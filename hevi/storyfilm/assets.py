"""Cross-episode asset registry for the storyfilm line.

Design borrowed from AID Studio's role/prop/scene asset tables (MIT;
re-implemented for this line — see
``~/workspace/references/aid-studio/LEARN.md``):

  * one registry for characters and scenes, keyed inside a series by
    (kind, normalised name); normalisation is NFKC + whitespace
    collapse + ASCII lowercase, so the same name written slightly
    differently cannot split the library;
  * a character's appearance description is LOCKED at first
    registration.  Later episodes may append reference images and
    record differing descriptions as seen variants, but the locked
    text — the consistency anchor injected into image prompts — never
    drifts silently;
  * reference images accumulate and the first one stays the primary
    reference (AID's ``is_use`` selection, pointer-style);
  * a character record carries a voice binding (this line narrates
    with a single voice, so the binding lives on the hero character);
  * a scene record can bind a brushpaint template, so the zero-cost
    brush route re-renders the same place in later episodes.

Storage is a single ``assets.json`` under the library root; reference
images the pipeline reuses live under ``files/`` next to it.  No
database — this is a single-operator agent pipeline, not a
multi-user platform.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import unicodedata
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LIBRARY_FILE = "assets.json"
LIBRARY_VERSION = 1
_KIND_PREFIX = {"character": "char", "scene": "scene", "prop": "prop"}
_MAX_VARIANTS = 5


class AssetRegistryError(RuntimeError):
    """The on-disk asset library is unreadable or inconsistent."""


def normalize_name(name: str) -> str:
    """AID-style name key: NFKC + whitespace collapse + ASCII lowercase."""
    text = unicodedata.normalize("NFKC", str(name or ""))
    text = " ".join(text.split())
    return "".join(ch.lower() if ch.isascii() else ch for ch in text)


def _slug(text: str) -> str:
    norm = normalize_name(text)
    out = []
    for ch in norm:
        if ch.isalnum():
            out.append(ch)
        elif ch in " -_":
            out.append("-")
    slug = re.sub(r"-+", "-", "".join(out)).strip("-")
    if not slug:
        slug = "x" + format(zlib.crc32(norm.encode("utf-8")), "08x")
    return slug


def asset_id_for(kind: str, series: str, name: str) -> str:
    prefix = _KIND_PREFIX.get(kind, kind)
    return f"{prefix}:{_slug(series)}:{_slug(name)}"


def default_library_root() -> Path:
    env = os.getenv("HEVI_ASSET_LIBRARY", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".hevi" / "storyfilm_assets"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def empty_library() -> dict[str, Any]:
    return {"version": LIBRARY_VERSION, "assets": {}}


def load_library(root: str | Path) -> dict[str, Any]:
    path = Path(root) / LIBRARY_FILE
    if not path.exists():
        return empty_library()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AssetRegistryError(f"asset library unreadable: {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("assets"), dict):
        raise AssetRegistryError(f"asset library malformed: {path}")
    return data


def save_library(root: str | Path, library: dict[str, Any]) -> Path:
    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    path = root_path / LIBRARY_FILE
    tmp = root_path / f".{LIBRARY_FILE}.tmp"
    tmp.write_text(
        json.dumps(library, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    tmp.replace(path)
    return path


def _find(
    library: dict[str, Any], kind: str, series: str, name: str
) -> dict[str, Any] | None:
    key = normalize_name(name)
    for record in (library.get("assets") or {}).values():
        if (
            record.get("kind") == kind
            and record.get("series") == series
            and record.get("name_normalized") == key
        ):
            return record
    return None


def get_asset(library: dict[str, Any], asset_id: str) -> dict[str, Any] | None:
    return (library.get("assets") or {}).get(asset_id)


def find_character(
    library: dict[str, Any], *, series: str, name: str
) -> dict[str, Any] | None:
    return _find(library, "character", series, name)


def find_scene(
    library: dict[str, Any], *, series: str, name: str
) -> dict[str, Any] | None:
    return _find(library, "scene", series, name)


def _touch(record: dict[str, Any], episode: str | None) -> None:
    record["appearances"] = int(record.get("appearances") or 0) + 1
    if episode:
        episodes = record.setdefault("episodes", [])
        if episode not in episodes:
            episodes.append(episode)
    record["updated_at"] = _now()


def _add_reference(record: dict[str, Any], reference_image: str | None) -> bool:
    if not reference_image:
        return False
    refs = record.setdefault("reference_images", [])
    if reference_image in refs:
        return False
    refs.append(reference_image)
    return True


def _note_variant(record: dict[str, Any], field: str, value: str) -> None:
    if not value or value == record.get(field):
        return
    variants = record.setdefault("seen_variants", [])
    entry = {field: value}
    if entry not in variants:
        variants.append(entry)
        if len(variants) > _MAX_VARIANTS:
            del variants[: len(variants) - _MAX_VARIANTS]


def upsert_character(
    library: dict[str, Any],
    *,
    series: str,
    name: str,
    appearance_en: str = "",
    role: str = "",
    aliases: list[str] | None = None,
    voice: str | None = None,
    reference_image: str | None = None,
    episode: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Register or refresh a character.  Returns (record, created).

    The appearance text is locked on creation; a later, different
    description is kept as a seen variant, never as the anchor.
    """
    record = _find(library, "character", series, name)
    created = record is None
    if created:
        record = {
            "id": asset_id_for("character", series, name),
            "kind": "character",
            "series": series,
            "name": str(name).strip(),
            "name_normalized": normalize_name(name),
            "aliases": [],
            "role": role or "",
            "appearance_en": appearance_en or "",
            "appearance_locked": True,
            "seen_variants": [],
            "reference_images": [],
            "voice": voice,
            "first_seen_episode": episode,
            "episodes": [],
            "appearances": 0,
            "created_at": _now(),
            "updated_at": _now(),
        }
        library.setdefault("assets", {})[record["id"]] = record
    else:
        if role and not record.get("role"):
            record["role"] = role
        if voice and not record.get("voice"):
            record["voice"] = voice
        _note_variant(record, "appearance_en", appearance_en or "")
    for alias in aliases or []:
        if isinstance(alias, str) and alias.strip() and alias.strip() not in record["aliases"]:
            record["aliases"].append(alias.strip())
    _add_reference(record, reference_image)
    _touch(record, episode)
    return record, created


def upsert_scene(
    library: dict[str, Any],
    *,
    series: str,
    name: str,
    description_en: str = "",
    brush_template: str | None = None,
    reference_image: str | None = None,
    episode: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Register or refresh a scene asset.  Returns (record, created)."""
    record = _find(library, "scene", series, name)
    created = record is None
    if created:
        record = {
            "id": asset_id_for("scene", series, name),
            "kind": "scene",
            "series": series,
            "name": str(name).strip(),
            "name_normalized": normalize_name(name),
            "description_en": description_en or "",
            "description_locked": True,
            "seen_variants": [],
            "brush_template": brush_template,
            "reference_images": [],
            "first_seen_episode": episode,
            "episodes": [],
            "appearances": 0,
            "created_at": _now(),
            "updated_at": _now(),
        }
        library.setdefault("assets", {})[record["id"]] = record
    else:
        if brush_template and not record.get("brush_template"):
            record["brush_template"] = brush_template
        _note_variant(record, "description_en", description_en or "")
    _add_reference(record, reference_image)
    _touch(record, episode)
    return record, created


def bind_scene_template(
    library: dict[str, Any], asset_id: str, template: str
) -> bool:
    """Bind a brush template to a scene (first binding wins)."""
    record = get_asset(library, asset_id)
    if record is None or record.get("kind") != "scene" or not template:
        return False
    if record.get("brush_template"):
        return record["brush_template"] == template
    record["brush_template"] = template
    record["updated_at"] = _now()
    return True


def add_reference_image(
    library: dict[str, Any], asset_id: str, path: str
) -> bool:
    record = get_asset(library, asset_id)
    if record is None:
        return False
    changed = _add_reference(record, path)
    if changed:
        record["updated_at"] = _now()
    return changed


def store_reference_image(
    root: str | Path, record: dict[str, Any], src: str | Path, *, tag: str
) -> str:
    """Copy an image into the library's files area; return its path."""
    src_path = Path(src)
    folder = Path(root) / "files" / str(record["id"]).replace(":", "_")
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{tag}-{src_path.name}"
    if src_path.resolve() != dest.resolve():
        shutil.copyfile(src_path, dest)
    return str(dest)


def primary_reference(record: dict[str, Any]) -> str | None:
    refs = record.get("reference_images") or []
    return refs[0] if refs else None


def register_draft_assets(
    library: dict[str, Any],
    draft: dict[str, Any],
    *,
    series: str,
    episode: str,
    voice: str | None = None,
) -> dict[str, Any]:
    """Upsert every character/scene of an enriched draft.

    The hero (first character) receives the run's voice as its
    binding when it has none yet.  Returns name→record maps plus the
    created/updated id lists for the delivery ledger.
    """
    characters: dict[str, dict[str, Any]] = {}
    created: list[str] = []
    updated: list[str] = []
    for index, char in enumerate(draft.get("characters") or []):
        if not isinstance(char, dict) or not str(char.get("name") or "").strip():
            continue
        record, was_created = upsert_character(
            library,
            series=series,
            name=str(char["name"]),
            appearance_en=str(char.get("appearance_en") or ""),
            role=str(char.get("role") or ""),
            aliases=[a for a in char.get("aliases") or [] if isinstance(a, str)],
            voice=voice if index == 0 else None,
            episode=episode,
        )
        characters[record["name"]] = record
        (created if was_created else updated).append(record["id"])
    scenes: dict[str, dict[str, Any]] = {}
    for scene in draft.get("scenes") or []:
        if not isinstance(scene, dict) or not str(scene.get("name") or "").strip():
            continue
        record, was_created = upsert_scene(
            library,
            series=series,
            name=str(scene["name"]),
            description_en=str(scene.get("description_en") or ""),
            episode=episode,
        )
        scenes[record["name"]] = record
        (created if was_created else updated).append(record["id"])
    hero_id = None
    draft_characters = draft.get("characters") or []
    if draft_characters and isinstance(draft_characters[0], dict):
        hero = characters.get(str(draft_characters[0].get("name") or ""))
        hero_id = hero["id"] if hero else None
    return {
        "characters": characters,
        "scenes": scenes,
        "created_ids": created,
        "updated_ids": updated,
        "hero_id": hero_id,
    }


def resolve_cast(
    library: dict[str, Any], *, series: str, names: list[str]
) -> dict[str, dict[str, Any]]:
    """Name → character record for the names that exist in the series."""
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        record = _find(library, "character", series, name)
        if record is not None:
            out[record["name"]] = record
    return out


def library_listing(
    library: dict[str, Any], *, series: str | None = None
) -> dict[str, Any]:
    records = [
        r
        for r in (library.get("assets") or {}).values()
        if series is None or r.get("series") == series
    ]
    counts = {"character": 0, "scene": 0, "prop": 0}
    summaries = []
    for record in sorted(records, key=lambda r: (r.get("kind", ""), r.get("id", ""))):
        counts[record.get("kind", "")] = counts.get(record.get("kind", ""), 0) + 1
        summaries.append(
            {
                "id": record.get("id"),
                "kind": record.get("kind"),
                "series": record.get("series"),
                "name": record.get("name"),
                "appearances": record.get("appearances", 0),
                "reference_images": len(record.get("reference_images") or []),
                "voice": record.get("voice"),
                "brush_template": record.get("brush_template"),
            }
        )
    return {"counts": counts, "assets": summaries}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hevi.storyfilm.assets",
        description="Inspect the storyfilm cross-episode asset library.",
    )
    parser.add_argument(
        "--library",
        default="",
        help="library root (default: $HEVI_ASSET_LIBRARY or ~/.hevi/storyfilm_assets)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    list_parser = sub.add_parser("list", help="list registered assets")
    list_parser.add_argument("--series", default="", help="only this series")
    show_parser = sub.add_parser("show", help="show one asset record")
    show_parser.add_argument("asset_id")
    args = parser.parse_args(argv)

    root = Path(args.library).expanduser() if args.library else default_library_root()
    library = load_library(root)
    if args.command == "list":
        payload: Any = library_listing(library, series=args.series or None)
    else:
        record = get_asset(library, args.asset_id)
        if record is None:
            print(json.dumps({"error": f"no such asset: {args.asset_id}"}))
            return 1
        payload = record
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AssetRegistryError",
    "add_reference_image",
    "asset_id_for",
    "bind_scene_template",
    "default_library_root",
    "empty_library",
    "find_character",
    "find_scene",
    "get_asset",
    "library_listing",
    "load_library",
    "normalize_name",
    "primary_reference",
    "register_draft_assets",
    "resolve_cast",
    "save_library",
    "store_reference_image",
    "upsert_character",
    "upsert_scene",
]
