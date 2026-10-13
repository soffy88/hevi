"""Parse SFX audio assets to extract FX template entries.

Reads from assets/audio/sfx/ directory. If a manifest.json exists,
uses that; otherwise scans for .wav files.
"""

from __future__ import annotations

import json
from pathlib import Path

from hevi.fx.registry import FXTemplate, Category, Source

_SFX_DIR = Path(__file__).resolve().parents[3] / "assets" / "audio" / "sfx"
_MANIFEST_PATH = _SFX_DIR / "library" / "manifest.json"


def _load_from_manifest() -> list[dict[str, str]]:
    """Load SFX entries from manifest.json if it exists."""
    if not _MANIFEST_PATH.exists():
        return []

    data = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = []
    for item in data.get("items", []):
        entries.append({
            "id": item.get("id", item.get("name", "")),
            "name": item.get("name", ""),
            "description": item.get("description", ""),
        })
    return entries


def _scan_wav_files() -> list[dict[str, str]]:
    """Scan SFX directory for .wav files."""
    if not _SFX_DIR.exists():
        return []

    entries = []
    for wav_file in sorted(_SFX_DIR.glob("*.wav")):
        name = wav_file.stem
        entries.append({
            "id": name,
            "name": name.capitalize(),
            "description": f"{name} sound effect",
        })
    return entries


def load_sfx() -> list[FXTemplate]:
    """Load all SFX templates.

    Returns:
        List of FXTemplate entries for all SFX audio files.
    """
    entries = _load_from_manifest()
    if not entries:
        entries = _scan_wav_files()

    templates = []
    for entry in entries:
        sfx_id = entry["id"]
        name = entry.get("name", sfx_id)
        description = entry.get("description", "")

        template_id = f"sfx:{sfx_id}"
        tags = [sfx_id, "sfx", "sound effect"]
        if description:
            tags.append(description.lower().replace(" ", "-"))

        templates.append(FXTemplate(
            id=template_id,
            name_zh=f"{name} 音效",
            category=Category.OVERLAY,
            source=Source.SFX,
            source_ref=sfx_id,
            tags=tags,
            duration_hint=None,
        ))

    return templates