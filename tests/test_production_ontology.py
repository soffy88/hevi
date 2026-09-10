from __future__ import annotations

from hevi.production_graph import (
    Character,
    CharacterState,
    Episode,
    Location,
    LocationState,
    LookVariant,
    ProductionGraphRepository,
    ProductionGraphSnapshot,
    ProductionProject,
    ProductionRevision,
    Prop,
    PropState,
    Scene,
)
from hevi.production_graph.adapters.vault import (
    manifest_to_character,
    manifest_to_look_variant,
    manifest_to_reference_items,
)
from hevi.vault.schemas import Manifest, ManifestFile


def test_vault_identity_pack_binds_identity_look_and_typed_refs() -> None:
    manifest = Manifest(
        pack_id="identity/C001",
        pack_type="identity",
        version="1.0.0",
        name="A",
        immutable_traits="blue coat",
        lifecycle="published",
        files={
            "portrait.png": ManifestFile(sha256="portrait-sha", role="canonical_portrait"),
            "turnaround.mp4": ManifestFile(sha256="motion-sha", role="turnaround_video"),
        },
    )
    character = manifest_to_character(manifest, project_id="p", revision_id="r")
    look = manifest_to_look_variant(
        manifest, character_id=character.id, project_id="p", revision_id="r"
    )
    refs = manifest_to_reference_items(manifest, character_id=character.id, revision_id="r")

    assert character.identity_pack_id == manifest.pack_id
    assert look.character_id == character.id
    assert {item.role.value for item in refs} == {"CHARACTER_IDENTITY", "VIDEO_MOTION"}
    assert all(item.locked for item in refs)
    assert all(item.artifact_id for item in refs)


async def _ontology_snapshot() -> ProductionGraphSnapshot:
    project = ProductionProject(user_id="u", title="continuity")
    revision = ProductionRevision(project_id=project.id)
    project = project.model_copy(update={"current_revision_id": revision.id})
    character = Character(project_id=project.id, revision_id=revision.id, canonical_name="A")
    look_a = LookVariant(
        project_id=project.id,
        revision_id=revision.id,
        character_id=character.id,
        name="arrival",
        costume="travel coat",
    )
    look_b = LookVariant(
        project_id=project.id,
        revision_id=revision.id,
        character_id=character.id,
        name="battle",
        costume="damaged armor",
    )
    world_location = Location(project_id=project.id, revision_id=revision.id, name="gate")
    prop = Prop(project_id=project.id, revision_id=revision.id, name="sword")
    episode_one = Episode(project_id=project.id, revision_id=revision.id, number=1)
    episode_two = Episode(project_id=project.id, revision_id=revision.id, number=2)
    scene_one = Scene(
        project_id=project.id,
        revision_id=revision.id,
        episode_id=episode_one.id,
        location_id=world_location.id,
        character_ids=[character.id],
        prop_ids=[prop.id],
    )
    scene_two = scene_one.model_copy(update={"id": "scene-two", "episode_id": episode_two.id})
    states = [
        CharacterState(
            project_id=project.id,
            revision_id=revision.id,
            character_id=character.id,
            scene_id=scene_one.id,
            look_variant_id=look_a.id,
            location_id=world_location.id,
        ),
        CharacterState(
            project_id=project.id,
            revision_id=revision.id,
            character_id=character.id,
            scene_id=scene_two.id,
            look_variant_id=look_b.id,
            location_id=world_location.id,
            possessions=[prop.id],
        ),
    ]
    return ProductionGraphSnapshot(
        project=project,
        revision=revision,
        characters=[character],
        look_variants=[look_a, look_b],
        character_states=states,
        locations=[world_location],
        location_states=[
            LocationState(
                project_id=project.id,
                revision_id=revision.id,
                location_id=world_location.id,
                scene_id=scene_two.id,
                damage_state="burned",
            )
        ],
        props=[prop],
        prop_states=[
            PropState(
                project_id=project.id,
                revision_id=revision.id,
                prop_id=prop.id,
                scene_id=scene_two.id,
                owner_character_id=character.id,
            )
        ],
        episodes=[episode_one, episode_two],
        scenes=[scene_one, scene_two],
    )


async def test_dynamic_state_is_explicit_across_episodes() -> None:
    snapshot = await _ontology_snapshot()
    snapshot.validate_referential_integrity()
    assert [state.look_variant_id for state in snapshot.character_states] == [
        snapshot.look_variants[0].id,
        snapshot.look_variants[1].id,
    ]
    assert snapshot.prop_states[0].owner_character_id == snapshot.characters[0].id


def test_ontology_snapshot_repository_is_reopenable() -> None:
    # Ensure the repository accepts the same graph object used by the async
    # integration path without introducing a separate asset store.
    import asyncio

    snapshot = asyncio.run(_ontology_snapshot())
    repository = ProductionGraphRepository()
    asyncio.run(repository.save_snapshot(snapshot))
    reopened = asyncio.run(repository.get_snapshot(snapshot.project.id))
    assert reopened is not None
    assert reopened.characters[0].id == snapshot.characters[0].id
