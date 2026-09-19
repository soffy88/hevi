"""D3-E: creative-intelligence composition (memory + identity + continuity).

No new memory system: this test proves the three existing authorities
jointly resolve one new-production request into correct planning inputs:

- user preference (CreativeMemory, user scope): cinematic realistic
- project convention (CreativeMemory, project scope): winter appearance
- persistent identity + appearance + voice (registry + binding)
- live character state (ContinuityLedger fact): currently injured
"""

from __future__ import annotations

from hevi.creative.layer4.character_authority import AppearanceKind, VoiceIdentity
from hevi.creative.layer4.continuity_gate import FactSource, record_production_fact
from hevi.creative.layer4.creative_memory import CreativeMemory
from hevi.creative.layer4.identity_store import IdentityStore
from hevi.creative.layer4.persistent_identity import (
    ContinuityCategory,
    PersistentIdentityRegistry,
)


def test_composition_resolves_planning_inputs(tmp_path) -> None:
    memory = CreativeMemory.at_path(tmp_path / "memory.db")
    memory.edit(
        scope="user", key="style_preference", content="cinematic realistic"
    )
    memory.edit(
        scope="project:conventions",
        key="appearance_convention",
        content="this project uses winter appearance",
        project_id="proj-b",
    )

    store = IdentityStore(db_path=tmp_path / "identities.db")
    registry = PersistentIdentityRegistry()
    identity = registry.create_identity(
        owner_id="user-1",
        canonical_name="Anna",
        voice=VoiceIdentity(voice_id="v-anna"),
    )
    registry.add_appearance(
        identity.identity_id,
        owner_id="user-1",
        appearance_id="winter-outfit",
        kind=AppearanceKind.OUTFIT,
        reference_asset_ids=("ref-anna-winter",),
    )
    store.save_identity("user-1", registry.get_identity(identity.identity_id, owner_id="user-1").model_dump(mode="json"))
    binding = registry.bind(
        project_id="proj-b", identity_id=identity.identity_id, owner_id="user-1"
    )
    record_production_fact(
        store=store,
        registry=registry,
        owner_id="user-1",
        identity_id=identity.identity_id,
        category=ContinuityCategory.CHARACTER_STATE,
        statement="currently injured",
        source=FactSource.APPROVED_SHOT_RESULT,
        source_artifact_id="artifact-ep1",
        episode="ep1",
    )

    # New production request resolution — each authority contributes.
    user_prefs = {
        entry.entry_key: entry.content
        for entry in memory.inspect(scope="user")
    }
    project_conventions = {
        entry.entry_key: entry.content
        for entry in memory.recall_for_project("proj-b", "appearance")
    }
    bound = registry.get_binding(binding.binding_id, owner_id="user-1")
    resolved_identity = registry.get_identity(bound.identity_id, owner_id="user-1")
    states = [
        fact.statement
        for fact in registry.ledger.facts_for_scope(identity.identity_id, episode="ep1")
        if fact.category is ContinuityCategory.CHARACTER_STATE
    ]
    planning_inputs = {
        "style_preference": user_prefs.get("style_preference"),
        "project_convention": project_conventions.get("appearance_convention"),
        "identity_id": resolved_identity.identity_id,
        "appearance_id": "winter-outfit",
        "appearance_refs": list(
            resolved_identity.appearance("winter-outfit").reference_asset_ids
        ),
        "voice_id": resolved_identity.effective_voice("winter-outfit").voice_id,
        "character_state": states,
        "pinned_identity_version": bound.pinned_identity_version,
    }

    assert planning_inputs["style_preference"] == "cinematic realistic"
    assert planning_inputs["project_convention"] == "this project uses winter appearance"
    assert planning_inputs["identity_id"] == identity.identity_id
    assert planning_inputs["appearance_refs"] == ["ref-anna-winter"]
    assert planning_inputs["voice_id"] == "v-anna"
    assert planning_inputs["character_state"] == ["currently injured"]
    assert planning_inputs["pinned_identity_version"] == 2
