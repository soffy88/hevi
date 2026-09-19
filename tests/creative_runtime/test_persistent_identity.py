"""D2-B gates: persistent identity, bindings, continuity, cross-project E2E."""

from __future__ import annotations

import pytest

from hevi.creative.layer4.character_authority import AppearanceKind, VoiceIdentity
from hevi.creative.layer4.persistent_identity import (
    ContinuityCategory,
    ContinuityFactRecord,
    ContinuitySeverity,
    IdentityError,
    IdentityKind,
    PersistentIdentityRegistry,
    validate_pre_production,
)


def _voice(voice_id: str = "v-anna") -> VoiceIdentity:
    return VoiceIdentity(voice_id=voice_id)


def _registry() -> PersistentIdentityRegistry:
    return PersistentIdentityRegistry()


def _identity(registry: PersistentIdentityRegistry, owner: str = "user-1"):
    return registry.create_identity(
        owner_id=owner,
        canonical_name="Anna",
        voice=_voice(),
        kind=IdentityKind.CHARACTER,
        canon_constraints=("anna never leaves harbor city",),
    )


def test_global_identity_vs_project_binding_are_distinct() -> None:
    registry = _registry()
    identity = _identity(registry)
    binding = registry.bind(
        project_id="proj-a", identity_id=identity.identity_id, owner_id="user-1"
    )
    assert binding.identity_id == identity.identity_id
    assert binding.project_id == "proj-a"
    assert binding.pinned_identity_version == identity.identity_version == 1
    assert binding.binding_id != identity.identity_id


def test_tenant_isolation_private_by_default() -> None:
    registry = _registry()
    identity = _identity(registry, owner="user-1")
    with pytest.raises(IdentityError, match="IDENTITY_OWNER_MISMATCH"):
        registry.get_identity(identity.identity_id, owner_id="user-2")
    with pytest.raises(IdentityError, match="IDENTITY_OWNER_MISMATCH"):
        registry.bind(
            project_id="proj-x", identity_id=identity.identity_id, owner_id="user-2"
        )
    with pytest.raises(IdentityError, match="IDENTITY_OWNER_REQUIRED"):
        registry.create_identity(
            owner_id="anonymous", canonical_name="Ghost", voice=_voice()
        )
    with pytest.raises(IdentityError, match="IDENTITY_OWNER_REQUIRED"):
        registry.create_identity(owner_id="", canonical_name="Ghost", voice=_voice())


def test_project_cannot_silently_mutate_global_identity() -> None:
    registry = _registry()
    identity = _identity(registry)
    # Structural override refused; only allow-listed display fields pass.
    with pytest.raises(IdentityError, match="IDENTITY_OVERRIDE_NOT_ALLOWED"):
        registry.bind(
            project_id="proj-a",
            identity_id=identity.identity_id,
            owner_id="user-1",
            overrides={"voice": "v-evil"},
        )
    binding = registry.bind(
        project_id="proj-a",
        identity_id=identity.identity_id,
        owner_id="user-1",
        overrides={"display_name": "Anna (Ep1)"},
    )
    assert binding.overrides == {"display_name": "Anna (Ep1)"}
    # Global identity untouched by the binding override.
    fresh = registry.get_identity(identity.identity_id, owner_id="user-1")
    assert fresh.canonical_name == "Anna"
    assert fresh.identity_version == 1


def test_continuity_facts_have_provenance_and_scope() -> None:
    registry = _registry()
    identity = _identity(registry)
    registry.ledger.record(
        ContinuityFactRecord(
            fact_id="f1",
            identity_id=identity.identity_id,
            category=ContinuityCategory.LOCATION,
            statement="harbor city",
            episode="ep1",
            scene="sc3",
            shot="sh7",
            revision="rev-2",
            source_artifact_id="artifact-1",
            provenance="observer-state-extraction",
        )
    )
    scoped = registry.ledger.facts_for_scope(
        identity.identity_id, episode="ep1", scene="sc3"
    )
    assert len(scoped) == 1
    assert scoped[0].provenance == "observer-state-extraction"
    assert scoped[0].revision == "rev-2"
    assert registry.ledger.facts_for_scope(identity.identity_id, episode="ep2") == ()


def test_validation_pass_warn_block() -> None:
    registry = _registry()
    identity = _identity(registry)
    registry.ledger.record(
        ContinuityFactRecord(
            fact_id="loc",
            identity_id=identity.identity_id,
            category=ContinuityCategory.LOCATION,
            statement="harbor city",
            source_artifact_id="a1",
            provenance="canon",
        )
    )
    binding = registry.bind(
        project_id="proj-a", identity_id=identity.identity_id, owner_id="user-1"
    )
    clean = validate_pre_production(
        registry=registry,
        binding=binding,
        owner_id="user-1",
        planned_location="harbor city",
    )
    assert clean.verdict is ContinuitySeverity.PASS

    warned = validate_pre_production(
        registry=registry,
        binding=binding,
        owner_id="user-1",
        planned_location="desert outpost",
        planned_voice_id="v-wrong",
    )
    assert warned.verdict is ContinuitySeverity.WARN
    codes = {finding.code for finding in warned.findings}
    assert "IDENTITY_LOCATION_UNRECORDED" in codes
    assert "IDENTITY_VOICE_MISMATCH" in codes

    hard_block = validate_pre_production(
        registry=registry,
        binding=binding,
        owner_id="user-1",
        planned_statements=("Plot twist: not anna never leaves harbor city",),
    )
    assert hard_block.verdict is ContinuitySeverity.BLOCK
    assert any(
        finding.code == "IDENTITY_CANON_CONTRADICTION"
        for finding in hard_block.findings
    )

    unrelated = validate_pre_production(
        registry=registry,
        binding=binding,
        owner_id="user-1",
        planned_statements=("Anna buys fresh fish at the harbor market",),
    )
    assert unrelated.verdict is not ContinuitySeverity.BLOCK


def test_validation_block_unknown_appearance_and_owner() -> None:
    registry = _registry()
    identity = _identity(registry)
    binding = registry.bind(
        project_id="proj-a", identity_id=identity.identity_id, owner_id="user-1"
    )
    unknown = validate_pre_production(
        registry=registry,
        binding=binding,
        owner_id="user-1",
        planned_appearance_id="mech-suit",
    )
    assert unknown.verdict is ContinuitySeverity.BLOCK
    wrong_owner = validate_pre_production(
        registry=registry, binding=binding, owner_id="user-2"
    )
    assert wrong_owner.verdict is ContinuitySeverity.BLOCK


def test_cross_project_reuse_e2e() -> None:
    """Project A builds identity -> artifact; Project B reuses -> new artifact."""
    registry = _registry()
    identity = registry.create_identity(
        owner_id="user-1",
        canonical_name="Anna",
        voice=_voice("v-anna"),
        kind=IdentityKind.PRESENTER,
        default_references=("ref-anna-default",),
    )
    registry.add_appearance(
        identity.identity_id,
        owner_id="user-1",
        appearance_id="stage-outfit",
        kind=AppearanceKind.OUTFIT,
        reference_asset_ids=("ref-anna-stage",),
    )
    binding_a = registry.bind(
        project_id="proj-a", identity_id=identity.identity_id, owner_id="user-1"
    )
    # Project A produces against its binding: approved appearance + voice.
    verdict_a = validate_pre_production(
        registry=registry,
        binding=binding_a,
        owner_id="user-1",
        planned_appearance_id="stage-outfit",
        planned_voice_id="v-anna",
    )
    assert verdict_a.verdict is ContinuitySeverity.PASS
    artifact_a = {
        "artifact_id": "artifact-a1",
        "project_id": "proj-a",
        "identity_id": identity.identity_id,
        "appearance_id": "stage-outfit",
        "voice_id": "v-anna",
    }
    registry.ledger.record(
        ContinuityFactRecord(
            fact_id="prod-a1",
            identity_id=identity.identity_id,
            category=ContinuityCategory.APPEARANCE,
            statement="stage-outfit worn in proj-a ep1",
            episode="ep1",
            source_artifact_id=artifact_a["artifact_id"],
            provenance="proj-a-production",
        )
    )

    # Project B reuses the SAME identity: new binding, same canonical id.
    binding_b = registry.reuse_in_project(
        identity_id=identity.identity_id, owner_id="user-1", new_project_id="proj-b"
    )
    assert binding_b.identity_id == identity.identity_id
    assert binding_b.project_id == "proj-b"
    assert binding_b.binding_id != binding_a.binding_id
    verdict_b = validate_pre_production(
        registry=registry,
        binding=binding_b,
        owner_id="user-1",
        planned_appearance_id="stage-outfit",
        planned_voice_id="v-anna",
    )
    assert verdict_b.verdict is ContinuitySeverity.PASS
    # One authority: both bindings resolve to the same owner + identity.
    assert registry.get_binding(binding_a.binding_id, owner_id="user-1").owner_id == (
        registry.get_binding(binding_b.binding_id, owner_id="user-1").owner_id
    )


def test_version_pinning_upgrade_or_stay() -> None:
    registry = _registry()
    identity = _identity(registry)
    binding = registry.bind(
        project_id="proj-a", identity_id=identity.identity_id, owner_id="user-1"
    )
    # Global change bumps the version; the old binding stays pinned (history safe).
    registry.add_appearance(
        identity.identity_id,
        owner_id="user-1",
        appearance_id="aged",
        kind=AppearanceKind.AGE,
    )
    current = registry.get_identity(identity.identity_id, owner_id="user-1")
    assert current.identity_version == 2
    pinned = registry.get_binding(binding.binding_id, owner_id="user-1")
    assert pinned.pinned_identity_version == 1
    assert pinned.is_stale(current.identity_version)
    drift = validate_pre_production(
        registry=registry, binding=pinned, owner_id="user-1"
    )
    assert drift.verdict is ContinuitySeverity.WARN
    # Explicit upgrade opts into the new version.
    upgraded = registry.upgrade_binding(binding.binding_id, owner_id="user-1")
    assert upgraded.pinned_identity_version == 2
    assert not upgraded.is_stale(current.identity_version)
    assert "aged" in upgraded.pinned_appearance_versions
