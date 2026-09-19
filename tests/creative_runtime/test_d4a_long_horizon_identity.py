"""D4-A: long-horizon persistent identity — no drift across production cycles."""

from __future__ import annotations

import pytest

from hevi.creative.layer4.character_authority import AppearanceKind, VoiceIdentity
from hevi.creative.layer4.identity_store import IdentityStore
from hevi.creative.layer4.persistent_identity import (
    IdentityError,
    PersistentIdentityRegistry,
    validate_pre_production,
)


def _registry() -> PersistentIdentityRegistry:
    return PersistentIdentityRegistry()


def _produce(registry, binding, owner="user-1", **planned) -> None:
    """One production cycle: validate + gate must not raise for clean plans."""
    verdict = validate_pre_production(
        registry=registry, binding=binding, owner_id=owner, **planned
    )
    assert verdict.verdict.value == "pass"


def test_long_horizon_three_projects_no_drift(tmp_path) -> None:
    store = IdentityStore(db_path=tmp_path / "identities.db")
    registry = _registry()
    identity = registry.create_identity(
        owner_id="user-1", canonical_name="Anna", voice=VoiceIdentity(voice_id="v-anna")
    )
    registry.add_appearance(
        identity.identity_id, owner_id="user-1", appearance_id="stage",
        kind=AppearanceKind.OUTFIT, reference_asset_ids=("ref-stage-v1",),
    )
    assert registry.get_identity(identity.identity_id, owner_id="user-1").identity_version == 2

    bindings = {}
    for project in ("proj-a", "proj-b", "proj-c"):
        bindings[project] = registry.bind(
            project_id=project, identity_id=identity.identity_id, owner_id="user-1"
        )
        for _ in range(3):  # 3 production revisions per project
            _produce(registry, bindings[project], planned_appearance_id="stage",
                     planned_voice_id="v-anna")

    # Global evolution: appearance v1->v2, new voice, rename.
    registry.update_appearance_assets(
        identity.identity_id, "stage", owner_id="user-1",
        reference_asset_ids=("ref-stage-v2",),
    )
    registry.assign_voice(identity.identity_id, VoiceIdentity(voice_id="v-anna-v2"), owner_id="user-1")
    registry.rename_identity(identity.identity_id, new_canonical_name="Anna Prime", owner_id="user-1")
    current = registry.get_identity(identity.identity_id, owner_id="user-1")
    assert current.identity_version == 5
    assert current.canonical_name == "Anna Prime"

    # Stay pinned: old bindings still resolve original snapshots.
    for project in ("proj-a", "proj-b"):
        pinned_app = registry.resolve_pinned_appearance(bindings[project], "stage")
        assert pinned_app.version == 1
        assert pinned_app.reference_asset_ids == ("ref-stage-v1",)
        assert registry.resolve_pinned_voice(bindings[project]).voice_id == "v-anna"

    # Explicit upgrade: project C moves to current.
    upgraded = registry.upgrade_binding(bindings["proj-c"].binding_id, owner_id="user-1")
    assert upgraded.pinned_identity_version == 5
    assert upgraded.pinned_appearance_versions["stage"] == 2
    _produce(registry, upgraded, planned_appearance_id="stage", planned_voice_id="v-anna-v2")

    # Same canonical identity everywhere; historical drift is zero.
    assert {b.identity_id for b in bindings.values()} == {identity.identity_id}
    assert registry.resolve_pinned_voice(bindings["proj-a"]).voice_id == "v-anna"

    # Durable round-trip preserves versions + history.
    for row_identity in registry.snapshot()["identities"]:
        store.save_identity("user-1", row_identity)
    for row_binding in registry.snapshot()["bindings"]:
        store.save_binding("user-1", row_binding)
    fresh = PersistentIdentityRegistry()
    fresh.restore({
        "identities": store.load_identities("user-1"),
        "bindings": store.load_bindings("user-1"),
    })
    reloaded = fresh.get_identity(identity.identity_id, owner_id="user-1")
    assert reloaded.identity_version == 5
    assert len(reloaded.appearance_history) == 1
    assert len(reloaded.voice_history) == 2
    assert reloaded.appearance_at_version("stage", 1).reference_asset_ids == ("ref-stage-v1",)
    assert reloaded.voice_at_version(2).voice_id == "v-anna"


def test_alias_stability(tmp_path) -> None:
    registry = _registry()
    identity = registry.create_identity(
        owner_id="user-1", canonical_name="Anna", voice=VoiceIdentity(voice_id="v-anna"),
        aliases=("Ann",),
    )
    renamed = registry.rename_identity(
        identity.identity_id, new_canonical_name="Anna Prime", owner_id="user-1"
    )
    # No new identity; old canonical name preserved as alias (casting stable).
    assert renamed.identity_id == identity.identity_id
    assert renamed.canonical_name == "Anna Prime"
    assert "Anna" in renamed.aliases and "Ann" in renamed.aliases

    aliased = registry.add_alias(renamed.identity_id, alias="Star", owner_id="user-1")
    assert "Star" in aliased.aliases
    cleaned = registry.remove_alias(renamed.identity_id, alias="Star", owner_id="user-1")
    assert "Star" not in cleaned.aliases
    # Canonical name is immutable through alias removal.
    with pytest.raises(IdentityError, match="IDENTITY_ALIAS_CANONICAL_IMMUTABLE"):
        registry.remove_alias(renamed.identity_id, alias="Anna Prime", owner_id="user-1")
    with pytest.raises(IdentityError, match="IDENTITY_ALIAS_UNKNOWN"):
        registry.remove_alias(renamed.identity_id, alias="Nobody", owner_id="user-1")
    # Canonical ID never changed through the whole lifecycle.
    assert registry.get_identity(identity.identity_id, owner_id="user-1").canonical_name == "Anna Prime"


def test_appearance_version_stability() -> None:
    registry = _registry()
    identity = registry.create_identity(
        owner_id="user-1", canonical_name="Anna", voice=VoiceIdentity(voice_id="v-anna")
    )
    registry.add_appearance(
        identity.identity_id, owner_id="user-1", appearance_id="coat",
        kind=AppearanceKind.OUTFIT, reference_asset_ids=("coat-v1",),
    )
    binding_a = registry.bind(project_id="proj-a", identity_id=identity.identity_id, owner_id="user-1")
    registry.update_appearance_assets(
        identity.identity_id, "coat", owner_id="user-1", reference_asset_ids=("coat-v2",)
    )
    binding_b = registry.bind(project_id="proj-b", identity_id=identity.identity_id, owner_id="user-1")
    registry.update_appearance_assets(
        identity.identity_id, "coat", owner_id="user-1", reference_asset_ids=("coat-v3",)
    )
    binding_c = registry.bind(project_id="proj-c", identity_id=identity.identity_id, owner_id="user-1")

    assert registry.resolve_pinned_appearance(binding_a, "coat").reference_asset_ids == ("coat-v1",)
    assert registry.resolve_pinned_appearance(binding_b, "coat").reference_asset_ids == ("coat-v2",)
    assert registry.resolve_pinned_appearance(binding_c, "coat").reference_asset_ids == ("coat-v3",)
    current = registry.get_identity(identity.identity_id, owner_id="user-1")
    assert current.appearance("coat").version == 3
    assert len(current.appearance_history) == 2
    with pytest.raises(IdentityError, match="IDENTITY_APPEARANCE_VERSION_UNKNOWN"):
        current.appearance_at_version("coat", 9)


def test_voice_version_stability() -> None:
    registry = _registry()
    identity = registry.create_identity(
        owner_id="user-1", canonical_name="Anna", voice=VoiceIdentity(voice_id="v-anna-v1")
    )
    historical = registry.bind(project_id="proj-a", identity_id=identity.identity_id, owner_id="user-1")
    registry.assign_voice(identity.identity_id, VoiceIdentity(voice_id="v-anna-v2"), owner_id="user-1")
    # Historical production is not silently rewritten.
    assert registry.resolve_pinned_voice(historical).voice_id == "v-anna-v1"
    # New production only uses the new voice after explicit upgrade.
    upgraded = registry.upgrade_binding(historical.binding_id, owner_id="user-1")
    assert registry.resolve_pinned_voice(upgraded).voice_id == "v-anna-v2"
    current = registry.get_identity(identity.identity_id, owner_id="user-1")
    assert [r.voice.voice_id for r in current.voice_history] == ["v-anna-v1", "v-anna-v2"]
