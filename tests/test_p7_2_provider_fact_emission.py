"""P7.2 — the fact producer exists.

P7.1 removed provider-id guessing from consumers and left the gap visible: the
schema declared locality / licence class / capability state, but nothing produced
them, so every real decision reported UNRESOLVED and failed closed. Safe, and
unusable.

These tests pin the other end of that chain — ``ProviderCatalogue`` →
``evaluate_provider_policy`` → ``ProviderDecision`` — and pin the two rules that
make it trustworthy: the evaluator never guesses, and it never crosses into
production authority.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib

import pytest

from hevi.production.p7 import (
    AssetRequirement,
    AssetSemanticRole,
    MediaType,
    SourcePolicy,
    evaluate_policy,
)
from hevi.provider_policy.policy import (
    ProviderCapabilityState,
    ProviderLicenseClass,
    ProviderLocality,
    ProviderPolicy,
    evaluate_provider_policy,
)
from hevi.providers.facts import (
    PROVIDER_CATALOGUE,
    ProviderCatalogue,
    ProviderKind,
    ProviderProfile,
)

POLICY_SRC = pathlib.Path("hevi/provider_policy/policy.py")
FACTS_SRC = pathlib.Path("hevi/providers/facts.py")

ACME = ProviderProfile(
    "acme.internal-image",
    ProviderKind.IMAGE,
    ProviderLocality.LOCAL,
    ProviderLicenseClass.LICENSED,
    ProviderCapabilityState.AVAILABLE,
    ("stock",),
)
ACME_CATALOGUE = ProviderCatalogue((ACME,))


def _requirement(source_policy: SourcePolicy) -> AssetRequirement:
    return AssetRequirement(
        media_type=MediaType.IMAGE,
        semantic_role=AssetSemanticRole.PROP,
        source_policy=source_policy,
    )


def _evaluate(providers: list[str], catalogue=None):
    """evaluate_provider_policy is async; tests drive it synchronously."""
    return asyncio.run(
        evaluate_provider_policy(
            ProviderPolicy(candidates=providers, quality_floor=1), catalogue=catalogue
        )
    )


def _eligible(source_policy: SourcePolicy, providers: list[str], catalogue=None):
    """evaluate() then P7 policy — the chain P7.2 closes."""
    decision = _evaluate(providers, catalogue)
    return decision, evaluate_policy(_requirement(source_policy), decision)


# ── acceptance criterion 1: catalogue facts reach the decision, verbatim ──


def test_catalogue_facts_are_carried_exactly():
    decision, _ = _eligible(SourcePolicy.LOCAL_ONLY, ["acme.internal-image"], ACME_CATALOGUE)
    assert decision.locality == {"acme.internal-image": ProviderLocality.LOCAL}
    assert decision.license_class == {"acme.internal-image": ProviderLicenseClass.LICENSED}
    assert decision.capability_states == {
        "acme.internal-image": ProviderCapabilityState.AVAILABLE
    }


def test_local_licensed_provider_is_accepted_by_both_policies():
    """The spec's worked example: LOCAL_ONLY accepts, LICENSED_ONLY accepts."""
    _, local = _eligible(SourcePolicy.LOCAL_ONLY, ["acme.internal-image"], ACME_CATALOGUE)
    _, licensed = _eligible(SourcePolicy.LICENSED_ONLY, ["acme.internal-image"], ACME_CATALOGUE)
    assert "acme.internal-image" in local.allowed_ids
    assert "acme.internal-image" in licensed.allowed_ids


def test_declared_facts_survive_the_full_14_provider_fleet():
    """Every provider the policy can select must have declared facts."""
    from hevi.video.capability_guard import PROVIDER_LIMITS

    decision = asyncio.run(evaluate_provider_policy(ProviderPolicy(quality_floor=1)))
    assert set(PROVIDER_LIMITS) <= set(decision.locality)
    assert set(PROVIDER_LIMITS) <= set(decision.license_class)
    assert set(PROVIDER_LIMITS) <= set(decision.capability_states)


# ── acceptance criterion 2: one fact source, no second assembly ──


def test_evaluator_reads_the_catalogue_it_is_given():
    other = ProviderCatalogue(
        (
            ProviderProfile(
                "acme.internal-image",
                ProviderKind.IMAGE,
                ProviderLocality.REMOTE,
                ProviderLicenseClass.GENERATED,
            ),
        )
    )
    decision = _evaluate(["acme.internal-image"], other)
    assert decision.locality["acme.internal-image"] is ProviderLocality.REMOTE
    assert decision.license_class["acme.internal-image"] is ProviderLicenseClass.GENERATED


def test_catalogue_is_the_module_level_singleton():
    from hevi.providers.facts import PROVIDER_CATALOGUE as imported_twice

    assert imported_twice is PROVIDER_CATALOGUE


def test_unknown_provider_yields_no_facts_rather_than_empty_strings():
    facts = PROVIDER_CATALOGUE.facts_for("never.declared")
    assert facts == {"locality": {}, "license_class": {}, "capability_states": {}}


def test_every_catalogue_profile_is_internally_valid():
    for provider_id in PROVIDER_CATALOGUE.list_ids():
        profile = PROVIDER_CATALOGUE.resolve(provider_id)
        assert profile.provider_id == provider_id
        assert isinstance(profile.locality, ProviderLocality)
        assert isinstance(profile.license_class, ProviderLicenseClass)
        assert isinstance(profile.capability_state, ProviderCapabilityState)


def test_duplicate_registration_is_rejected():
    with pytest.raises(ValueError, match="PROVIDER_PROFILE_DUPLICATE"):
        ProviderCatalogue((ACME,)).register(ACME)


@pytest.mark.parametrize(
    "field,value,error",
    [
        ("provider_id", "", "PROVIDER_PROFILE_WITHOUT_ID"),
        ("locality", "on-prem", "UNKNOWN_PROVIDER_LOCALITY"),
        ("license_class", "public-domain", "UNKNOWN_LICENSE_CLASS"),
        ("capability_state", "throttled", "UNKNOWN_CAPABILITY_STATE"),
    ],
)
def test_profile_rejects_undeclared_values(field, value, error):
    kwargs = {
        "provider_id": "p",
        "kind": ProviderKind.VIDEO,
        "locality": ProviderLocality.LOCAL,
        "license_class": ProviderLicenseClass.GENERATED,
        "capability_state": ProviderCapabilityState.AVAILABLE,
    }
    kwargs[field] = value
    with pytest.raises(ValueError, match=error):
        ProviderProfile(**kwargs)


# ── acceptance criterion 3: absence closes the loop ──


def test_missing_locality_is_unresolved_and_blocked():
    """A provider the catalogue does not know must be UNRESOLVED, never guessed."""
    decision, policy = _eligible(
        SourcePolicy.LOCAL_ONLY, ["acme.internal-image", "unlisted.provider"], ACME_CATALOGUE
    )
    assert decision.locality.get("unlisted.provider") is None
    assert "unlisted.provider" not in policy.allowed_ids
    assert "acme.internal-image" in policy.allowed_ids


def test_unlisted_provider_is_blocked_with_a_reason():
    _, policy = _eligible(SourcePolicy.LOCAL_ONLY, ["unlisted.provider"], ACME_CATALOGUE)
    assert "unlisted.provider" not in policy.allowed_ids
    assert policy.blocked_reasons()["unlisted.provider"]


def test_remote_provider_cannot_satisfy_local_only():
    remote_only = ProviderCatalogue(
        (ProviderProfile("remote.vp", ProviderKind.VIDEO, ProviderLocality.REMOTE,
                         ProviderLicenseClass.GENERATED),)
    )
    _, policy = _eligible(SourcePolicy.LOCAL_ONLY, ["remote.vp"], remote_only)
    assert "remote.vp" not in policy.allowed_ids
    assert "REMOTE" in policy.blocked_reasons()["remote.vp"]


def test_generated_material_cannot_satisfy_licensed_only():
    """Licence class is its own fact — a LOCAL provider still yields GENERATED."""
    _, policy = _eligible(SourcePolicy.LOCAL_ONLY, ["wan_local"], PROVIDER_CATALOGUE)
    _, licensed = _eligible(SourcePolicy.LICENSED_ONLY, ["wan_local"], PROVIDER_CATALOGUE)
    assert "wan_local" in policy.allowed_ids
    assert "wan_local" not in licensed.allowed_ids


def test_adoption_state_is_declared_and_enforced():
    """Adoption state is declared data, and it now actually gates selection.

    Originally this asserted `happyhorse_1_1_maas_lock` was NOT_ADOPTED. That was
    wrong about the repository: the provider is referenced by `longvideo_orchestrator`,
    `director`, `shortdrama` and `director_pipeline`, and `registry.py` names it the
    mainline create_episode/Series path. The state contradicted all of that.

    Worse, the state was inert — `policy.py` populated `capability_states` and never
    read it — so a wrong value produced no symptom and survived. P0-4.2 made
    adoption state gate selection, which means the wrong value would have denied the
    mainline provider outright. The test now pins the corrected value *and* the fact
    that enforcement exists, because "declared" without "enforced" is what let this
    drift.
    """
    from hevi.provider_policy.policy import _SELECTABLE_STATES

    profile = PROVIDER_CATALOGUE.resolve("happyhorse_1_1_maas_lock")
    assert profile.capability_state is ProviderCapabilityState.AVAILABLE
    assert profile.capability_state in _SELECTABLE_STATES

    # A non-selectable state remains representable and remains a refusal.
    assert ProviderCapabilityState.BLOCKED not in _SELECTABLE_STATES
    assert ProviderCapabilityState.FAILED not in _SELECTABLE_STATES
    assert ProviderCapabilityState.NOT_ADOPTED not in _SELECTABLE_STATES

    # And nothing is currently marked unadopted, which is itself the correction:
    # the sole NOT_ADOPTED row was the mainline provider.
    assert PROVIDER_CATALOGUE.by_capability_state(
        ProviderCapabilityState.NOT_ADOPTED
    ) == ()


# ── acceptance criterion 1, restated as an absence: no guessing anywhere ──


def test_no_source_under_test_contains_a_name_based_locality_guess():
    for source in (POLICY_SRC, FACTS_SRC):
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = getattr(func, "attr", getattr(func, "id", ""))
            if name not in {"startswith", "endswith", "split", "partition"}:
                continue
            for arg in node.args[:1]:
                literal = None
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    literal = arg.value
                if literal and any(
                    token in literal.lower() for token in ("local", "remote", "cloud", "host")
                ):
                    raise AssertionError(
                        f"{source.name}:{node.lineno} infers locality from a name: {literal!r}"
                    )


def test_catalogue_module_derives_no_locality_from_ids():
    """'local' appears only as a comment or enum member, never as a test on an id."""
    text = FACTS_SRC.read_text()
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) and not isinstance(node, ast.BoolOp):
            continue
        segment = ast.get_source_segment(text, node) or ""
        if "provider_id" in segment and (" in " in segment or "==" in segment):
            assert "local" not in segment.lower(), (
                f"facts.py:{node.lineno} branches on provider_id: {segment}"
            )


def test_locality_is_independent_of_the_name():
    """Same declared locality for names that read oppositely."""
    oddly_named = ProviderProfile(
        "local-looking-remote-vp", ProviderKind.VIDEO, ProviderLocality.REMOTE,
        ProviderLicenseClass.GENERATED,
    )
    _, policy = _eligible(
        SourcePolicy.LOCAL_ONLY, ["local-looking-remote-vp"], ProviderCatalogue((oddly_named,))
    )
    assert "local-looking-remote-vp" not in policy.allowed_ids


# ── acceptance criterion 4: the evaluator stops at eligibility + facts ──


def test_evaluator_module_imports_no_production_or_sourcing_authority():
    tree = ast.parse(POLICY_SRC.read_text())
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        for module in modules:
            assert not module.startswith("hevi.production"), (
                f"provider policy must not import {module}"
            )
            assert not module.startswith("hevi.sourcing"), (
                f"provider policy must not import {module}"
            )


def test_evaluator_defines_no_asset_or_execution_state():
    text = POLICY_SRC.read_text()
    tree = ast.parse(text)
    for node in ast.walk(tree):
        name = getattr(node, "name", "")
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            for forbidden in ("AssetDecision", "RunState", "ExecutionReceipt", "Receipt"):
                assert forbidden not in name, (
                    f"{name} is not provider policy's to define"
                )
    for forbidden in ("AssetDecision", "RunState", "ExecutionReceipt"):
        assert f"{forbidden}." not in text, f"policy must not produce {forbidden}"


def test_evaluator_returns_provider_decision_only():
    decision = _evaluate(["wan_local"])
    assert type(decision).__name__ == "ProviderDecision"
    assert not hasattr(decision, "asset_decision")
    assert not hasattr(decision, "run_state")
    assert not hasattr(decision, "receipt")


# ── backward compatibility ──


def test_facts_default_empty_so_existing_callers_are_unaffected():
    from hevi.provider_policy.policy import ProviderDecision

    decision = ProviderDecision()
    assert decision.locality == {}
    assert decision.license_class == {}
    assert decision.capability_states == {}


def test_default_catalogue_is_used_when_none_injected():
    decision = _evaluate(["wan_local", "veo3"])
    assert decision.locality["wan_local"] is ProviderLocality.LOCAL
    assert decision.locality["veo3"] is ProviderLocality.REMOTE
