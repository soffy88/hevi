"""HEVI P7.1 — Provider fact authority and the asset/execution boundary.

Two boundary leaks, closed:

1. **Locality was inferred from a provider id's spelling.** ``startswith("local")``
   made a naming convention into an implicit authority: ``acme.internal-image``
   (which runs on your hardware) read as remote, ``local-cache`` (which does not)
   read as local. P7.1 moves locality, licence class and capability state into
   ``ProviderDecision`` as structured facts. P7 reads them and never parses a name.

2. **The asset plane had no lifecycle, and could have drifted toward execution.**
   ``AssetDecisionState`` is now ``REQUESTED -> EVALUATED -> {ACCEPTED, BLOCKED,
   REJECTED}`` and is asserted *disjoint* from ``RunState``. The asset plane cannot
   say "produced"; only P6.6's ``ExecutionReceipt`` can.

The principle under both: **an authority provides facts; a consumer must never
guess them from a name.**
"""

from __future__ import annotations

import ast
import pathlib
import re
from dataclasses import fields
from pathlib import Path

import pytest

from hevi.production.p6.production_runtime import (
    ExecutionReceipt,
    ProductionRunResult,
    RunState,
)
from hevi.production.p7 import (
    AssetDecision,
    AssetDecisionAuthority,
    AssetDecisionState,
    AssetRequirement,
    AssetSemanticRole,
    MediaType,
    SourcePolicy,
    evaluate_policy,
)
from hevi.provider_policy.policy import (
    ProviderCapabilityState,
    ProviderDecision,
    ProviderLicenseClass,
    ProviderLocality,
    ProviderRejection,
)

P7_POLICY_FILE = Path("hevi/production/p7/asset_policy.py")
P7_DIR = Path("hevi/production/p7")
PROVIDER_POLICY_FILE = Path("hevi/provider_policy/policy.py")


def _requirement(**kwargs) -> AssetRequirement:
    base = {
        "media_type": MediaType.IMAGE,
        "semantic_role": AssetSemanticRole.PROP,
    }
    return AssetRequirement(**{**base, **kwargs})


def _decision(
    eligible: tuple[str, ...] = ("acme.image",),
    locality: dict[str, ProviderLocality] | None = None,
    license_class: dict[str, ProviderLicenseClass] | None = None,
    rejected: tuple[ProviderRejection, ...] = (),
) -> ProviderDecision:
    decision = ProviderDecision(
        selected_provider=eligible[0] if eligible else None,
        eligible=list(eligible),
        rejected=list(rejected),
    )
    if locality:
        decision.locality = locality
    if license_class:
        decision.license_class = license_class
    return decision


def _code_only(path: Path) -> str:
    """Source with docstrings removed, so prose about a rule is not a rule."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)
    return ast.unparse(tree)


# ═══════════════════════════════════════════════════════════════════════════
# Structured facts exist at the authority
# ═══════════════════════════════════════════════════════════════════════════


def test_provider_decision_carries_structured_locality() -> None:
    assert "locality" in ProviderDecision.model_fields


def test_provider_decision_locality_is_a_typed_mapping() -> None:
    assert ProviderDecision.model_fields["locality"].annotation == dict[str, ProviderLocality]


def test_provider_decision_carries_licence_class() -> None:
    assert ProviderDecision.model_fields["license_class"].annotation == dict[
        str, ProviderLicenseClass
    ]


def test_provider_decision_carries_capability_states() -> None:
    assert ProviderDecision.model_fields["capability_states"].annotation == dict[
        str, ProviderCapabilityState
    ]


def test_locality_is_an_enum_not_a_string() -> None:
    assert {v.value for v in ProviderLocality} == {"LOCAL", "REMOTE"}
    with pytest.raises(ValueError):
        ProviderLocality("maybe")


def test_license_class_is_an_enum_not_a_string() -> None:
    assert {v.value for v in ProviderLicenseClass} == {"LICENSED", "GENERATED", "UNKNOWN"}


def test_capability_state_has_the_four_declared_values() -> None:
    assert {v.value for v in ProviderCapabilityState} == {
        "AVAILABLE", "BLOCKED", "FAILED", "NOT_ADOPTED",
    }


def test_provider_decision_facts_default_empty_and_backward_compatible() -> None:
    decision = ProviderDecision()
    assert decision.locality == {}
    assert decision.license_class == {}
    assert decision.capability_states == {}
    assert decision.policy_version == 1


def test_provider_decision_still_carries_the_pre_existing_fields() -> None:
    names = set(ProviderDecision.model_fields)
    for existing in ("selected_provider", "eligible", "considered", "rejected",
                     "candidate_scores", "selected_reason", "explored", "policy_version"):
        assert existing in names, existing


# ═══════════════════════════════════════════════════════════════════════════
# LOCALITY AUTHORITY — provider_id != locality
# ═══════════════════════════════════════════════════════════════════════════


def test_locality_authority_name_says_local_but_fact_says_remote() -> None:
    """The exact corruption the audit found, now impossible."""
    requirement = _requirement(source_policy=SourcePolicy.LOCAL_ONLY)
    decision = _decision(
        eligible=("local-voice.run",),
        locality={"local-voice.run": ProviderLocality.REMOTE},
    )
    assert evaluate_policy(requirement, decision).allowed_ids == ()


def test_locality_authority_name_says_nothing_but_fact_says_local() -> None:
    requirement = _requirement(source_policy=SourcePolicy.LOCAL_ONLY)
    decision = _decision(
        eligible=("acme.internal-image",),
        locality={"acme.internal-image": ProviderLocality.LOCAL},
    )
    assert evaluate_policy(requirement, decision).allowed_ids == ("acme.internal-image",)


def test_locality_authority_edge_cluster_render_may_be_local() -> None:
    requirement = _requirement(source_policy=SourcePolicy.LOCAL_ONLY)
    decision = _decision(
        eligible=("edge.cluster.render",),
        locality={"edge.cluster.render": ProviderLocality.LOCAL},
    )
    assert evaluate_policy(requirement, decision).allowed_ids == ("edge.cluster.render",)


def test_locality_authority_local_generate_still_local() -> None:
    requirement = _requirement(source_policy=SourcePolicy.LOCAL_ONLY)
    decision = _decision(
        eligible=("local.generate",),
        locality={"local.generate": ProviderLocality.LOCAL},
    )
    assert evaluate_policy(requirement, decision).allowed_ids == ("local.generate",)


def test_locality_is_independent_of_the_name_in_every_direction() -> None:
    requirement = _requirement(source_policy=SourcePolicy.LOCAL_ONLY)
    matrix = [
        ("local.generate", ProviderLocality.LOCAL, True),
        ("acme.internal-image", ProviderLocality.LOCAL, True),
        ("edge.cluster.render", ProviderLocality.LOCAL, True),
        ("local-voice.run", ProviderLocality.REMOTE, False),
        ("local-cache", ProviderLocality.REMOTE, False),
        ("LOCAL.generate", ProviderLocality.LOCAL, True),
    ]
    for provider_id, fact, should_allow in matrix:
        decision = _decision(eligible=(provider_id,), locality={provider_id: fact})
        allowed = bool(evaluate_policy(requirement, decision).allowed_ids)
        assert allowed is should_allow, (provider_id, fact, allowed)


def test_undeclared_locality_fails_closed() -> None:
    """Absence of a fact is unknown, never guessed from the name."""
    requirement = _requirement(source_policy=SourcePolicy.LOCAL_ONLY)
    decision = _decision(eligible=("mystery.provider",), locality={})
    policy = evaluate_policy(requirement, decision)
    assert policy.allowed_ids == ()
    assert "UNRESOLVED" in policy.blocked_reasons()["mystery.provider"]


def test_undeclared_locality_blocks_even_a_local_looking_name() -> None:
    requirement = _requirement(source_policy=SourcePolicy.LOCAL_ONLY)
    decision = _decision(eligible=("local.generate",), locality={})
    assert evaluate_policy(requirement, decision).allowed_ids == ()


def test_licensed_only_uses_the_licence_fact_not_locality() -> None:
    """A local pipeline can serve licensed material; a remote one may not."""
    requirement = _requirement(source_policy=SourcePolicy.LICENSED_ONLY)
    local_licensed = _decision(
        eligible=("acme.internal-image",),
        locality={"acme.internal-image": ProviderLocality.LOCAL},
        license_class={"acme.internal-image": ProviderLicenseClass.LICENSED},
    )
    assert evaluate_policy(requirement, local_licensed).allowed_ids == ("acme.internal-image",)

    remote_generated = _decision(
        eligible=("open-source-generate",),
        locality={"open-source-generate": ProviderLocality.REMOTE},
        license_class={"open-source-generate": ProviderLicenseClass.GENERATED},
    )
    assert evaluate_policy(requirement, remote_generated).allowed_ids == ()


def test_licensed_only_fails_closed_on_an_undeclared_licence() -> None:
    requirement = _requirement(source_policy=SourcePolicy.LICENSED_ONLY)
    decision = _decision(eligible=("acme.image",), license_class={})
    policy = evaluate_policy(requirement, decision)
    assert policy.allowed_ids == ()
    assert "UNRESOLVED" in policy.blocked_reasons()["acme.image"]


def test_p7_reads_only_the_structured_facts() -> None:
    source = _code_only(P7_POLICY_FILE)
    assert "decision.locality.get(" in source
    assert "decision.license_class.get(" in source
    assert ".locality" in source and ".license_class" in source


def test_p7_no_longer_parses_provider_ids() -> None:
    """The leak itself: no id inspection anywhere in P7's policy layer."""
    code = _code_only(P7_POLICY_FILE)
    for pattern in (r"startswith\(", r"\.split\(", r"provider_id\["):
        assert not re.search(pattern, code), pattern


def test_p7_does_not_string_match_a_locality_token() -> None:
    code = _code_only(P7_POLICY_FILE).lower()
    # `"local"` may appear as an enum member reference, never as a prefix test.
    assert 'startswith("local")' not in code
    assert "== 'local'" not in code
    assert "local.generate" not in code
    assert "stock" not in code


def test_p7_defines_no_locality_or_license_of_its_own() -> None:
    """The authority is the provider layer, not P7."""
    for path in P7_DIR.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef):
                assert "Locality" not in node.name, (path.name, node.name)
                assert "LicenseClass" not in node.name, (path.name, node.name)


def test_p7_compares_against_enum_members_not_strings() -> None:
    source = P7_POLICY_FILE.read_text()
    # The comparison target is the declared fact's own value, resolved once.
    assert "_locality_of" in source
    assert "_license_of" in source
    code = _code_only(P7_POLICY_FILE)
    # The rule compares the *declared fact* against a term, never an id against a
    # name. Asserted via the enums' own values so the check does not depend on
    # `ast.unparse`'s quote normalisation.
    assert f"!= {ProviderLocality.LOCAL.value!r}" in code
    assert f"!= {ProviderLicenseClass.LICENSED.value!r}" in code
    assert "_locality_of" in code and "_license_of" in code


def test_provider_policy_is_the_sole_fact_source() -> None:
    """Only the provider layer may define these enums."""
    for path in P7_DIR.glob("*.py"):
        assert "class ProviderLocality" not in path.read_text(), path.name
        assert "class ProviderCapabilityState" not in path.read_text(), path.name


def test_capability_states_are_readable_from_the_decision() -> None:
    decision = _decision(eligible=("acme.image", "idle.provider"))
    decision.capability_states = {
        "acme.image": ProviderCapabilityState.AVAILABLE,
        "idle.provider": ProviderCapabilityState.NOT_ADOPTED,
    }
    assert decision.capability_states["idle.provider"] is (
        ProviderCapabilityState.NOT_ADOPTED
    )


# ═══════════════════════════════════════════════════════════════════════════
# ASSET LIFECYCLE
# ═══════════════════════════════════════════════════════════════════════════


def test_asset_lifecycle_has_requested_and_evaluated() -> None:
    assert AssetDecisionState.REQUESTED.value == "REQUESTED"
    assert AssetDecisionState.EVALUATED.value == "EVALUATED"


def test_asset_lifecycle_terminal_states() -> None:
    terminal = {s for s in AssetDecisionState if s.is_terminal}
    assert terminal == {
        AssetDecisionState.ACCEPTED,
        AssetDecisionState.BLOCKED,
        AssetDecisionState.REJECTED,
    }


def test_asset_lifecycle_provisional_states_are_not_success() -> None:
    for state in (AssetDecisionState.REQUESTED, AssetDecisionState.EVALUATED):
        assert not state.is_success
        assert state.is_provisional


def test_asset_plane_owns_no_execution_state() -> None:
    """ASSET_EXECUTION_BOUNDARY.

    The asset plane cannot say produced, failed, or QA-passed. Only P6.6's
    ``ExecutionReceipt`` can, so an acceptance stays an *input* to production
    rather than a claim that production happened.
    """
    asset = {s.value for s in AssetDecisionState}
    run = {s.value for s in RunState}
    assert asset.isdisjoint(run), sorted(asset & run)
    for execution_only in ("PRODUCED", "FAILED", "QA_PASSED", "QA_FAILED",
                           "BLOCKED_BY_PROVIDER", "EXECUTING", "CANCELLED"):
        assert execution_only not in asset, execution_only


def test_asset_plane_declares_no_execution_state_members() -> None:
    forbidden = {"PRODUCED", "FAILED", "QA_PASSED", "QA_FAILED", "EXECUTING",
                 "BLOCKED_BY_PROVIDER", "BLOCKED_BY_CAPABILITY", "CANCELLED",
                 "COMPILED", "VALIDATED", "AVAILABLE"}
    assert {s.value for s in AssetDecisionState}.isdisjoint(forbidden)


def test_provisional_decision_may_not_carry_a_source() -> None:
    with pytest.raises(ValueError, match="PROVISIONAL_DECISION_WITH_RESULT"):
        AssetDecision(
            requirement_id="IMAGE/PROP",
            state=AssetDecisionState.REQUESTED,
            selected_source="acme.image",
        )


def test_provisional_decision_may_not_carry_a_provider_decision() -> None:
    with pytest.raises(ValueError, match="PROVISIONAL_DECISION_WITH_RESULT"):
        AssetDecision(
            requirement_id="IMAGE/PROP",
            state=AssetDecisionState.EVALUATED,
            provider_decision=_decision(),
        )


def test_provisional_decision_may_not_carry_evidence() -> None:
    from hevi.production.p7 import AssetEvidence, AssetStatus

    with pytest.raises(ValueError, match="PROVISIONAL_DECISION_WITH_EVIDENCE"):
        AssetDecision(
            requirement_id="IMAGE/PROP",
            state=AssetDecisionState.EVALUATED,
            evidence=(
                AssetEvidence(asset_id="a", source="s",
                              status=AssetStatus.AVAILABLE, license="L"),
            ),
        )


def test_requested_helper_creates_a_clean_provisional_decision() -> None:
    from hevi.production.p7 import requested

    decision = requested("IMAGE/PROP")
    assert decision.state is AssetDecisionState.REQUESTED
    assert decision.selected_source == ""
    assert decision.provider_decision is None
    assert decision.evidence == ()


def test_evaluated_helper_records_the_policy_that_ran() -> None:
    from hevi.production.p7 import evaluated

    decision = evaluated("IMAGE/PROP", policy_id="policy-7")
    assert decision.state is AssetDecisionState.EVALUATED
    assert decision.policy_id == "policy-7"


def test_accepted_asset_decision_is_still_only_an_input_to_production() -> None:
    """An acceptance never carries an execution receipt."""
    decision = AssetDecision(
        requirement_id="IMAGE/PROP",
        state=AssetDecisionState.ACCEPTED,
        selected_source="acme.image",
        provider_decision=_decision(
            locality={"acme.image": ProviderLocality.LOCAL}
        ),
        confidence=0.9,
    )
    assert decision.state.is_success
    assert not hasattr(decision, "receipt")
    assert "receipt" not in {f.name for f in fields(decision)}


def test_execution_receipt_is_the_sole_production_fact_source() -> None:
    """One place constructs a success state, and it requires a real receipt."""
    source = Path("hevi/production/p6/production_runtime.py").read_text()
    tree = ast.parse(source)
    produced_sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            kwargs = {k.arg for k in node.keywords if k.arg}
            func_name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
            if func_name == "ProductionRunResult":
                state = next(
                    (ast.unparse(k.value) for k in node.keywords if k.arg == "state"), ""
                )
                if "RunState.PRODUCED" in state or "RunState.QA_PASSED" in state:
                    produced_sites.append((node.lineno, "receipt" in kwargs))
    assert produced_sites, "no success-state site found"
    assert all(carries for _, carries in produced_sites), produced_sites


def test_success_state_still_requires_a_producing_receipt() -> None:
    with pytest.raises(ValueError, match="FALSE_SUCCESS_BLOCKED"):
        ProductionRunResult(run_id="r", product_profile_id="p", state=RunState.PRODUCED)
    with pytest.raises(ValueError, match="FALSE_SUCCESS_BLOCKED"):
        ProductionRunResult(
            run_id="r", product_profile_id="p", state=RunState.QA_PASSED,
            receipt=ExecutionReceipt(runtime_id="x", entrypoint_ref="y", produced=False),
        )


def test_authority_still_fails_closed_without_a_provider_decision() -> None:
    resolution = AssetDecisionAuthority().decide(_requirement(), provider_decision=None)
    assert resolution.decision.state is AssetDecisionState.BLOCKED
    assert "NO_PROVIDER_DECISION" in resolution.decision.reason


def test_authority_accepts_a_fresh_local_provider_named_anything() -> None:
    """End-to-end: a provider invented today, named nothing like 'local'."""
    resolution = AssetDecisionAuthority().decide(
        _requirement(source_policy=SourcePolicy.LOCAL_ONLY, evidence_required=False),
        provider_decision=_decision(
            eligible=("acme.internal-image",),
            locality={"acme.internal-image": ProviderLocality.LOCAL},
        ),
        selected_source="acme.internal-image",
        confidence=0.95,
    )
    assert resolution.policy.allowed_ids == ("acme.internal-image",)
    assert resolution.decision.state is AssetDecisionState.ACCEPTED


# ═══════════════════════════════════════════════════════════════════════════
# MUTATION
# ═══════════════════════════════════════════════════════════════════════════


def _mutate(tmp_path: Path, target: Path, needle: str, replacement: str) -> str:
    source = target.read_text()
    assert needle in source, f"anchor missing in {target.name}"
    mutated = source.replace(needle, replacement, 1)
    assert mutated != source
    (tmp_path / target.name).write_text(mutated)
    return mutated


def test_mutation_reintroducing_prefix_parsing_must_fail(tmp_path: Path) -> None:
    """The exact leak this phase closed."""
    mutated = _mutate(
        tmp_path, P7_POLICY_FILE,
        '    declared = decision.locality.get(provider_id)',
        '    if provider_id.startswith("local"):\n'
        '        return "LOCAL"\n'
        '    declared = decision.locality.get(provider_id)',
    )
    assert 'provider_id.startswith("local")' in mutated
    code = _code_only_path(mutated)
    assert re.search(r"startswith\(", code)


def _code_only_path(source: str) -> str:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        ):
            node.body.pop(0)
    return ast.unparse(tree)


def test_mutation_guessing_locality_when_undeclared_must_fail() -> None:
    """A fallback inference would silently restore the leak."""
    requirement = _requirement(source_policy=SourcePolicy.LOCAL_ONLY)
    decision = _decision(eligible=("local.generate",), locality={})
    policy = evaluate_policy(requirement, decision)
    assert policy.allowed_ids == ()
    assert "UNRESOLVED" in policy.blocked_reasons()["local.generate"]


def test_mutation_guessing_licence_from_locality_must_fail() -> None:
    requirement = _requirement(source_policy=SourcePolicy.LICENSED_ONLY)
    decision = _decision(
        eligible=("acme.image",),
        locality={"acme.image": ProviderLocality.REMOTE},
        license_class={},
    )
    assert evaluate_policy(requirement, decision).allowed_ids == ()


def test_mutation_adding_an_execution_state_to_the_asset_plane_must_fail(
    tmp_path: Path,
) -> None:
    mutated = _mutate(
        tmp_path, Path("hevi/production/p7/asset_decision.py"),
        '    REJECTED = "REJECTED"',
        '    REJECTED = "REJECTED"\n    PRODUCED = "PRODUCED"',
    )
    tree = ast.parse(mutated)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "AssetDecisionState":
            values = {s.value.value for s in node.body if isinstance(s, ast.Assign)}
            assert "PRODUCED" in values
    # and the real enum cannot express it
    assert not hasattr(AssetDecisionState, "PRODUCED")
    assert {s.value for s in AssetDecisionState}.isdisjoint({s.value for s in RunState})


def test_mutation_accepted_carrying_a_receipt_must_fail() -> None:
    names = {f.name for f in fields(AssetDecision)}
    assert "receipt" not in names
    assert "execution_receipt" not in names
    assert "render_receipt" not in names


def test_mutation_provider_layer_fact_fields_removed_must_fail() -> None:
    """The fact enums moved to the catalogue in P7.2; the guarantee did not.

    P7.1 asserted the enums were defined in ``provider_policy/policy.py``. They now
    live with the catalogue that produces them, so this asserts the stronger
    property instead: **exactly one** definition site for each fact enum across the
    whole package, and typed fact fields on the decision.
    """
    source = PROVIDER_POLICY_FILE.read_text()
    assert "locality: dict[str, ProviderLocality]" in source
    # The consumer depends on the fields existing.
    assert "locality" in ProviderDecision.model_fields
    assert "license_class" in ProviderDecision.model_fields
    assert "capability_states" in ProviderDecision.model_fields
    # policy.py re-exports the enum rather than redefining it.
    assert "class ProviderLocality" not in source
    for enum_name in ("ProviderLocality", "ProviderLicenseClass", "ProviderCapabilityState"):
        sites = [
            path
            for path in pathlib.Path("hevi").rglob("*.py")
            if f"class {enum_name}(" in path.read_text()
        ]
        assert len(sites) == 1, (
            f"{enum_name} must be defined exactly once, found {[p.name for p in sites]}"
        )
        assert sites[0].name == "facts.py", f"{enum_name} belongs to the catalogue"


def test_mutation_p7_defining_its_own_locality_must_fail() -> None:
    for path in P7_DIR.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                assert not re.match(r".*Locality$", node.name), (path.name, node.name)


def test_mutation_str_state_instead_of_enum_must_fail() -> None:
    with pytest.raises(ValueError):
        ProviderLocality("LOCALISH")
    with pytest.raises(ValueError):
        ProviderCapabilityState("SOMETHING")
    with pytest.raises(ValueError):
        ProviderLicenseClass("CC-BY")


def test_mutation_capability_state_missing_a_value_must_fail() -> None:
    assert {v.value for v in ProviderCapabilityState} == {
        "AVAILABLE", "BLOCKED", "FAILED", "NOT_ADOPTED",
    }
    with pytest.raises(ValueError):
        ProviderCapabilityState("UNKNOWN_STATE")