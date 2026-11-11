"""Optional anidoodle sound pack: where it is, what it holds, what it allows.

The pack is a 374 MB separate download (eight VCSL instruments, three OpenAIR
rooms); it is not in this repository and not in the image.  It is mounted
read-only into the API container (see DEPLOY.md) and every render that uses it
re-checks the manifest before playing a byte: the engine's own decoder verifies
each FLAC's sha256 against the manifest, and this module refuses a pack whose
licenses are not the ones S30 cleared for use.

Licences (read from the pack's manifest and its LICENSES.md):

* instruments - VCSL, CC0 1.0 (public domain): use, modification and
  redistribution allowed, no attribution required.
* rooms       - OpenAIR, Audio Lab, University of York, CC BY 4.0: use,
  commercial use, modification and redistribution allowed; the credit line
  below is required wherever a film made with a room is published.

Nothing in the pack is non-commercial or no-redistribution.  If a future pack
adds such an instrument, ``withheld`` names it and it is never offered.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .engine import AnidoodleError

#: Host install root; override with HEVI_ANIDOODLE_SOUNDS.
DEFAULT_ROOT = Path("/data/soffy/projects/anidoodle-sounds")

#: Licences cleared for use.  Instruments must be CC0/public domain; rooms are
#: only accepted with the CC BY 4.0 credit carried by the film.
CC0 = {"cc0-1.0", "cc0", "public-domain", "public domain"}
CC_BY = {"cc-by-4.0", "cc by 4.0"}

CREDIT = (
    "Recorded impulse responses from OpenAIR, the Open Acoustic Impulse Response "
    "library, Audio Lab, University of York "
    "(https://www.openair.hosted.york.ac.uk/), licensed CC BY 4.0."
)

#: Recorded voices per template.  Every written note of the slot it replaces is
#: inside the bank's declared range (checked by the engine at play time, and by
#: ``scripts/s30_soundcheck.py`` before a release); a bank that is missing simply
#: leaves the slot on its code-built instrument.
RECORDED_VOICES: dict[str, dict[str, dict[str, Any]]] = {
    "lofiElectronic": {
        "chords": {"inst": "piano", "role": "accomp", "gainDb": -4},
        "lead": {"inst": "marimba", "role": "melody", "gainDb": 0},
        "counter": {"inst": "vibes", "role": "color", "gainDb": -3},
    },
    "cinematic": {
        "chords": {"inst": "piano", "role": "accomp", "gainDb": -4},
        "lead": {"inst": "harp", "role": "melody", "gainDb": 0},
        "counter": {"inst": "vibes", "role": "color", "gainDb": -8},
        # A pitched drum lane: the bank's range is 37-59, so the note is pinned
        # inside it.  The code timpani reads the same opts.pitch, so both modes
        # strike the same drum.
        "kick": {"inst": "timpani", "role": "drum", "gainDb": -8, "opts": {"pitch": 38, "decay": 1.2}},
    },
    "folk": {
        "chords": {"inst": "piano", "role": "accomp", "gainDb": -5},
        "lead": {"inst": "harp", "role": "melody", "gainDb": 2},
        "counter": {"inst": "marimba", "role": "color", "gainDb": -8},
    },
    "musicBox": {
        "chords": {"inst": "piano", "role": "accomp", "gainDb": -3},
        "lead": {"inst": "bell", "role": "melody", "gainDb": 0, "opts": {"variant": "tubular"}},
        "counter": {"inst": "glockenspiel", "role": "color", "gainDb": -8},
    },
}

#: Stem levels for the recorded palettes, as dB offsets from each slot's target.
#: Only lofiElectronic is a calibrated style and its stem targets are enforced.
#: S30 measured the combo on 8 bars (seed 30): chords +7, lead +5, counter 0
#: reads chords -20.8 / lead -12.9 / counter -20.2 dB against -22 / -15.5 / -20,
#: and the masking guard keeps the melody clear in 100 % of bars (worst 3.4 dB).
#: Pushing the piano to +13 reaches the chord target but leaves the melody only
#: -1.3 dB: guards win, so chords stay at +7.  A harp on the chord slot masks
#: worse at the same level.  The other three styles carry advisory targets only,
#: and their first pass measured inside them.
RECORDED_LEVELS: dict[str, dict[str, float]] = {
    "lofiElectronic": {"lead": 5, "chords": 7},
    "cinematic": {"lead": 5, "chords": -2},
    "folk": {"lead": 5, "chords": -2},
    "musicBox": {"lead": 5, "chords": -2},
}

#: The counter line the recorded palettes need.  Same notes in both modes; a
#: missing bank leaves that slot on the code instrument (marimba->mallets,
#: vibes->mallets, glockenspiel->celesta, bell->bell).
COUNTER_LINES: dict[str, Any] = {
    "lofiElectronic": ["m2", "m3"],
    "cinematic": ["m2", "m3"],
    "folk": ["m2", "m3"],
    "musicBox": "C6:1 E6:1 G6:1 E6:1",
}


def root() -> Path:
    override = os.environ.get("HEVI_ANIDOODLE_SOUNDS") or os.environ.get("ANIDOODLE_SOUNDS")
    return Path(override).expanduser() if override else DEFAULT_ROOT


def _manifest(path: Path) -> dict[str, Any]:
    file = path / "manifest.json"
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnidoodleError(f"sound pack manifest unreadable at {file}: {exc}") from exc
    if data.get("pack") != "anidoodle-sounds" or data.get("version") != 1:
        raise AnidoodleError(f"{file} is not an anidoodle-sounds v1 manifest")
    return data


def _license_ok(kind: str, lic: str) -> bool:
    lic = (lic or "").strip().lower()
    return lic in CC0 if kind == "instrument" else lic in CC_BY


def installed() -> bool:
    try:
        _manifest(root())
    except AnidoodleError:
        return False
    return True


def _files(entry: dict[str, Any]) -> list[dict[str, Any]]:
    return list(entry.get("zones") or [])


def pack_status(*, verify: bool = False) -> dict[str, Any]:
    """What is installed, under which licence, and whether it may be used."""

    path = root()
    if not installed():
        return {
            "installed": False,
            "enabled": False,
            "root": str(path),
            "reason": "sound pack not installed; renders use code-built instruments",
            "instruments": [],
            "withheld": [],
            "rooms": [],
            "total_mb": 0.0,
            "credit": "",
        }
    manifest = _manifest(path)
    instruments: list[dict[str, Any]] = []
    withheld: list[dict[str, Any]] = []
    total = 0
    for ident, entry in sorted(manifest.get("instruments", {}).items()):
        files = _files(entry)
        size = sum(int(f.get("bytes") or 0) for f in files)
        if not size:
            size = sum(
                (path / f["file"]).stat().st_size
                for f in files
                if (path / f["file"]).is_file()
            )
        total += size
        lic = str(entry.get("license") or "")
        row = {
            "id": ident,
            "title": entry.get("title") or ident,
            "source": entry.get("source") or "",
            "license": lic,
            "zones": len(files),
            "mb": round(size / 1e6, 1),
            "range": entry.get("range"),
        }
        if _license_ok("instrument", lic):
            instruments.append(row)
        else:
            withheld.append({**row, "reason": "licence not cleared for use"})
    rooms: list[dict[str, Any]] = []
    for ident, entry in sorted(manifest.get("rooms", {}).items()):
        lic = str(entry.get("license") or "CC-BY-4.0")
        file = path / str(entry.get("file") or "")
        size = int(entry.get("bytes") or 0)
        if not size and file.is_file():
            size = file.stat().st_size
        rooms.append(
            {
                "id": ident,
                "title": entry.get("title") or ident,
                "license": lic,
                "rt60": entry.get("rt60"),
                "mb": round(size / 1e6, 2),
            }
        )
    report: dict[str, Any] = {
        "installed": True,
        "root": str(path),
        "instruments": instruments,
        "withheld": withheld,
        "rooms": rooms,
        "total_mb": round(total / 1e6, 1),
        "credit": CREDIT if rooms else "",
        "enabled": bool(instruments),
        "license_summary": {
            "instruments": "VCSL, CC0 1.0 Universal (public domain); no attribution required",
            "rooms": "OpenAIR, Audio Lab, University of York, CC BY 4.0; credit required",
        },
    }
    if verify:
        report["verify"] = verify_pack()
    return report


def verify_pack() -> dict[str, Any]:
    """Re-hash every installed FLAC against the manifest (467 files, a few seconds)."""

    path = root()
    manifest = _manifest(path)
    bad: list[str] = []
    count = 0
    for entry in manifest.get("instruments", {}).values():
        for zone in entry.get("zones", []):
            count += 1
            file = path / zone["file"]
            want = str(zone.get("sha256") or "").lower()
            if not file.is_file():
                bad.append(f"{zone['file']}: missing")
                continue
            digest = hashlib.sha256(file.read_bytes()).hexdigest()
            if digest != want:
                bad.append(f"{zone['file']}: sha256 mismatch")
    for zone in manifest.get("rooms", {}).values():
        file = path / zone["file"]
        count += 1
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != str(
            zone.get("sha256") or ""
        ).lower():
            bad.append(f"{zone['file']}: missing or mismatched")
    return {"ok": not bad, "files": count, "failures": bad[:20]}


def render_env() -> dict[str, str]:
    """The env a render needs to play recordings; empty when none are usable."""

    if not installed():
        return {}
    status = pack_status()
    if not status["enabled"]:
        return {}
    return {"ANIDOODLE_SOUNDS": str(root())}


def voices_for(template: str) -> dict[str, dict[str, Any]]:
    try:
        return dict(RECORDED_VOICES[template])
    except KeyError as exc:
        raise AnidoodleError(f"no recorded palette for {template}") from exc


def counter_line(template: str) -> Any:
    return COUNTER_LINES.get(template)


def recorded_levels(template: str) -> dict[str, float]:
    return dict(RECORDED_LEVELS.get(template, {}))
