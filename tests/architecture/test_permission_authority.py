"""P0-4.1 — permission/tenancy is an admission authority, not a route helper.

The tests here pin the three properties that matter:

1. Deny by default. An undeclared tenant, a missing principal, or an
   out-of-scope provider must refuse. There is no implicit "the route already
   authenticated the caller, therefore the worker may execute".
2. A refusal is a first-class record. It is persisted on the task row, not only
   logged, so the refusal survives the process that made it.
3. A refusal is inert. No attempt row, no executor dispatch, no budget settle or
   release — only the reservation stays ``held``.

The remaining tests pin the scope grammar, which is a configuration surface and
therefore deserves a parser test rather than a prose comment.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from obase.persistence import PgPool

from hevi.provider_policy.permission import (
    BudgetEffect,
    OperationKind,
    PermissionError,
    PermissionRequest,
    TenantScope,
    evaluate_permission,
    require_permission,
    resolver_from_settings,
)
from hevi.tasks.repository import TaskRepository
from hevi.tasks.task_service import TaskService

# A scope wide enough to admit the fixtures below and nothing more.
SCOPE = "ws-1|wan_local,wan_cloud|director_graph|t2v|render,regenerate|100.0"

# A deliberately narrow scope, for the "the seam refuses" tests.
NARROW = "ws-1|wan_local||t2v|render|100.0"


def _task(**over: Any) -> dict[str, Any]:
    task: dict[str, Any] = {
        "id": uuid.uuid4(),
        "topic": "t",
        "duration_archetype": "1-5min",
        "video_provider": "wan_local",
        "audio_provider": "a",
        "user_id": "user-1",
        "config_json": {
            "workspace_id": "ws-1",
            "production_source": "director_graph",
            "required_capabilities": ["t2v"],
        },
        "status": "pending",
        "progress_pct": 0.0,
    }
    task.update(over)
    return task


def _request(**over: Any) -> PermissionRequest:
    """Build a request from a realistic task row, then override fields.

    ``dataclasses.replace`` rather than ``setattr`` because the request is frozen;
    frozenness is itself the property that stops an admission decision from being
    rewritten after it is made.
    """
    return replace(
        PermissionRequest.from_task(
            _task(), provider="wan_local", operation=OperationKind.RENDER
        ),
        **over,
    )


# ---------------------------------------------------------------- allow side


def test_declared_scope_admits():
    decision = evaluate_permission(_request(), resolver_from_settings(SCOPE))
    assert decision.allowed
    assert decision.tenant_id == "ws-1"
    assert decision.budget_effect is BudgetEffect.HELD
    assert {c["check"] for c in decision.to_dict()["checks"]} >= {
        "principal_present",
        "tenant_resolved",
        "scope_configured",
        "provider_in_scope",
        "capabilities_in_scope",
        "operation_permitted",
        "budget_authority",
        "execution_target_permitted",
    }


# ---------------------------------------------------------------- deny side


def test_missing_principal_denies():
    req = _request(principal=None)
    decision = evaluate_permission(req, resolver_from_settings(SCOPE))
    assert not decision.allowed
    assert "no_principal" in decision.reason()


def test_missing_workspace_denies_as_unknown_tenant():
    req = _request(tenant_id=None)
    decision = evaluate_permission(req, resolver_from_settings(SCOPE))
    assert not decision.allowed
    assert "unknown_tenant" in decision.reason()


def test_undeclared_tenant_denies_even_with_a_principal():
    req = _request(tenant_id="ws-not-declared")
    decision = evaluate_permission(req, resolver_from_settings(SCOPE))
    assert not decision.allowed
    assert "unknown_tenant" in decision.reason()


def test_no_configured_scopes_denies_everything():
    """The empty-configuration default is the fail-closed guarantee.

    A deployment that has not declared any tenant scope can run nothing. This is
    the test that fails loudly if someone reaches for a permissive default.
    """
    decision = evaluate_permission(_request(), resolver_from_settings(""))
    assert not decision.allowed
    assert "unknown_tenant" in decision.reason()


def test_provider_outside_scope_denies():
    req = _request(provider="wan_secret")
    decision = evaluate_permission(req, resolver_from_settings(NARROW))
    assert not decision.allowed
    assert "provider_outside_tenant_scope" in decision.reason()


def test_capability_outside_scope_denies():
    req = _request(capabilities=frozenset({"lipsync"}))
    decision = evaluate_permission(req, resolver_from_settings(NARROW))
    assert not decision.allowed
    assert "capability_outside_tenant_scope" in decision.reason()


def test_operation_outside_scope_denies():
    req = _request(operation=OperationKind.ADMIN)
    decision = evaluate_permission(req, resolver_from_settings(NARROW))
    assert not decision.allowed
    assert "operation_not_permitted" in decision.reason()


def test_execution_target_outside_scope_denies():
    req = _request(execution_target="explainer")
    decision = evaluate_permission(req, resolver_from_settings(SCOPE))
    assert not decision.allowed
    assert "execution_target_denied" in decision.reason()


def test_budget_ceiling_denies_an_overspend_intent():
    req = _request(estimated_cost_usd=250.0)
    decision = evaluate_permission(req, resolver_from_settings(SCOPE))
    assert not decision.allowed
    assert "budget_ceiling_exceeded" in decision.reason()


def test_budget_without_authority_denies():
    """A tenant with no providers is not spendable.

    Budget authority is derived from the scope, so the cheapest way to express
    "declared but not permitted to spend" is a provider-less tenant. It must be
    refused on both counts rather than slipping through on the authority check.
    """
    req = _request()
    decision = evaluate_permission(req, resolver_from_settings("ws-1|||render|100.0"))
    assert not decision.allowed
    assert "tenant_scope_not_configured" in decision.reason()
    assert "budget_authority_denied" in decision.reason()


def test_admin_operation_denies_even_under_a_deliberately_wide_scope():
    """Naming an admin operation in a scope must not actually grant it.

    This is the `require_admin`-promotion trap. If a tenant scope could grant
    ADMIN by configuration, then an operator editing settings would hold a
    capability that HTTP-level guards assume only an explicit admin route can
    reach. Admin is therefore refused for every tenant scope.
    """
    req = _request(
        tenant_id="ws-1", provider="wan_local", execution_target="director_graph",
        operation=OperationKind.ADMIN,
    )
    decision = evaluate_permission(
        req, resolver_from_settings("ws-1|wan_local|director_graph||render,admin|100.0")
    )
    assert not decision.allowed
    assert "operation_not_permitted" in decision.reason()


def test_empty_budget_is_not_a_denial():
    """No cost estimate is not a free pass and not a refusal either.

    An absent budget is unknown rather than over-limit, so it must not be reported
    as a budget denial. Real spending control belongs to the budget stage.
    """
    req = _request(estimated_cost_usd=None)
    decision = evaluate_permission(req, resolver_from_settings(SCOPE))
    assert decision.allowed


def test_require_permission_raises_on_denial():
    with pytest.raises(PermissionError) as exc:
        require_permission(_request(tenant_id="nope"), resolver_from_settings(SCOPE))
    assert "unknown_tenant" in str(exc.value)


# ------------------------------------------------------------ scope grammar


def _scope(line: str) -> TenantScope:
    """Resolve one declared line to its scope, failing loudly if it was dropped."""
    resolver = resolver_from_settings(line)
    scope = resolver.scope_for(line.split("|")[0])
    assert scope is not None, f"scope line was dropped by the parser: {line!r}"
    return scope


def test_scope_grammar_parses_all_fields():
    scope = _scope(SCOPE)
    assert scope.tenant_id == "ws-1"
    assert scope.permitted_providers == frozenset({"wan_local", "wan_cloud"})
    assert scope.permitted_execution_targets == frozenset({"director_graph"})
    assert scope.permitted_capabilities == frozenset({"t2v"})
    assert scope.permitted_operations == frozenset(
        {OperationKind.RENDER, OperationKind.REGENERATE}
    )
    assert scope.max_estimated_cost_usd == 100.0


@pytest.mark.parametrize(
    ("line", "why"),
    [
        ("ws-1", "no field separator"),
        ("|wan_local|||render|100.0", "empty tenant id"),
    ],
)
def test_scope_grammar_drops_malformed_lines(line: str, why: str):
    """A bad line must not become a scope, and must not crash the process.

    Guessing at a malformed scope would be the dangerous failure: a line the
    operator meant to restrict would instead silently widen. Dropping it means the
    tenant is simply unknown, which denies.
    """
    assert resolver_from_settings(line).scope_for(line.split("|")[0] or "ws-1") is None


def test_scope_grammar_ignores_unknown_operations_rather_than_failing():
    """An unrecognised operation name narrows nothing it should not.

    `render,delete_everything` keeps RENDER and drops the rest. Refusing the whole
    line would let one typo lock a tenant out entirely.
    """
    scope = _scope("ws-1|wan_local||t2v|render,delete_everything|100.0")
    assert scope.permitted_operations == frozenset({OperationKind.RENDER})


def test_scope_grammar_treats_a_blank_ceiling_as_no_ceiling():
    """A blank budget field means 'no cap', not 'zero cap'.

    Confusing the two would deny every paid render on an operator's typo, which
    reads as a broken deployment rather than a rejected one.
    """
    scope = _scope("ws-1|wan_local|||render|")
    assert scope.max_estimated_cost_usd is None


def test_blank_capability_and_target_fields_are_unconstrained():
    """The asymmetry between fields is deliberate and worth pinning.

    An empty *providers* field means the tenant is not configured and is denied,
    because the provider list is the authority itself. Empty *capability* or
    *target* fields mean "not narrowed": they refine an already-admitted request
    rather than granting it.
    """
    scope = _scope("ws-1|wan_local|||render|100.0")
    assert scope.permitted_capabilities == frozenset()
    assert scope.permitted_execution_targets == frozenset()

    unconfigured = _scope("ws-1||t2v|render|100.0")
    assert unconfigured.permitted_providers == frozenset()
    decision = evaluate_permission(_request(), resolver_from_settings(
        "ws-1||t2v|render|100.0"))
    assert not decision.allowed
    assert "tenant_scope_not_configured" in decision.reason()


# ---------------------------------------------------- seam integration shape


def test_permission_precedes_attempt_and_dispatch():
    """Structural pin: refusal must be upstream of any side effect.

    This reads the method source rather than running it, because the property is
    about ordering across a 600-line method where a future edit could easily move
    the block. The behavioural no-dispatch test below covers the outcome; this one
    covers the placement so the outcome cannot be satisfied accidentally.
    """
    import inspect

    src = inspect.getsource(TaskService._run_task_impl)
    assert src.index("_apply_provider_policy") < src.index("_start_attempt")


@pytest.mark.asyncio
async def test_denied_task_makes_no_attempt_and_no_dispatch():
    repository = TaskRepository(object())  # non-PgPool: no persistence, no DB
    svc = TaskService(repository, scope_resolver=resolver_from_settings(SCOPE))
    task = _task()
    task["config_json"] = {**task["config_json"], "workspace_id": "ws-unknown"}

    with (
        patch.object(repository, "get_task", return_value=task),
        patch.object(repository, "update_task", new_callable=AsyncMock),
        patch.object(svc, "_start_attempt", new_callable=AsyncMock) as start_attempt,
        patch("hevi.tasks.task_service.orchestrate_longvideo", new_callable=AsyncMock) as orch,
    ):
        with pytest.raises(PermissionError):
            await svc._apply_provider_policy(task)

    start_attempt.assert_not_awaited()
    orch.assert_not_awaited()


@pytest.mark.asyncio
async def test_refusal_is_persisted_on_the_task_row():
    """A denial that exists only in a log line cannot be audited."""
    pool = PgPool.__new__(PgPool)  # type-only: these paths test isinstance()
    repository = TaskRepository(pool)
    svc = TaskService(repository, scope_resolver=resolver_from_settings(SCOPE))
    task = _task()
    task["config_json"] = {**task["config_json"], "workspace_id": "ws-unknown"}

    with patch.object(repository, "update_task", new_callable=AsyncMock) as update:
        with pytest.raises(PermissionError):
            await svc._apply_provider_policy(task)

    update.assert_awaited_once()
    payload = update.await_args.args[1]
    assert "permission_decision" in payload["config_json"]
    decision = payload["config_json"]["permission_decision"]
    assert decision["allowed"] is False
    assert "unknown_tenant" in decision["reason"]


@pytest.mark.asyncio
async def test_allow_also_persists_a_record():
    """Admission is auditable in both directions.

    Only recording refusals makes it impossible to reconstruct why a task ran,
    which is the question an incident review actually asks.
    """
    pool = PgPool.__new__(PgPool)  # type-only: these paths test isinstance()
    repository = TaskRepository(pool)
    svc = TaskService(repository, scope_resolver=resolver_from_settings(SCOPE))
    task = _task()

    with (
        patch.object(repository, "update_task", new_callable=AsyncMock) as update,
        # Provider selection runs *after* permission and has its own authority
        # (P0-4.2). Stubbing it keeps these tests on the permission record instead
        # of making them depend on the catalogue and a live health row.
        patch(
            "hevi.provider_policy.evaluate_provider_policy",
            return_value=MagicMock(provider="wan_local", rationale="stubbed"),
        ),
    ):
        await svc._apply_provider_policy(task)

        assert update.await_count == 2  # permission decision, then provider selection
    payload = update.await_args_list[0].args[1]
    assert payload["config_json"]["permission_decision"]["allowed"] is True
    assert isinstance(payload["updated_at"], datetime)


@pytest.mark.asyncio
async def test_decision_never_reaches_orchestration_kwargs():
    """The admission record must not leak into the creative render call.

    ``config_json`` is splatted as ``**kwargs`` into ``orchestrate_longvideo``,
    so persisting the decision into that same dict would turn an audit field into a
    required render parameter. The persisted row and the in-memory config are
    deliberately different objects.
    """
    pool = PgPool.__new__(PgPool)  # type-only: these paths test isinstance()
    repository = TaskRepository(pool)
    svc = TaskService(repository, scope_resolver=resolver_from_settings(SCOPE))
    task = _task()

    with (
        patch.object(repository, "update_task", new_callable=AsyncMock),
        patch(
            "hevi.provider_policy.evaluate_provider_policy",
            return_value=MagicMock(provider="wan_local", rationale="stubbed"),
        ),
    ):
        await svc._apply_provider_policy(task)

    assert "permission_decision" not in task["config_json"]


# ------------------------------------------------------- API tenant plumbing


def test_public_task_request_can_declare_a_tenant():
    """The API must have a way to name a tenant, or fail-closed denies everything.

    Without a field to carry the tenant, `workspace_id` can never reach
    `config_json`, every API-created task is refused, and the deployment cannot
    run at all. This test fails loudly if the field is removed rather than letting
    the whole HTTP suite fail with a confusing credit-balance assertion.
    """
    from hevi.api.routers.tasks import LongVideoRequest

    assert "workspace_id" in LongVideoRequest.model_fields


def test_declared_tenant_is_not_derivable_from_the_user():
    """The tenant is caller-declared, and that is a known gap rather than a design.

    `user_id` is set from the authenticated session, but no workspace/membership
    model exists, so the tenant cannot be resolved server-side. Pinning the field
    as an explicit input keeps the debt visible: the day a membership model lands,
    this is the line that should stop trusting the caller.
    """
    from hevi.api.routers.tasks import LongVideoRequest

    field = LongVideoRequest.model_fields["workspace_id"]
    assert field.default is None
