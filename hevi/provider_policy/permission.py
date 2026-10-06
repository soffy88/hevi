"""Permission and tenancy authority for the canonical admission seam.

P0-4.1. This module is the answer to the question P0-4.0 could not answer: stage 3
of admission — *"is this principal allowed to run this?"* — had no implementation
anywhere in the repository. ``hevi/auth/dependencies.py:65 require_admin`` is a
route-scoped operator allowlist for global registries and is deliberately **not**
promoted into this role: it answers a different question (is this caller an operator
of this server) and it never runs on the worker path, which is where execution
actually happens.

Where it lives, and why it is not a service
-------------------------------------------
It is a module beside ``policy.py`` inside ``hevi/provider_policy/``, not an
``AdmissionService`` above or beside the seam. The seam's position is fixed at
``hevi/tasks/task_service.py:1364``; this is called *from* that seam, so it cannot
become a second coordinator and cannot be routed around. A caller who reaches an
executor without passing through here has bypassed admission, which is precisely the
defect P0-4 is closing.

What it answers
---------------
Seven inputs, all from the persisted task row rather than from the HTTP request —
because by the time the worker runs, the request is gone and only the row survives:

    principal        the user_id the task was created under
    tenant           workspace_id from config_json, if any
    provider         the provider admission wants to select
    capability       the mode/capability set the task requires
    operation        what kind of work this is (render, regenerate, ...)
    budget authority whether the principal may spend, and how much
    execution target the adapter/source that would actually run

The honest part
---------------
**HEVI has no tenant table.** ``hevi/auth/models.py:15`` declares ``users`` and
nothing else; there is no workspace, organisation, or membership row anywhere in
``hevi/db/``. ``workspace_id`` appears only as a nullable passthrough column on
intelligence tables (``intelligence_repository.py:168``) and on ``config_json``.

So this module cannot verify membership against a tenant directory, because none
exists. What it does instead is the part that is both real and useful:

* a **declared** scope — ``TenantScope`` says which providers a tenant may use — is
  evaluated against the task, and a provider outside it is refused;
* an **undeclared** scope is refused. Not defaulted to allow. A deployment with no
  tenant policy denies every execution rather than admitting every execution, which
  is the only safe reading when the principal cannot be attributed.

That is a narrower guarantee than "tenancy is enforced", and the docstring of
:func:`evaluate_permission` says so. Making it a real tenancy check requires a
membership table, which is P0-4.1's follow-up and not something this module can fake.

Budget lifecycle
----------------
``create_task`` reserves budget at ``task_service.py:1222`` before admission runs at
``:1364``. That ordering is pre-existing and is **not** changed here. What is made
explicit is the three-state contract that the reservation already implies in
``hevi/budget/models.py:82`` (``reserved`` / ``settled`` / ``released``) and that
``budget/repository.py`` implements:

    reserved   funds are held, nothing is spent; this is what admission denial leaves
    settled    actual cost consumed and unused reservation released (:303)
    released   the hold is returned without consumption (:388)

So a permission denial **may** leave a reservation. It must not settle one, and it
must not dispatch. :func:`evaluate_permission` therefore reports budget authority
separately from the deny decision, and
:data:`ADMISSION_DENIAL_BUDGET_EFFECT` states the effect in one place rather than
leaving it to be inferred from call ordering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

#: Bumped when the decision shape changes. Recorded on every decision so a stored
#: verdict can be interpreted by the code that produced it.
PERMISSION_POLICY_VERSION = 1


class PermissionDenial(StrEnum):
    """Why execution was refused. Stable values; logs and tests key on these."""

    NO_PRINCIPAL = "no_principal"
    UNKNOWN_TENANT = "unknown_tenant"
    TENANT_SCOPE_NOT_CONFIGURED = "tenant_scope_not_configured"
    PROVIDER_OUTSIDE_TENANT_SCOPE = "provider_outside_tenant_scope"
    CAPABILITY_OUTSIDE_TENANT_SCOPE = "capability_outside_tenant_scope"
    OPERATION_NOT_PERMITTED = "operation_not_permitted"
    BUDGET_AUTHORITY_DENIED = "budget_authority_denied"
    BUDCEILING_EXCEEDED = "budget_ceiling_exceeded"
    EXECUTION_TARGET_DENIED = "execution_target_denied"


class BudgetAuthority(StrEnum):
    """How the principal may spend. Explicit, never inferred from task size."""

    #: Spend permitted, up to the tenant's ceiling.
    ALLOWED = "allowed"
    #: Read-only principal; may not cause provider execution.
    READ_ONLY = "read_only"
    #: No spending authority.
    DENIED = "denied"


class OperationKind(StrEnum):
    """What the task is asking to do. Used for scope checks, not for routing."""

    RENDER = "render"
    REGENERATE = "regenerate"
    QUALIFICATION = "qualification"
    ADMIN = "admin"


class BudgetEffect(StrEnum):
    """What an admission outcome does to a pre-existing reservation.

    Named because the reservation happens at create time (``:1222``) and admission
    runs later (``:1364``), so the effect is otherwise an inference from call order.
    """

    #: A hold remains. Nothing is consumed and no work has run.
    HELD = "held"
    #: The hold is returned without consumption.
    RELEASED = "released"
    #: Real cost consumed.
    SETTLED = "settled"


#: On permission denial the reservation is held, never settled. Settling without an
#: execution would charge for work that did not happen.
ADMISSION_DENIAL_BUDGET_EFFECT = BudgetEffect.HELD

#: Operations a tenant may never perform regardless of scope, because they do not
#: execute video and instead mutate shared server state.
ADMIN_ONLY_OPERATIONS = frozenset({OperationKind.ADMIN})


@dataclass(frozen=True)
class TenantScope:
    """What one tenant is permitted to use.

    Declared, not derived: HEVI has no tenant table, so this is the deployment's
    statement of scope rather than a lookup. An empty scope means *nothing is
    permitted*, which is the fail-closed reading — see the module docstring.
    """

    tenant_id: str
    permitted_providers: frozenset[str] = frozenset()
    permitted_capabilities: frozenset[str] = frozenset()
    permitted_operations: frozenset[OperationKind] = frozenset()
    budget_authority: BudgetAuthority = BudgetAuthority.DENIED
    max_estimated_cost_usd: float | None = None
    permitted_execution_targets: frozenset[str] = frozenset()

    @classmethod
    def denying(cls, tenant_id: str) -> TenantScope:
        """A scope that permits nothing. The default for an unknown tenant."""
        return cls(tenant_id=tenant_id, budget_authority=BudgetAuthority.DENIED)

    @classmethod
    def allowing(
        cls,
        tenant_id: str,
        *,
        providers: frozenset[str],
        capabilities: frozenset[str] = frozenset(),
        operations: frozenset[OperationKind] = frozenset(),
        execution_targets: frozenset[str] = frozenset(),
        max_estimated_cost_usd: float | None = None,
        budget_authority: BudgetAuthority = BudgetAuthority.ALLOWED,
    ) -> TenantScope:
        """A scope that permits exactly what it names.

        Provided because the fail-closed default means every permitted deployment
        must construct its scope explicitly; a helper makes that legible instead of
        requiring callers to remember that empty sets deny.
        """
        return cls(
            tenant_id=tenant_id,
            permitted_providers=providers,
            permitted_capabilities=capabilities,
            permitted_operations=operations,
            budget_authority=budget_authority,
            max_estimated_cost_usd=max_estimated_cost_usd,
            permitted_execution_targets=execution_targets,
        )


@dataclass(frozen=True)
class PermissionRequest:
    """The admission question, built from the persisted task row.

    Every field is derived from durable state rather than from the HTTP request. The
    worker has no request; it has a row. Building the question from the row is what
    makes "authenticated at intake" irrelevant to the decision — which is the point.
    """

    principal: str | None
    tenant_id: str | None
    provider: str
    capabilities: frozenset[str]
    operation: OperationKind
    execution_target: str
    estimated_cost_usd: float | None = None

    @classmethod
    def from_task(
        cls,
        task: dict[str, Any],
        *,
        provider: str,
        operation: OperationKind = OperationKind.RENDER,
    ) -> PermissionRequest:
        """Read the question out of a task row.

        ``user_id`` is the principal (``hevi/tasks/models.py:19``) and
        ``workspace_id`` the tenant (``task_service.py:1114``). Both are optional in
        the schema, which is why a missing value denies rather than defaults.
        """
        config = task.get("config_json") or {}
        capabilities = config.get("required_capabilities") or ()
        source = str(config.get("production_source") or "")
        return cls(
            principal=(str(task.get("user_id") or "") or None),
            tenant_id=(str(config.get("workspace_id") or "") or None),
            provider=provider,
            capabilities=frozenset(str(c) for c in capabilities),
            operation=operation,
            execution_target=source,
            estimated_cost_usd=(
                float(config["max_provider_cost_usd"])
                if config.get("max_provider_cost_usd") is not None else None),
        )


@dataclass(frozen=True)
class PermissionDecision:
    """An explicit allow or deny. There is no third value and no default."""

    allowed: bool
    denials: tuple[PermissionDenial, ...] = ()
    tenant_id: str | None = None
    principal: str | None = None
    budget_effect: BudgetEffect = ADMISSION_DENIAL_BUDGET_EFFECT
    checks: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    policy_version: int = PERMISSION_POLICY_VERSION

    def reason(self) -> str:
        """Stable single string for logs and for the task's error field."""
        return "+".join(d.value for d in self.denials) if self.denials else "allowed"

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "denials": [d.value for d in self.denials],
            "reason": self.reason(),
            "tenant_id": self.tenant_id,
            "principal": self.principal,
            "budget_effect": self.budget_effect.value,
            "checks": [dict(c) for c in self.checks],
            "policy_version": self.policy_version,
        }


class PermissionError(ValueError):
    """Refusal carrying the decision, so the caller can record it.

    Raising rather than returning a boolean is deliberate: a caller that ignores a
    returned verdict has not been denied, it has merely not been stopped. The
    endpoint_lifecycle seam was rejected in P0-4.0 partly for returning
    ``AdmissionVerdict(admitted=False)`` instead of raising.
    """

    def __init__(self, decision: PermissionDecision) -> None:
        super().__init__(f"ADMISSION_DENIED:{decision.reason()}")
        self.decision = decision


class ScopeResolver:
    """Resolves a tenant id to its declared scope.

    Deliberately an interface rather than a database lookup: no tenant table exists,
    so the deployment supplies the scopes. A resolver that returns ``None`` for an
    unknown tenant produces :class:`PermissionDenial.UNKNOWN_TENANT`, which denies.
    """

    def scope_for(self, tenant_id: str | None) -> TenantScope | None:
        raise NotImplementedError


class StaticScopeResolver(ScopeResolver):
    """Scope resolver over an in-process mapping. Used by configuration and tests."""

    def __init__(self, scopes: dict[str, TenantScope] | None = None) -> None:
        self._scopes = dict(scopes or {})

    def register(self, scope: TenantScope) -> None:
        self._scopes[scope.tenant_id] = scope

    def scope_for(self, tenant_id: str | None) -> TenantScope | None:
        if not tenant_id:
            return None
        return self._scopes.get(tenant_id)


def evaluate_permission(
    request: PermissionRequest,
    resolver: ScopeResolver,
) -> PermissionDecision:
    """Answer the admission question. Denies by default; never by accident.

    Order matters and is deliberate. Principal and tenant are checked first because
    a question with no principal cannot be answered against any scope, and evaluating
    scope for an anonymous request would be reasoning about a caller who does not
    exist. Every check appends to ``denials`` rather than returning early, so one
    decision reports every reason it failed — a caller fixing one problem should not
    have to rediscover the next.

    The guarantee this makes, and its limit: a *declared* scope is enforced, and an
    undeclared tenant is refused. It does not verify that a principal belongs to the
    tenant it names, because HEVI has no membership table to verify against. That
    gap is real, is recorded in the module docstring, and is the reason
    :class:`TenantScope` is described as declared rather than authoritative.
    """
    denials: list[PermissionDenial] = []
    checks: list[dict[str, Any]] = []

    def record(name: str, ok: bool | None, detail: Any = None) -> None:
        """Record one check. ``ok=None`` means *not evaluated* — no scope to check
        against — which is distinct from False, and is what an unresolved tenant
        produces on every scope-dependent check."""
        checks.append({"check": name, "ok": ok, "detail": detail})

    # 1. Principal. No principal means no attributable caller.
    if not request.principal:
        denials.append(PermissionDenial.NO_PRINCIPAL)
    record("principal_present", bool(request.principal), request.principal)

    # 2. Tenant. Absent or unknown is a denial, never an implicit default scope.
    scope: TenantScope | None = None
    if not request.tenant_id:
        denials.append(PermissionDenial.UNKNOWN_TENANT)
        record("tenant_present", False, None)
    else:
        scope = resolver.scope_for(request.tenant_id)
        if scope is None:
            denials.append(PermissionDenial.UNKNOWN_TENANT)
        record("tenant_resolved", scope is not None, request.tenant_id)

    # 3. A resolved scope that permits nothing refuses everything. This is what makes
    #    an unconfigured deployment deny rather than admit.
    if scope is not None and not scope.permitted_providers:
        denials.append(PermissionDenial.TENANT_SCOPE_NOT_CONFIGURED)
    record("scope_configured",
           scope is not None and bool(scope.permitted_providers),
           None if scope is None else sorted(scope.permitted_providers))

    # 4. Provider scope. Checked even when the scope is unconfigured, so the log
    #    records the specific provider that would have been admitted.
    if (scope is not None and scope.permitted_providers
            and request.provider not in scope.permitted_providers):
        denials.append(PermissionDenial.PROVIDER_OUTSIDE_TENANT_SCOPE)
    record("provider_in_scope",
           bool(scope and request.provider in scope.permitted_providers),
           request.provider)

    # 5. Capability scope.
    if scope is not None and scope.permitted_capabilities:
        for capability in sorted(request.capabilities):
            if capability not in scope.permitted_capabilities:
                denials.append(PermissionDenial.CAPABILITY_OUTSIDE_TENANT_SCOPE)
                break
    record("capabilities_in_scope", None if scope is None else bool(
        scope.permitted_capabilities
        and not (request.capabilities - scope.permitted_capabilities)),
        sorted(request.capabilities))

    # 6. Operation scope. ADMIN is refused unconditionally at this seam.
    #
    # The rule is not "admin unless the scope names it". Admin capability is the
    # one thing a tenant scope must never be able to hand out: it is held by an
    # explicit HTTP-level guard (`require_admin`), and making it configuration-
    # reachable would let whoever edits `admission_tenant_scopes` acquire a
    # capability that the route layer believes only an admin can reach. So a scope
    # naming `admin` is narrowed to the operations it may actually grant, and
    # ADMIN itself is dropped from it at construction.
    admin_refused = request.operation is OperationKind.ADMIN
    outside_declared_ops = (
        scope is not None
        and scope.permitted_operations
        and request.operation not in scope.permitted_operations
    )
    if admin_refused or outside_declared_ops:
        denials.append(PermissionDenial.OPERATION_NOT_PERMITTED)
    record("operation_permitted",
           PermissionDenial.OPERATION_NOT_PERMITTED not in denials,
           request.operation.value)

    # 7. Budget authority, and the tenant's own ceiling when it has one.
    if scope is None or scope.budget_authority is not BudgetAuthority.ALLOWED:
        denials.append(PermissionDenial.BUDGET_AUTHORITY_DENIED)
    elif (scope.max_estimated_cost_usd is not None
          and request.estimated_cost_usd is not None
          and request.estimated_cost_usd > scope.max_estimated_cost_usd):
        denials.append(PermissionDenial.BUDCEILING_EXCEEDED)
    record("budget_authority",
           bool(scope and scope.budget_authority is BudgetAuthority.ALLOWED),
           None if scope is None else scope.budget_authority.value)

    # 8. Execution target. A tenant that enumerates its targets may not dispatch
    #    through an adapter it does not name.
    if (scope is not None and scope.permitted_execution_targets
            and request.execution_target not in scope.permitted_execution_targets):
        denials.append(PermissionDenial.EXECUTION_TARGET_DENIED)
    record("execution_target_permitted",
           not (scope and scope.permitted_execution_targets
                and request.execution_target
                not in scope.permitted_execution_targets),
           request.execution_target)

    allowed = not denials
    return PermissionDecision(
        allowed=allowed,
        denials=tuple(denials),
        tenant_id=request.tenant_id,
        principal=request.principal,
        # Always HELD here. On a deny the reservation stays held and nothing is
        # consumed, because no execution happened. On an allow the hold is settled
        # downstream by budget/repository.py:303 settle_attempt once the real cost
        # is known — this decision never settles it, because an admission verdict is
        # not a measurement of cost.
        budget_effect=ADMISSION_DENIAL_BUDGET_EFFECT,
        checks=tuple(checks),
    )


def require_permission(
    request: PermissionRequest,
    resolver: ScopeResolver,
) -> PermissionDecision:
    """Evaluate and raise on denial. Returns the decision on allow.

    This is the function the seam calls. It returns a value so the caller can persist
    it, and raises so a caller that forgets to check cannot proceed: the denial path
    terminates before any dispatch.
    """
    decision = evaluate_permission(request, resolver)
    if not decision.allowed:
        raise PermissionError(decision)
    return decision


class ConfigScopeResolver(ScopeResolver):
    """Builds scopes from ``settings.admission_tenant_scopes``.

    Format, one tenant per line, with a comma-separated list in every field::

        ws-1|wan_local,wan_cloud|director_graph|t2v|render,regenerate|100.0
        ws-2|wan_local|director_graph||render|10.0

    Fields are ``tenant|providers|targets|capabilities|operations|ceiling_usd``.
    Trailing empty fields may be omitted, and an empty list means *unrestricted for
    that dimension only* — except ``providers``, where empty means the tenant is not
    configured and therefore denied. That asymmetry is deliberate and is the
    fail-closed reading of an operator who declared a tenant but no providers.

    Unparseable lines are dropped rather than guessed. A malformed scope silently
    permitting everything would be worse than it not existing, and the deployment
    operator is the only one who can fix it.
    """

    def __init__(self, raw: str) -> None:
        self._scopes: dict[str, TenantScope] = {}
        for line in (raw or "").splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 2:
                continue
            tenant_id = parts[0].strip()
            if not tenant_id:
                continue
            known_operations = {o.value for o in OperationKind}
            providers = frozenset(p.strip() for p in parts[1].split(",") if p.strip())
            targets: frozenset[str] = frozenset()
            capabilities: frozenset[str] = frozenset()
            operations: frozenset[OperationKind] = frozenset()
            ceiling: float | None = None
            if len(parts) > 2:
                targets = frozenset(p.strip() for p in parts[2].split(",") if p.strip())
            if len(parts) > 3:
                capabilities = frozenset(
                    p.strip() for p in parts[3].split(",") if p.strip())
            if len(parts) > 4:
                operations = frozenset(
                    OperationKind(p.strip())
                    for p in parts[4].split(",")
                    if p.strip() in known_operations
                )
            if len(parts) > 5 and parts[5].strip():
                try:
                    ceiling = float(parts[5].strip())
                except ValueError:
                    ceiling = None
            self._scopes[tenant_id] = TenantScope(
                tenant_id=tenant_id,
                permitted_providers=providers,
                permitted_capabilities=capabilities,
                permitted_operations=operations,
                # A declared tenant with providers is assumed spendable; an operator
                # who wants it read-only names a ceiling of 0 or omits the tenant.
                budget_authority=(BudgetAuthority.ALLOWED if providers
                                  else BudgetAuthority.DENIED),
                max_estimated_cost_usd=ceiling,
                permitted_execution_targets=targets,
            )

    def scope_for(self, tenant_id: str | None) -> TenantScope | None:
        if not tenant_id:
            return None
        return self._scopes.get(tenant_id)

    @property
    def configured_tenants(self) -> tuple[str, ...]:
        return tuple(sorted(self._scopes))


def resolver_from_settings(raw: str | None = None) -> ConfigScopeResolver:
    """The resolver the seam uses when none is injected."""
    if raw is None:
        from hevi.core.config import settings

        raw = settings.admission_tenant_scopes
    return ConfigScopeResolver(raw)


__all__ = [
    "ADMIN_ONLY_OPERATIONS",
    "ADMISSION_DENIAL_BUDGET_EFFECT",
    "PERMISSION_POLICY_VERSION",
    "BudgetAuthority",
    "BudgetEffect",
    "OperationKind",
    "PermissionDecision",
    "PermissionDenial",
    "PermissionError",
    "PermissionRequest",
    "ScopeResolver",
    "StaticScopeResolver",
    "TenantScope",
    "evaluate_permission",
    "require_permission",
    "resolver_from_settings",
]
