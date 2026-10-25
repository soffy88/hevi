"""Multi-image reference bundle -- ``story.reference_bundle``.

Builds, for one shot, the ordered list of reference blocks that a
generation step may cite, so the same character / scene / prop keeps
the same locked description across shots (character consistency by
reference, method only -- no code or example text copied from any
outside implementation).

Field names reuse the asset-registry names already used by
``story.episode_prompts`` (``portrait_block`` / ``block`` /
``signature_props`` / ``face_anchors`` / ``outfit``) so a bundle entry
can be registered without a new vocabulary.

Reference order is fixed: characters (in the shot's ``character_ids``
order), then the scene, then props (in the shot's ``prop_ids`` order),
then a costume variant (if any) split into two references.

A costume variant follows the identity/style separation used by
``story.episode_prompts``: the identity block locks the character's
face anchors / hair / body proportions and never changes; a costume
change swaps only the style block (outfit). The variant therefore
emits two references: an ``identity`` reference whose block is the
character's registry block (``[缺失]`` when that character has no
registry entry or no block, never invented), and a ``style``
reference whose block is the variant's ``outfit`` text (``[缺失]``
when no outfit was given).

Rules that matter:

* Unknown character / scene ids raise :class:`CapabilityError` --
  a bundle must never be built against a character or scene that
  does not exist. Unknown props and unknown variant characters do
  not raise; they are emitted as ``[缺失]`` blocks and recorded in
  ``warnings``, for the caller / gates to judge.
* Missing fields are NEVER silently invented. A missing block is
  literally marked ``[缺失]`` and recorded in ``warnings`` (build)
  or in the returned issues (validate).
* The output is JSON serializable: ids, blocks and sources are
  plain strings, and ``warnings`` / issues are plain dicts.
"""

from __future__ import annotations

from typing import Any

from hevi.capabilities.errors import CapabilityError

MISSING = "[缺失]"

VALID_KINDS = ("character", "scene", "prop", "costume")

__all__ = [
    "MISSING",
    "VALID_KINDS",
    "build_bundle",
    "validate_bundle",
]


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _nonempty(value: Any) -> str | None:
    text = _as_str(value).strip()
    return text if text else None


def _entry_block(entry: dict[str, Any]) -> str | None:
    """Locked block text for a registry entry.

    Character entries may carry the block as ``portrait_block``
    (the ``story.episode_prompts`` convention) or as ``block``;
    the portrait form wins when both are present.
    """
    for key in ("portrait_block", "block"):
        block = _nonempty(entry.get(key))
        if block is not None:
            return block
    return None


def _has_face_anchors(entry: dict[str, Any]) -> bool:
    value = entry.get("face_anchors")
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) > 0
    return True


def _normalize_registry(asset_registry: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(asset_registry, dict):
        raise CapabilityError(
            "story.reference_bundle: 'asset_registry' must be an object"
        )
    normalized: dict[str, dict[str, Any]] = {}
    for key, entry in asset_registry.items():
        normalized[_as_str(key)] = entry if isinstance(entry, dict) else {}
    return normalized


def _registry_entry(
    registry: dict[str, dict[str, Any]], asset_id: str
) -> dict[str, Any] | None:
    entry = registry.get(asset_id)
    if entry is None:
        return None
    return entry


def build_bundle(shot: dict[str, Any], *, asset_registry: dict[str, Any]) -> dict[str, Any]:
    """Build the ordered reference bundle for one shot.

    ``shot`` carries ``shot_id``, ``scene_id`` (optional),
    ``character_ids`` (optional list), ``prop_ids`` (optional list)
    and ``costume_variant`` (optional, with ``character_id``,
    ``outfit`` and ``variant_id``). ``asset_registry`` maps an
    asset id to ``{kind, block, face_anchors?, outfit?}``.

    Returns ``{shot_id, character_ids, references, warnings}`` where
    each reference is ``{role, asset_id, block, source}`` and each
    warning is ``{asset_id, code, message}``.
    """
    registry = _normalize_registry(asset_registry)
    if not isinstance(shot, dict):
        raise CapabilityError("story.reference_bundle: 'shot' must be an object")
    shot_id = _nonempty(shot.get("shot_id"))
    if shot_id is None:
        raise CapabilityError("story.reference_bundle: 'shot_id' is missing")

    character_ids_raw = shot.get("character_ids")
    if character_ids_raw is None:
        character_ids: list[str] = []
    elif isinstance(character_ids_raw, (list, tuple)):
        character_ids = [_as_str(cid) for cid in character_ids_raw]
    else:
        raise CapabilityError(
            f"story.reference_bundle: 'character_ids' must be a list "
            f"(shot {shot_id})"
        )
    prop_ids_raw = shot.get("prop_ids")
    if prop_ids_raw is None:
        prop_ids: list[str] = []
    elif isinstance(prop_ids_raw, (list, tuple)):
        prop_ids = [_as_str(pid) for pid in prop_ids_raw]
    else:
        raise CapabilityError(
            f"story.reference_bundle: 'prop_ids' must be a list (shot {shot_id})"
        )

    # Unknown characters / scenes are hard errors, never silently built.
    for cid in character_ids:
        if _registry_entry(registry, cid) is None:
            raise CapabilityError(
                f"story.reference_bundle: unknown character id: {cid!r} "
                f"(shot {shot_id})"
            )
    scene_id = _nonempty(shot.get("scene_id"))
    if scene_id is not None and _registry_entry(registry, scene_id) is None:
        raise CapabilityError(
            f"story.reference_bundle: unknown scene id: {scene_id!r} "
            f"(shot {shot_id})"
        )

    references: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    def _warn(asset_id: str, code: str, message: str) -> None:
        warnings.append({"asset_id": asset_id, "code": code, "message": message})

    # 1. Characters, in the shot's character_ids order.
    for cid in character_ids:
        entry = _registry_entry(registry, cid) or {}
        block = _entry_block(entry)
        if block is None:
            block = MISSING
            _warn(cid, "missing_block", f"角色 {cid} 缺失锁定描述块，已记为[缺失]。")
        references.append(
            {"role": "character", "asset_id": cid, "block": block, "source": "character_ids"}
        )

    # 2. Scene.
    if scene_id is not None:
        entry = _registry_entry(registry, scene_id) or {}
        block = _entry_block(entry)
        if block is None:
            block = MISSING
            _warn(scene_id, "missing_block", f"场景 {scene_id} 缺失锁定描述块，已记为[缺失]。")
        references.append(
            {"role": "scene", "asset_id": scene_id, "block": block, "source": "scene_id"}
        )

    # 3. Props, in the shot's prop_ids order. An unknown prop is not
    # invented: it is emitted as [缺失] and warned, for validate /
    # gates to catch as an error.
    for pid in prop_ids:
        entry = _registry_entry(registry, pid)
        if entry is None:
            references.append(
                {"role": "prop", "asset_id": pid, "block": MISSING, "source": "prop_ids"}
            )
            _warn(pid, "unknown_asset", f"道具 {pid} 在 asset_registry 中不存在，已记为[缺失]。")
            continue
        block = _entry_block(entry)
        if block is None:
            block = MISSING
            _warn(pid, "missing_block", f"道具 {pid} 缺失锁定描述块，已记为[缺失]。")
        references.append(
            {"role": "prop", "asset_id": pid, "block": block, "source": "prop_ids"}
        )

    # 4. Costume variant, split into identity + style.
    variant = shot.get("costume_variant")
    if variant is not None:
        if not isinstance(variant, dict):
            raise CapabilityError(
                f"story.reference_bundle: 'costume_variant' must be an object "
                f"(shot {shot_id})"
            )
        variant_character = _nonempty(variant.get("character_id"))
        variant_id = _nonempty(variant.get("variant_id"))
        if variant_character is None:
            variant_id = variant_id or MISSING
            identity_asset = MISSING
            identity_block = MISSING
            _warn(
                MISSING,
                "missing_character_id",
                "换装变体缺失 character_id，身份块已记为[缺失]。",
            )
        else:
            variant_id = variant_id or f"{variant_character}_variant"
            identity_asset = variant_character
            entry = _registry_entry(registry, variant_character)
            identity_block = _entry_block(entry) if entry is not None else None
            if identity_block is None:
                identity_block = MISSING
                _warn(
                    variant_character,
                    "missing_block",
                    f"换装变体角色 {variant_character} 缺失身份块，已记为[缺失]。",
                )
        references.append(
            {
                "role": "character",
                "asset_id": identity_asset,
                "block": identity_block,
                "source": "costume_variant:identity",
            }
        )
        outfit = _nonempty(variant.get("outfit"))
        style_block = outfit if outfit is not None else MISSING
        if outfit is None:
            _warn(
                variant_character or MISSING,
                "missing_outfit",
                "换装变体缺失 outfit，造型块已记为[缺失]。",
            )
        references.append(
            {
                "role": "costume",
                "asset_id": variant_id,
                "block": style_block,
                "source": "costume_variant:style",
            }
        )

    return {
        "shot_id": shot_id,
        "character_ids": character_ids,
        "references": references,
        "warnings": warnings,
    }


def validate_bundle(
    bundle: dict[str, Any], *, asset_registry: dict[str, Any]
) -> list[dict[str, Any]]:
    """Validate a bundle against the asset registry.

    Returns a list of issues, each ``{asset_id, severity, code,
    message}`` with severity ``error`` or ``warning``. It never
    invents content: a missing block stays ``[缺失]`` and is
    reported, and a bundle without a ``character_ids`` field simply
    skips the missing-character-reference check (the shot's list
    cannot be inferred from the references alone).
    """
    registry = _normalize_registry(asset_registry)
    if not isinstance(bundle, dict):
        return [
            {
                "asset_id": MISSING,
                "severity": "error",
                "code": "invalid_bundle",
                "message": "bundle 必须是对象。",
            }
        ]
    references_raw = bundle.get("references")
    if not isinstance(references_raw, list):
        return [
            {
                "asset_id": MISSING,
                "severity": "error",
                "code": "invalid_bundle",
                "message": "bundle.references 必须是列表。",
            }
        ]

    issues: list[dict[str, Any]] = []

    def _issue(asset_id: str, severity: str, code: str, message: str) -> None:
        issues.append(
            {"asset_id": asset_id, "severity": severity, "code": code, "message": message}
        )

    seen: set[str] = set()
    face_warned: set[str] = set()
    character_refs: set[str] = set()
    for raw in references_raw:
        if not isinstance(raw, dict):
            _issue(MISSING, "error", "invalid_reference", "reference 必须是对象。")
            continue
        asset_id = _nonempty(raw.get("asset_id")) or MISSING
        role = _nonempty(raw.get("role"))
        block = raw.get("block")
        source = _nonempty(raw.get("source")) or ""
        is_costume_derived = source.startswith("costume_variant:")

        if asset_id in seen:
            _issue(asset_id, "warning", "duplicate_asset", f"asset {asset_id} 在同一 bundle 内重复出现。")
        else:
            seen.add(asset_id)

        if role == "character":
            character_refs.add(asset_id)

        # Costume-variant references are derived, not direct registry
        # lookups: the style block is a variant outfit, not a registry
        # entry, so the unknown-asset / kind checks do not apply to
        # them. The identity half still must match a character entry
        # when one exists.
        if is_costume_derived:
            if source == "costume_variant:identity":
                entry = _registry_entry(registry, asset_id)
                if entry is not None and entry.get("kind") not in (None, "character"):
                    _issue(
                        asset_id,
                        "error",
                        "role_kind_mismatch",
                        f"换装身份 reference 的 role 为 character，但 registry 条目 kind 为 {entry.get('kind')!r}。",
                    )
                if (
                    entry is not None
                    and asset_id not in face_warned
                    and not _has_face_anchors(entry)
                ):
                    face_warned.add(asset_id)
                    _issue(
                        asset_id,
                        "warning",
                        "missing_face_anchors",
                        f"角色 {asset_id} 对应 registry 条目缺 face_anchors。",
                    )
            # No unknown-asset / kind check for the style half.
        else:
            entry = _registry_entry(registry, asset_id)
            if entry is None:
                _issue(asset_id, "error", "unknown_asset", f"asset {asset_id} 在 asset_registry 中不存在。")
            elif role is not None and entry.get("kind") is not None and role != entry.get("kind"):
                _issue(
                    asset_id,
                    "error",
                    "role_kind_mismatch",
                    f"reference 的 role 为 {role}，但 registry 条目 kind 为 {entry.get('kind')!r}。",
                )
            if (
                role == "character"
                and entry is not None
                and asset_id not in face_warned
                and not _has_face_anchors(entry)
            ):
                face_warned.add(asset_id)
                _issue(
                    asset_id,
                    "warning",
                    "missing_face_anchors",
                    f"角色 {asset_id} 对应 registry 条目缺 face_anchors。",
                )

        if block is None or _nonempty(block) is None or _nonempty(block) == MISSING:
            _issue(asset_id, "warning", "missing_block", f"asset {asset_id} 的描述块为[缺失]。")

    listed = bundle.get("character_ids")
    if isinstance(listed, (list, tuple)):
        for cid in listed:
            cid_str = _as_str(cid)
            if cid_str not in character_refs:
                _issue(
                    cid_str,
                    "error",
                    "missing_character_reference",
                    f"shot 列了角色 {cid_str}，但 bundle 中无对应角色 reference。",
                )

    return issues
