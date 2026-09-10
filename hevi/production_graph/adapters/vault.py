"""Vault IdentityPack → canonical character/look/reference bindings."""

from __future__ import annotations

from hevi.production_graph.domain import (
    Character,
    LookVariant,
    ReferenceItem,
    ReferenceRole,
)
from hevi.production_graph.ids import stable_id
from hevi.vault.schemas import Manifest

_ROLE_MAP: dict[str, ReferenceRole] = {
    "canonical_portrait": ReferenceRole.CHARACTER_IDENTITY,
    "portrait": ReferenceRole.CHARACTER_IDENTITY,
    "identity": ReferenceRole.CHARACTER_IDENTITY,
    "turnaround_video": ReferenceRole.VIDEO_MOTION,
    "kinetic_ref": ReferenceRole.VIDEO_MOTION,
    "action_pose": ReferenceRole.CHARACTER_LOOK,
    "expression_sheet": ReferenceRole.CHARACTER_LOOK,
}


def manifest_to_character(
    manifest: Manifest, *, project_id: str, revision_id: str, character_id: str | None = None
) -> Character:
    """Bind an existing identity pack to a stable semantic character."""

    canonical_character_id = character_id or stable_id("character", f"{project_id}:{manifest.name}")
    return Character(
        id=canonical_character_id,
        project_id=project_id,
        revision_id=revision_id,
        canonical_name=manifest.name,
        immutable_traits={
            "traits": manifest.immutable_traits,
            "era_lock": manifest.era_lock,
        },
        identity_pack_id=manifest.pack_id,
        voice_profile_id=str(manifest.voice.get("voice_id") or "") or None,
        legacy_ids={"vault.pack_id": manifest.pack_id, "vault.version": manifest.version},
    )


def manifest_to_look_variant(
    manifest: Manifest, *, character_id: str, project_id: str, revision_id: str, name: str = "default"
) -> LookVariant:
    """Create a semantic look binding without copying Vault binary assets."""

    return LookVariant(
        id=stable_id("look-variant", f"{manifest.pack_id}:{manifest.version}:{name}"),
        project_id=project_id,
        revision_id=revision_id,
        character_id=character_id,
        name=name,
        costume=manifest.immutable_traits,
        identity_pack_refs=[manifest.pack_id],
        lifecycle="LOCKED" if manifest.lifecycle == "published" else "SELECTED",
    )


def manifest_to_reference_items(
    manifest: Manifest, *, character_id: str, revision_id: str
) -> list[ReferenceItem]:
    """Expose typed references to existing Vault objects/artifacts."""

    items: list[ReferenceItem] = []
    for path, file in manifest.files.items():
        role = _ROLE_MAP.get(file.role)
        if role is None:
            continue
        items.append(
            ReferenceItem(
                id=stable_id("reference-item", f"{manifest.pack_id}:{manifest.version}:{path}"),
                revision_id=revision_id,
                role=role,
                production_entity_id=character_id,
                artifact_id=file.sha256,
                priority=100 if role is ReferenceRole.CHARACTER_IDENTITY else 50,
                locked=manifest.lifecycle == "published",
                metadata={
                    "vault_pack_id": manifest.pack_id,
                    "vault_version": manifest.version,
                    "vault_path": path,
                    "vault_file_role": file.role,
                },
            )
        )
    return items


__all__ = ["manifest_to_character", "manifest_to_look_variant", "manifest_to_reference_items"]
