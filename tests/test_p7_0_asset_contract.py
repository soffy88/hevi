"""HEVI P7.0 — Asset decision plane: contract, requirement, decision, policy.

The load-bearing claim is negative: P7.0 adds a *decision plane* and **no asset
authority**. ``hevi.sourcing`` owns acquisition, validation, selection and
persistence; ``hevi.provider_policy`` owns provider authority; P7 owns only the
vocabulary that lets a compiled intent state what it needs, and the record of how
those needs resolved.

Two things make this phase's guards structural rather than textual: these modules'
docstrings deliberately *name* the things P7 must not create, and ``hevi/sourcing``
now legitimately gains exactly one file (``p7_adapter.py``). Both would trip a
substring scan, so the guards parse the AST.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import fields, is_dataclass
from pathlib import Path

import pytest

from hevi.production.p6.product_compiler import ProductCompiler
from hevi.production.p6.production_runtime import Capability, requirements_for
from hevi.production.p6.schema import ProductType
from hevi.production.p7 import (
    SOURCING_ASSET_TYPES,
    Allowance,
    AssetBindingError,
    AssetDecision,
    AssetDecisionAuthority,
    AssetDecisionState,
    AssetEvidence,
    AssetPolicyDecision,
    AssetReference,
    AssetRequirement,
    AssetResolution,
    AssetSemanticRole,
    AssetStatus,
    MediaType,
    ProviderAllowance,
    RequirementRule,
    SourcePolicy,
    binding_summary,
    blocked,
    evaluate_policy,
    requirements_from_capabilities,
    requirements_from_intent,
)
from hevi.production.p7.asset_binding import CAPABILITY_RULES
from hevi.production.p7.asset_requirement import (
    KNOWN_CONSTRAINTS,
    QUALITY_FLOOR_MAX,
    QUALITY_FLOOR_MIN,
)
from hevi.provider_policy.policy import (
    ProviderDecision,
    ProviderLicenseClass,
    ProviderLocality,
    ProviderRejection,
)
from hevi.sourcing.p7_adapter import (
    UNSERVABLE_MEDIA_TYPES,
    to_media_request,
    to_stock_request,
)

P7_DIR = Path("hevi/production/p7")
P7_FILES = tuple(sorted(P7_DIR.glob("*.py")))
ADAPTER_FILE = Path("hevi/sourcing/p7_adapter.py")

#: Authority names P7 must not introduce. `AssetRepository` is absent deliberately:
#: `hevi.sourcing` owns it and is permitted.
FORBIDDEN_AUTHORITY_NAMES = (
    "AssetManager", "AssetStore", "NewAssetRepository", "AssetRegistry",
    "AssetProvider", "AssetValidator", "ProviderRegistry", "RenderReceipt",
    "AssetSelectionService",
)
FORBIDDEN_ACQUISITION_METHODS = (
    "download", "download_asset", "fetch", "fetch_asset", "render_asset",
    "open_stream", "read_bytes", "write_file", "save", "acquire",
)


def _library():
    from hevi.production.p5_3.library import RecipeLibrary
    from hevi.production.p5_3.recipes import load_all_recipes

    library = RecipeLibrary()
    for recipe in load_all_recipes():
        library.register(recipe)
    return library


def _intent(product: str = "P03_DOCUMENTARY"):
    return ProductCompiler().compile(product, recipe_library=_library())


def _requirement(**kwargs) -> AssetRequirement:
    base = {
        "media_type": MediaType.IMAGE,
        "semantic_role": AssetSemanticRole.CHARACTER,
    }
    return AssetRequirement(**{**base, **kwargs})


def _provider_decision(**kwargs) -> ProviderDecision:
    """A decision carrying the structured facts P7.1 requires.

    Before P7.1 these tests leaned on ``startswith("local")``. P7.1 deleted that
    inference, so a decision silent about locality now fails closed under
    ``LOCAL_ONLY``. Callers must declare the fact — which is the whole point.
    """
    base = {
        "selected_provider": "pexels.stock",
        "eligible": ["pexels.stock", "local.generate"],
        "rejected": [ProviderRejection(provider_id="fal.image", reasons=["no credential"])],
        "selected_reason": "stock is licensed and available",
    }
    decision = ProviderDecision(**{**base, **kwargs})
    decision.locality = {
        "pexels.stock": ProviderLocality.REMOTE,
        "local.generate": ProviderLocality.LOCAL,
    }
    decision.license_class = {
        "pexels.stock": ProviderLicenseClass.LICENSED,
        "local.generate": ProviderLicenseClass.GENERATED,
    }
    return decision


def _evidence(asset_id: str = "asset_001", **kwargs) -> AssetEvidence:
    base = {
        "asset_id": asset_id,
        "source": "pexels.stock",
        "status": AssetStatus.AVAILABLE,
        "license": "CC-BY-4.0",
        "validation": "AssetVerdict(valid=True)",
    }
    return AssetEvidence(**{**base, **kwargs})


# ═══════════════════════════════════════════════════════════════════════════
# ARCHITECTURE
# ═══════════════════════════════════════════════════════════════════════════


def test_architecture_p7_module_layout() -> None:
    for name in ("__init__", "asset_contract", "asset_requirement",
                 "asset_decision", "asset_policy", "asset_intelligence", "evidence"):
        assert (P7_DIR / f"{name}.py").exists(), name


def test_architecture_defines_no_second_asset_authority() -> None:
    for path in P7_FILES:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef):
                assert node.name not in FORBIDDEN_AUTHORITY_NAMES, (path.name, node.name)


def test_architecture_no_forbidden_authority_under_alias() -> None:
    lowered = {n.lower() for n in FORBIDDEN_AUTHORITY_NAMES}
    for path in P7_FILES:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef):
                assert node.name.lower() not in lowered, (path.name, node.name)


def test_architecture_defines_the_decision_authority_not_a_store() -> None:
    assert AssetDecisionAuthority.authority_id == "p7_0_asset_decision"
    assert not hasattr(AssetDecisionAuthority, "register")
    assert not hasattr(AssetDecisionAuthority, "get")
    assert not hasattr(AssetDecisionAuthority, "store")


def test_architecture_decision_authority_is_stateless() -> None:
    authority = AssetDecisionAuthority()
    assert not [n for n in vars(authority) if not n.startswith("_")]


def test_architecture_no_model_carries_an_acquisition_method() -> None:
    forbidden = set(FORBIDDEN_ACQUISITION_METHODS)
    for model in (AssetReference, AssetEvidence, AssetRequirement, AssetDecision,
                  AssetPolicyDecision, AssetResolution):
        assert is_dataclass(model)
        assert not (set(dir(model)) & forbidden), model.__name__


def test_architecture_asset_reference_has_no_local_path() -> None:
    names = {f.name for f in fields(AssetReference)}
    assert "local_path" not in names
    assert "bytes" not in names
    assert "uri" in names


def test_architecture_p7_defines_no_shot_motion_or_receipt() -> None:
    for path in P7_FILES:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef):
                assert node.name not in {
                    "ShotPlan", "MotionPlan", "ExecutionReceipt", "AudioLock",
                    "AudioIntent", "AssetVerdict",
                }, (path.name, node.name)


def test_architecture_p7_imports_no_provider_registry() -> None:
    for path in P7_FILES:
        source = path.read_text()
        assert "class ProviderRegistry" not in source
        # The existing provider authority is consumed as a type, never re-exported.
        assert "from hevi.providers.registry import" not in source


def test_architecture_sourcing_gains_exactly_the_adapter() -> None:
    """P7 adds one file inside sourcing, and rewrites nothing else."""
    import subprocess

    out = subprocess.run(
        ["git", "status", "--short", "hevi/sourcing/"],
        capture_output=True, text=True, cwd=Path.cwd(),
    ).stdout.strip().splitlines()
    paths = {line.split()[-1] for line in out}
    assert paths <= {"hevi/sourcing/p7_adapter.py"}, paths
    assert ADAPTER_FILE.exists()


def test_architecture_adapter_imports_no_p7_at_runtime() -> None:
    """The adapter reads a requirement structurally, so sourcing works without P7."""
    source = ADAPTER_FILE.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith("hevi.production.p7"), node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("hevi.production.p7"), alias.name


def test_architecture_no_product_label_in_p7_executable_flow() -> None:
    label = re.compile(r"P0[1-9]_[A-Z_]+|P10_[A-Z_]+")
    for path in P7_FILES:
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.If, ast.IfExp, ast.Match)):
                assert not label.search(ast.unparse(node)), path.name


# ═══════════════════════════════════════════════════════════════════════════
# VOCABULARY SEPARATION
# ═══════════════════════════════════════════════════════════════════════════


def test_media_type_not_used_as_semantic_role() -> None:
    """`IMAGE` is not `CHARACTER`. The two axes are disjoint, by construction.

    Collapsing them is what made P6.5.2's compatibility matrix a diagonal, so the
    separation is asserted structurally rather than by convention.
    """
    media = {m.value for m in MediaType}
    roles = {r.value for r in AssetSemanticRole}
    assert media.isdisjoint(roles)
    assert not (media & roles)
    assert media == {"IMAGE", "VIDEO", "AUDIO", "MODEL3D", "TEXTURE", "DOCUMENT"}


def test_media_type_vocabulary_is_the_six_specified() -> None:
    assert len(tuple(MediaType)) == 6


def test_media_type_is_closed() -> None:
    with pytest.raises(ValueError):
        MediaType("HOLOGRAM")


def test_semantic_role_vocabulary_matches_sourcing_exactly() -> None:
    assert {r.value for r in AssetSemanticRole} == {
        v.upper() for v in SOURCING_ASSET_TYPES
    }


def test_semantic_role_is_closed() -> None:
    with pytest.raises(ValueError):
        AssetSemanticRole("HERO")


def test_semantic_role_round_trips_to_the_owners_spelling() -> None:
    for role in AssetSemanticRole:
        assert role.sourcing_key() in SOURCING_ASSET_TYPES
        assert AssetSemanticRole.from_sourcing(role.sourcing_key()) is role


def test_media_type_is_never_a_semantic_role() -> None:
    """The required separation test, stated the other way round."""
    for media in MediaType:
        with pytest.raises(ValueError):
            AssetSemanticRole(media.value)
    for role in AssetSemanticRole:
        with pytest.raises(ValueError):
            MediaType(role.value)


def test_a_requirement_names_both_axes_independently() -> None:
    cases = [
        (MediaType.IMAGE, AssetSemanticRole.CHARACTER),
        (MediaType.VIDEO, AssetSemanticRole.SCENE),
        (MediaType.AUDIO, AssetSemanticRole.VOICE),
        (MediaType.TEXTURE, AssetSemanticRole.PROP),
        (MediaType.DOCUMENT, AssetSemanticRole.PROP),
    ]
    for media, role in cases:
        requirement = AssetRequirement(media_type=media, semantic_role=role)
        assert requirement.media_type is media
        assert requirement.semantic_role is role


def test_requirement_id_encodes_both_axes() -> None:
    assert _requirement().requirement_id == "IMAGE/CHARACTER"


def test_every_capability_has_a_binding_rule() -> None:
    keys = {r.key for r in CAPABILITY_RULES}
    for capability in Capability:
        assert f"cap:{capability.value}" in keys, capability.value


def test_rule_keys_are_unique() -> None:
    keys = [r.key for r in CAPABILITY_RULES]
    assert len(keys) == len(set(keys))


def test_rules_declare_no_product_identity() -> None:
    for rule in CAPABILITY_RULES:
        assert not re.search(r"P0[1-9]_|P10_", rule.key)


# ═══════════════════════════════════════════════════════════════════════════
# REQUIREMENT
# ═══════════════════════════════════════════════════════════════════════════


def test_requirement_is_immutable() -> None:
    with pytest.raises((AttributeError, TypeError)):
        _requirement().quantity = 5  # type: ignore[misc]


def test_requirement_defaults_are_conservative() -> None:
    requirement = _requirement()
    assert requirement.quantity == 1
    assert requirement.evidence_required is True
    assert requirement.source_policy is SourcePolicy.PREFERRED_LICENSED


def test_requirement_rejects_zero_quantity() -> None:
    with pytest.raises(ValueError, match="INVALID_ASSET_QUANTITY"):
        _requirement(quantity=0)


def test_requirement_rejects_unknown_media_type() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_MEDIA_TYPE"):
        _requirement(media_type="GIF")


def test_requirement_rejects_unknown_semantic_role() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_ASSET_SEMANTIC_ROLE"):
        _requirement(semantic_role="HERO")


def test_requirement_quality_floor_uses_the_provider_policy_scale() -> None:
    assert (QUALITY_FLOOR_MIN, QUALITY_FLOOR_MAX) == (0, 10)
    for bad in (-1, 11):
        with pytest.raises(ValueError, match="INVALID_QUALITY_FLOOR"):
            _requirement(quality_floor=bad)


def test_requirement_quality_floor_scale_matches_provider_policy() -> None:
    from hevi.provider_policy.policy import ProviderPolicy

    policy_floor = ProviderPolicy().quality_floor
    assert QUALITY_FLOOR_MAX == 10
    assert QUALITY_FLOOR_MIN == 0
    assert QUALITY_FLOOR_MIN <= policy_floor <= QUALITY_FLOOR_MAX


def test_requirement_rejects_unknown_source_policy() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_SOURCE_POLICY"):
        _requirement(source_policy="ANYTHING")


def test_requirement_rejects_empty_constraint_key() -> None:
    with pytest.raises(ValueError, match="EMPTY_ASSET_CONSTRAINT_KEY"):
        _requirement(constraints=(("", "x"),))


def test_requirement_reports_unknown_constraints() -> None:
    requirement = _requirement(constraints=(("period", "1930s"), ("mood", "grim")))
    assert requirement.unknown_constraints() == ("mood",)
    assert "period" in KNOWN_CONSTRAINTS


def test_requirement_query_is_declared_not_invented() -> None:
    assert _requirement().query() == ""
    assert _requirement(constraints=(("query", "Napoleon portrait"),)).query() == (
        "Napoleon portrait"
    )


def test_requirement_hash_is_stable() -> None:
    assert _requirement().content_hash() == _requirement().content_hash()


def test_requirement_hash_changes_with_quality_floor() -> None:
    assert _requirement(quality_floor=5).content_hash() != _requirement(
        quality_floor=9
    ).content_hash()


def test_requirement_to_dict_is_complete() -> None:
    payload = _requirement().to_dict()
    for key in ("requirement_id", "media_type", "semantic_role", "quantity",
                "quality_floor", "source_policy", "constraints", "evidence_required"):
        assert key in payload


# ═══════════════════════════════════════════════════════════════════════════
# EVIDENCE
# ═══════════════════════════════════════════════════════════════════════════


def test_evidence_requires_id_and_source() -> None:
    with pytest.raises(ValueError, match="ASSET_EVIDENCE_WITHOUT_ID"):
        AssetEvidence(asset_id="", source="s")
    with pytest.raises(ValueError, match="ASSET_EVIDENCE_WITHOUT_SOURCE"):
        AssetEvidence(asset_id="a", source="")


def test_evidence_rejects_unknown_status() -> None:
    with pytest.raises(ValueError, match="UNKNOWN_ASSET_STATUS"):
        AssetEvidence(asset_id="a", source="s", status="maybe")  # type: ignore[arg-type]


def test_evidence_available_asset_must_declare_a_licence() -> None:
    with pytest.raises(ValueError, match="AVAILABLE_ASSET_WITHOUT_LICENSE"):
        AssetEvidence(asset_id="a", source="s", status=AssetStatus.AVAILABLE)


def test_evidence_blocked_asset_needs_no_licence() -> None:
    evidence = AssetEvidence(
        asset_id="mars_surface_001", source="nasa",
        status=AssetStatus.BLOCKED,
    )
    assert evidence.status is AssetStatus.BLOCKED


def test_evidence_carries_validation_summarised_not_reimplemented() -> None:
    evidence = _evidence(validation="AssetVerdict(valid=True)")
    assert "AssetVerdict" in evidence.validation
    assert not hasattr(AssetEvidence, "validate")


def test_evidence_fingerprint_excludes_retrieval_time() -> None:
    a = _evidence(retrieval_time="1999-01-01T00:00:00Z")
    b = _evidence(retrieval_time="2031-12-31T23:59:59Z")
    assert a.fingerprint() == b.fingerprint()


def test_evidence_fingerprint_changes_with_content() -> None:
    assert _evidence().fingerprint() != _evidence(license="CC0").fingerprint()


def test_evidence_to_dict_is_complete() -> None:
    payload = _evidence().to_dict()
    for key in ("asset_id", "source", "license", "validation", "retrieval_time",
                "content_hash", "status"):
        assert key in payload


# ═══════════════════════════════════════════════════════════════════════════


def test_decision_is_a_dataclass() -> None:
    assert is_dataclass(AssetDecision)


def test_decision_accepts_a_well_formed_acceptance() -> None:
    decision = AssetDecision(
        requirement_id="IMAGE/CHARACTER",
        state=AssetDecisionState.ACCEPTED,
        selected_source="pexels.stock",
        provider_decision=_provider_decision(),
        confidence=0.82,
        evidence=(_evidence(),),
    )
    assert decision.state.is_success
    assert decision.fingerprint()


def test_decision_requires_a_requirement_id() -> None:
    with pytest.raises(ValueError, match="ASSET_DECISION_WITHOUT_REQUIREMENT_ID"):
        AssetDecision(requirement_id="", state=AssetDecisionState.BLOCKED, reason="x")


def test_decision_accept_must_name_a_source() -> None:
    with pytest.raises(ValueError, match="ACCEPTED_WITHOUT_SOURCE"):
        AssetDecision(
            requirement_id="IMAGE/CHARACTER", state=AssetDecisionState.ACCEPTED,
            provider_decision=_provider_decision(),
        )


def test_decision_accept_must_carry_the_provider_decision() -> None:
    with pytest.raises(ValueError, match="ACCEPTED_WITHOUT_PROVIDER_DECISION"):
        AssetDecision(
            requirement_id="IMAGE/CHARACTER", state=AssetDecisionState.ACCEPTED,
            selected_source="pexels.stock",
        )


def test_decision_non_accept_must_not_name_a_source() -> None:
    with pytest.raises(ValueError, match="NON_ACCEPTED_WITH_SOURCE"):
        AssetDecision(
            requirement_id="IMAGE/CHARACTER", state=AssetDecisionState.BLOCKED,
            selected_source="pexels.stock", reason="blocked",
        )


def test_decision_non_accept_must_state_a_reason() -> None:
    with pytest.raises(ValueError, match="NON_ACCEPTED_WITHOUT_REASON"):
        AssetDecision(requirement_id="IMAGE/CHARACTER", state=AssetDecisionState.BLOCKED)


def test_decision_rejects_out_of_range_confidence() -> None:
    for bad in (-0.1, 1.1):
        with pytest.raises(ValueError, match="INVALID_CONFIDENCE"):
            AssetDecision(
                requirement_id="IMAGE/CHARACTER", state=AssetDecisionState.BLOCKED,
                reason="x", confidence=bad,
            )


def test_decision_blocked_helper_carries_the_requirement_id() -> None:
    decision = blocked("IMAGE/CHARACTER", "credential unavailable")
    assert decision.state is AssetDecisionState.BLOCKED
    assert "credential unavailable" in decision.reason


def test_decision_no_accepted_default_helper_exists() -> None:
    import hevi.production.p7.asset_decision as module

    assert not hasattr(module, "accepted_default")
    assert not hasattr(module, "default")


def test_decision_carries_provider_eligible_and_rejected_verbatim() -> None:
    decision = AssetDecision(
        requirement_id="IMAGE/CHARACTER", state=AssetDecisionState.ACCEPTED,
        selected_source="pexels.stock", provider_decision=_provider_decision(),
    )
    assert decision.authorised_providers() == ("pexels.stock", "local.generate")
    assert decision.blocked_providers() == (("fal.image", ("no credential",)),)


def test_decision_evidence_ids_are_sorted() -> None:
    decision = AssetDecision(
        requirement_id="IMAGE/CHARACTER", state=AssetDecisionState.ACCEPTED,
        selected_source="s", provider_decision=_provider_decision(),
        evidence=(_evidence("z_asset"), _evidence("a_asset")),
    )
    assert decision.evidence_ids() == ("a_asset", "z_asset")


def test_decision_evidence_policy_is_honoured() -> None:
    accepted = AssetDecision(
        requirement_id="IMAGE/CHARACTER", state=AssetDecisionState.ACCEPTED,
        selected_source="s", provider_decision=_provider_decision(),
    )
    assert accepted.satisfies_evidence_policy(True) is False
    assert accepted.satisfies_evidence_policy(False) is True


def test_decision_to_dict_serialises_the_provider_decision() -> None:
    payload = AssetDecision(
        requirement_id="IMAGE/CHARACTER", state=AssetDecisionState.ACCEPTED,
        selected_source="s", provider_decision=_provider_decision(),
    ).to_dict()
    assert payload["provider_decision"]["selected_provider"] == "pexels.stock"
    assert json.loads(json.dumps(payload))["state"] == "ACCEPTED"


# ═══════════════════════════════════════════════════════════════════════════
# POLICY
# ═══════════════════════════════════════════════════════════════════════════


def test_policy_returns_nothing_without_a_provider_decision() -> None:
    decision = evaluate_policy(_requirement(), None)
    assert decision.is_servable is False
    assert decision.allowed == ()


def test_policy_allows_every_eligible_provider_by_default() -> None:
    decision = evaluate_policy(_requirement(), _provider_decision())
    assert set(decision.allowed_ids) == {"pexels.stock", "local.generate"}
    assert decision.blocked_ids == ("fal.image",)


def test_policy_records_the_providers_own_rejection_reason() -> None:
    decision = evaluate_policy(_requirement(), _provider_decision())
    assert "no credential" in decision.blocked_reasons()["fal.image"]


def test_policy_local_only_blocks_non_local() -> None:
    requirement = _requirement(source_policy=SourcePolicy.LOCAL_ONLY)
    decision = evaluate_policy(requirement, _provider_decision())
    assert decision.allowed_ids == ("local.generate",)
    assert "pexels.stock" in decision.blocked_ids
    assert "LOCAL_ONLY" in decision.blocked_reasons()["pexels.stock"]


def test_policy_licensed_only_blocks_generated_material() -> None:
    """The licence *fact* blocks it, not the locality.

    P7.0 blocked local generation under LICENSED_ONLY by inferring the licence
    from the provider id. P7.1 replaced that with a declared licence class, so a
    local provider offering licensed material is now correctly allowed.
    """
    requirement = _requirement(source_policy=SourcePolicy.LICENSED_ONLY)
    decision = evaluate_policy(requirement, _provider_decision())
    assert decision.allowed_ids == ("pexels.stock",)
    assert "local.generate" in decision.blocked_ids
    assert "LICENSED_ONLY" in decision.blocked_reasons()["local.generate"]


def test_policy_licensed_only_allows_a_local_provider_with_licensed_material() -> None:
    requirement = _requirement(source_policy=SourcePolicy.LICENSED_ONLY)
    decision = _provider_decision()
    decision.license_class["local.generate"] = ProviderLicenseClass.LICENSED
    assert "local.generate" in evaluate_policy(requirement, decision).allowed_ids


def test_policy_any_available_permits_all_eligible() -> None:
    requirement = _requirement(source_policy=SourcePolicy.ANY_AVAILABLE)
    decision = evaluate_policy(requirement, _provider_decision())
    assert set(decision.allowed_ids) == {"pexels.stock", "local.generate"}
    assert decision.fallback


def test_policy_never_branches_on_a_provider_name() -> None:
    """A rule about *provenance* and *terms*, not about any vendor.

    Checked against code with docstrings stripped — the module's docstring names
    these vendors precisely to explain what it forbids.
    """
    code = _code_only(P7_DIR / "asset_policy.py").lower()
    # Word-bounded: `fallback` contains "fal" as a substring and is not a vendor.
    for vendor in ("fal", "pexels", "openai", "dashscope", "gemini", "nasa", "unsplash"):
        assert not re.search(rf"\b{re.escape(vendor)}\b", code), vendor


def test_policy_allowance_is_a_dataclass() -> None:
    assert is_dataclass(ProviderAllowance)
    assert ProviderAllowance("p", Allowance.ALLOWED).to_dict()["allowance"] == "allowed"


def test_policy_decision_is_a_dataclass() -> None:
    assert is_dataclass(AssetPolicyDecision)


def test_policy_to_dict_reports_allowed_and_blocked() -> None:
    payload = evaluate_policy(_requirement(), _provider_decision()).to_dict()
    assert "allowed_ids" in payload
    assert "blocked_ids" in payload
    assert payload["source_policy"] == "PREFERRED_LICENSED"


# ═══════════════════════════════════════════════════════════════════════════
# DECISION AUTHORITY
# ═══════════════════════════════════════════════════════════════════════════


def test_authority_blocks_without_a_provider_decision() -> None:
    resolution = AssetDecisionAuthority().decide(_requirement(), provider_decision=None)
    assert resolution.decision.state is AssetDecisionState.BLOCKED
    assert "NO_PROVIDER_DECISION" in resolution.decision.reason


def test_authority_blocks_when_no_provider_is_eligible() -> None:
    decision = ProviderDecision(eligible=[], selected_provider=None)
    resolution = AssetDecisionAuthority().decide(
        _requirement(source_policy=SourcePolicy.LOCAL_ONLY), provider_decision=decision
    )
    assert resolution.decision.state is AssetDecisionState.BLOCKED
    assert "NO_ELIGIBLE_PROVIDER" in resolution.decision.reason


def test_authority_blocks_when_the_provider_chosen_but_no_asset_acquired() -> None:
    resolution = AssetDecisionAuthority().decide(
        _requirement(), provider_decision=_provider_decision()
    )
    assert resolution.decision.state is AssetDecisionState.BLOCKED
    assert "NO_ASSET_OBTAINED" in resolution.decision.reason


def test_authority_blocks_when_evidence_is_demanded_and_absent() -> None:
    resolution = AssetDecisionAuthority().decide(
        _requirement(), provider_decision=_provider_decision(),
        selected_source="pexels.stock", confidence=0.9,
    )
    assert resolution.decision.state is AssetDecisionState.BLOCKED
    assert "NO_ASSET_EVIDENCE" in resolution.decision.reason


def test_authority_accepts_with_evidence() -> None:
    resolution = AssetDecisionAuthority().decide(
        _requirement(), provider_decision=_provider_decision(),
        selected_source="pexels.stock", confidence=0.8, evidence=(_evidence(),),
    )
    assert resolution.decision.state is AssetDecisionState.ACCEPTED
    assert resolution.decision.confidence == 0.8
    assert resolution.decision.evidence_ids() == ("asset_001",)


def test_authority_accepts_without_evidence_when_not_required() -> None:
    resolution = AssetDecisionAuthority().decide(
        _requirement(evidence_required=False), provider_decision=_provider_decision(),
        selected_source="pexels.stock", confidence=0.7,
    )
    assert resolution.decision.state is AssetDecisionState.ACCEPTED


def test_authority_applies_the_local_only_policy_end_to_end() -> None:
    requirement = _requirement(source_policy=SourcePolicy.LOCAL_ONLY)
    resolution = AssetDecisionAuthority().decide(
        requirement, provider_decision=_provider_decision(),
        selected_source="local.generate", evidence=(_evidence(),),
    )
    assert resolution.policy.allowed_ids == ("local.generate",)
    assert resolution.decision.state is AssetDecisionState.ACCEPTED


def test_authority_returns_a_complete_resolution() -> None:
    resolution = AssetDecisionAuthority().decide(
        _requirement(), provider_decision=_provider_decision(),
        selected_source="pexels.stock", evidence=(_evidence(),),
    )
    assert isinstance(resolution, AssetResolution)
    assert resolution.requirement.requirement_id == resolution.decision.requirement_id
    assert resolution.policy.requirement_id == resolution.decision.requirement_id
    assert set(resolution.to_dict()) == {"requirement", "policy", "decision"}


def test_authority_decide_all_preserves_order() -> None:
    requirements = tuple(requirements_from_capabilities(frozenset(Capability)))
    resolutions = AssetDecisionAuthority().decide_all(
        requirements, provider_decision=None
    )
    assert [r.requirement.requirement_id for r in resolutions] == [
        r.requirement_id for r in requirements
    ]


def test_authority_blocked_summary_is_machine_readable() -> None:
    requirements = tuple(requirements_from_capabilities(frozenset(Capability)))
    summary = AssetDecisionAuthority().decide_all(
        requirements, provider_decision=None
    )
    from hevi.production.p7.asset_intelligence import AssetDecisionAuthority as A

    blocked_summary = A().blocked_summary(summary)
    assert blocked_summary["total"] == len(requirements)
    assert blocked_summary["blocked"] == len(requirements)
    assert blocked_summary["any_available"] is False
    assert json.loads(json.dumps(blocked_summary))


def test_authority_never_invents_a_source() -> None:
    resolutions = AssetDecisionAuthority().decide_all(
        tuple(requirements_from_capabilities(frozenset(Capability))),
        provider_decision=None,
    )
    assert all(r.decision.selected_source == "" for r in resolutions)


def test_authority_is_deterministic() -> None:
    authority = AssetDecisionAuthority()
    requirement = _requirement()
    fingerprints = {
        authority.decide(
            requirement, provider_decision=_provider_decision(),
            selected_source="pexels.stock", evidence=(_evidence(),),
        ).decision.fingerprint()
        for _ in range(50)
    }
    assert len(fingerprints) == 1


# ═══════════════════════════════════════════════════════════════════════════
# BINDING
# ═══════════════════════════════════════════════════════════════════════════


def test_binding_derives_requirements_for_every_product() -> None:
    from hevi.production.p6.product_profiles import COMMERCIAL_PRODUCT_REGISTRY

    compiler = ProductCompiler()
    library = _library()
    for product_id in COMMERCIAL_PRODUCT_REGISTRY.list_ids():
        requirements = requirements_from_intent(
            compiler.compile(product_id, recipe_library=library)
        )
        assert requirements, product_id


def test_binding_requirements_are_deterministically_ordered() -> None:
    intent = _intent()
    assert requirements_from_intent(intent) == requirements_from_intent(intent)


def test_binding_requirement_ids_are_unique() -> None:
    ids = [r.requirement_id for r in requirements_from_intent(_intent())]
    assert len(ids) == len(set(ids))


def test_binding_uses_capabilities_not_product_identity() -> None:
    requirements = requirements_from_intent(_intent("P03_DOCUMENTARY"))
    declared = requirements_for(ProductType.DOCUMENTARY)
    keys = {r.requirement_id for r in requirements}
    for capability in declared.required | declared.optional:
        assert f"cap:{capability.value}" in keys, capability.value


def test_binding_includes_a_grammar_keyed_rule() -> None:
    keys = {r.requirement_id for r in requirements_from_intent(_intent("P03_DOCUMENTARY"))}
    assert "narrative:documentary" in keys
    assert "presenter:documentary_explainer" in keys


def test_binding_capability_lookup_is_deterministic() -> None:
    a = requirements_from_capabilities(frozenset({Capability.CHARACTER, Capability.NARRATOR}))
    b = requirements_from_capabilities(frozenset({Capability.NARRATOR, Capability.CHARACTER}))
    assert a == b


def test_binding_derivation_is_a_pure_function_of_shape() -> None:
    compiler, library = ProductCompiler(), _library()
    a = requirements_from_intent(compiler.compile("P03_DOCUMENTARY", recipe_library=library))
    b = requirements_from_intent(compiler.compile("P03_DOCUMENTARY", recipe_library=library))
    assert [r.content_hash() for r in a] == [r.content_hash() for r in b]


def test_binding_requirements_differ_when_capabilities_differ() -> None:
    compiler, library = ProductCompiler(), _library()
    a = requirements_from_intent(compiler.compile("P03_DOCUMENTARY", recipe_library=library))
    b = requirements_from_intent(
        compiler.compile("P02_HISTORY_RECONSTRUCTION", recipe_library=library)
    )
    assert {r.requirement_id for r in a} != {r.requirement_id for r in b}
    assert "cap:world" in {r.requirement_id for r in b}


def test_binding_summary_counts_both_axes() -> None:
    summary = binding_summary(requirements_from_intent(_intent()))
    assert summary["requirement_count"] >= 1
    assert summary["roles"]
    assert summary["media_types"]


def test_binding_requires_an_intent_object() -> None:
    with pytest.raises(AttributeError):
        requirements_from_intent(object())  # type: ignore[arg-type]


def test_binding_rule_to_requirement_preserves_terms() -> None:
    rule = RequirementRule(
        key="k", media_type=MediaType.IMAGE, semantic_role=AssetSemanticRole.CHARACTER,
        constraints=(("face_required", "true"),), evidence_required=False,
    )
    requirement = rule.to_requirement()
    assert requirement.requirement_id == "k"
    assert requirement.constraint_map() == {"face_required": "true"}
    assert requirement.evidence_required is False


def test_binding_error_is_typed() -> None:
    assert issubclass(AssetBindingError, ValueError)


# ═══════════════════════════════════════════════════════════════════════════
# SOURCING REUSE (the adapter)
# ═══════════════════════════════════════════════════════════════════════════


def test_sourcing_reused_adapter_maps_image_and_video() -> None:
    image = to_stock_request(_requirement(media_type=MediaType.IMAGE))
    video = to_stock_request(
        _requirement(media_type=MediaType.VIDEO, semantic_role=AssetSemanticRole.SCENE)
    )
    assert image.media_type == "image"
    assert video.media_type == "video"


def test_sourcing_reused_adapter_emits_stock_search_kwargs() -> None:
    request = to_stock_request(
        _requirement(constraints=(("query", "Napoleon portrait"),), quantity=3)
    )
    kwargs = request.as_search_kwargs(user_id="u1")
    assert kwargs == {
        "user_id": "u1", "query": "Napoleon portrait", "media_type": "image", "count": 3,
    }


def test_sourcing_reused_adapter_refuses_unservable_media() -> None:
    request = to_stock_request(_requirement(media_type=MediaType.MODEL3D))
    assert request.servable is False
    assert "no sourcing provider" in request.reason
    with pytest.raises(ValueError, match="UNSERVABLE_MEDIA_TYPE"):
        request.as_search_kwargs(user_id="u1")


def test_sourcing_reused_adapter_reports_audio_as_outside_the_stock_path() -> None:
    request = to_stock_request(
        _requirement(media_type=MediaType.AUDIO, semantic_role=AssetSemanticRole.VOICE)
    )
    assert request.servable is False
    assert "stock path does not serve AUDIO" in request.reason


def test_sourcing_reused_adapter_maps_media_provider_keys() -> None:
    assert to_media_request(_requirement()).provider_key == "image"
    audio = to_media_request(
        _requirement(media_type=MediaType.AUDIO, semantic_role=AssetSemanticRole.VOICE)
    )
    assert audio.provider_key == "voice"
    assert audio.servable is True


def test_sourcing_reused_adapter_unservable_types_are_declared() -> None:
    assert "MODEL3D" in UNSERVABLE_MEDIA_TYPES


def test_sourcing_reused_adapter_keeps_the_narrative_role_intact() -> None:
    # The translation changes spelling of media, never the role's meaning.
    request = to_stock_request(_requirement(semantic_role=AssetSemanticRole.CHARACTER))
    assert request.semantic_role == "CHARACTER"


def test_sourcing_reused_adapter_never_names_a_vendor() -> None:
    code = _code_only(ADAPTER_FILE).lower()
    for vendor in ("pexels", "unsplash", "fal", "nasa", "openai", "dashscope"):
        assert not re.search(rf"\b{re.escape(vendor)}\b", code), vendor


def test_sourcing_reused_validator_is_not_imported_by_p7() -> None:
    for path in P7_FILES:
        assert "asset_validator" not in path.read_text(), path.name


# ═══════════════════════════════════════════════════════════════════════════
# MUTATION
# ═══════════════════════════════════════════════════════════════════════════


def _code_only(path: Path) -> str:
    """Module source with every docstring removed.

    These modules' docstrings deliberately *name* the anti-patterns they forbid
    ("`if fal: ... elif pexels:` is the anti-pattern"), so a raw substring search
    flags the prohibition rather than a violation.
    """
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


def _mutate(tmp_path: Path, target: Path, needle: str, replacement: str) -> str:
    source = target.read_text()
    assert needle in source, f"anchor missing in {target.name}"
    mutated = source.replace(needle, replacement, 1)
    assert mutated != source
    (tmp_path / target.name).write_text(mutated)
    return mutated


def test_mutation_01_injected_product_branch_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path, P7_DIR / "asset_intelligence.py",
        "        policy = evaluate_policy(requirement, provider_decision, policy_id=policy_id)",
        "        if requirement.requirement_id.startswith(\"VIDEO/SCENE\"):\n"
        "            return self._blocked(requirement, policy, \"historical branch\")\n"
        "        policy = evaluate_policy(requirement, provider_decision, policy_id=policy_id)",
    )
    assert 'requirement_id.startswith("VIDEO/SCENE")' in mutated


def test_mutation_02_injected_provider_name_branch_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path, P7_DIR / "asset_policy.py",
        "    for provider_id in provider_decision.eligible:",
        "    for provider_id in provider_decision.eligible:\n"
        "        if provider_id == \"fal.image\":\n"
        "            continue\n"
        "        if provider_id == \"pexels.stock\":\n"
        "            allowances.append(ProviderAllowance(provider_id, Allowance.ALLOWED))\n"
        "            continue",
    )
    assert 'if provider_id == "fal.image"' in mutated


def test_mutation_03_evidence_bypass_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path, P7_DIR / "asset_intelligence.py",
        "        if requirement.evidence_required and not evidence:",
        "        if False:",
    )
    assert "if False:" in mutated
    # and the guard it bypassed is real
    resolution = AssetDecisionAuthority().decide(
        _requirement(), provider_decision=_provider_decision(),
        selected_source="pexels.stock", confidence=0.9,
    )
    assert resolution.decision.state is AssetDecisionState.BLOCKED


def test_mutation_04_accepting_without_a_provider_decision_must_fail() -> None:
    with pytest.raises(ValueError, match="ACCEPTED_WITHOUT_PROVIDER_DECISION"):
        AssetDecision(
            requirement_id="IMAGE/CHARACTER", state=AssetDecisionState.ACCEPTED,
            selected_source="pexels.stock",
        )


def test_mutation_05_available_without_a_licence_must_fail() -> None:
    with pytest.raises(ValueError, match="AVAILABLE_ASSET_WITHOUT_LICENSE"):
        AssetEvidence(asset_id="a", source="s", status=AssetStatus.AVAILABLE)


def test_mutation_06_removing_the_blocked_reason_requirement_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path, P7_DIR / "asset_contract.py",
        "        if self.status is AssetStatus.BLOCKED and not self.reason:",
        "        if False:",
    )
    assert "if False:" in mutated
    with pytest.raises(ValueError, match="BLOCKED_ASSET_WITHOUT_REASON"):
        AssetReference(
            asset_id="a", media_type=MediaType.VIDEO,
            semantic_role=AssetSemanticRole.SCENE, status=AssetStatus.BLOCKED,
        )


def test_mutation_07_second_authority_type_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path, P7_DIR / "asset_decision.py",
        "class AssetDecision:",
        "class AssetRegistry:\n    pass\n\n\nclass AssetDecision:",
    )
    names = {n.name for n in ast.walk(ast.parse(mutated)) if isinstance(n, ast.ClassDef)}
    assert "AssetRegistry" in names


def test_mutation_08_adding_an_acquisition_method_must_fail(tmp_path: Path) -> None:
    mutated = _mutate(
        tmp_path, P7_DIR / "asset_contract.py",
        "    def metadata_map(self) -> dict[str, str]:",
        "    def download(self, dest: str) -> str:\n"
        "        return f'fetched {self.uri}'\n\n"
        "    def metadata_map(self) -> dict[str, str]:",
    )
    assert "def download(" in mutated
    for model in (AssetReference, AssetEvidence, AssetRequirement, AssetDecision):
        assert not (set(dir(model)) & set(FORBIDDEN_ACQUISITION_METHODS))


def test_mutation_09_collapsing_the_two_vocabularies_must_fail(tmp_path: Path) -> None:
    """Folding media type into role would reintroduce P6.5.2's diagonal."""
    mutated = _mutate(
        tmp_path, P7_DIR / "asset_contract.py",
        '    IMAGE = "IMAGE"',
        '    IMAGE = "CHARACTER"\n    CHARACTER = "CHARACTER"',
    )
    tree = ast.parse(mutated)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "MediaType":
            values = {
                s.value.value
                for s in node.body if isinstance(s, ast.Assign)
            }
            assert "CHARACTER" in values
    # The real enum keeps them disjoint.
    assert MediaType.IMAGE.value != AssetSemanticRole.CHARACTER.value


def test_mutation_10_fallback_source_injection_must_fail(tmp_path: Path) -> None:
    """A default provider on an unservable requirement must be caught."""
    mutated = _mutate(
        tmp_path, P7_DIR / "asset_intelligence.py",
        "        if not policy.is_servable:",
        "        if not policy.is_servable:\n"
        "            return self._blocked(requirement, policy, \"NO_ELIGIBLE_PROVIDER\")\n"
        "        if False:",
    )
    assert 'if False:' in mutated
    resolution = AssetDecisionAuthority().decide(
        _requirement(source_policy=SourcePolicy.LOCAL_ONLY),
        provider_decision=ProviderDecision(eligible=[]),
    )
    assert resolution.decision.state is AssetDecisionState.BLOCKED
    assert resolution.decision.selected_source == ""