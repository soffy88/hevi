"""BGM from anidoodle's music engine: written as data, played by code or pack.

The score is always composed from a Material written here.  The voices are code
synthesized by default; when the optional sound pack is installed (S30) the
same notes are played by the recorded VCSL instruments instead, and a missing
bank silently leaves that slot on its code-built instrument, so a pack that is
absent, partial or stale never blocks a render.  The ``music.mjs check`` verdict
(key/mode, loudness, masking, stems, novelty) is returned with the file, so a
caller can refuse a bed that fails a guard.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import soundpack
from .engine import (
    AnidoodleError,
    engine_dir,
    output_root,
    run_node,
    sha256_file,
)

# Four templates that have been through the engine's own check on this machine.
# The other vocabularies are exposed by ``music.mjs vocab`` but are not silently
# enabled: a caller must compose and check one before it ships.
TEMPLATES: dict[str, dict[str, Any]] = {
    "lofiElectronic": {
        "bpm": 80,
        "mood": "calm",
        "key": "C",
        "mode": "major",
        "groove": "bounce",
        "meter": "4/4",
        "drums": True,
        "chords": {
            "Cmaj9": ("[C3 G3 B3 E4]", "C2:4"),
            "Am9": ("[A2 E3 C4 G4]", "A1:4"),
            "Fmaj9": ("[F2 C3 A3 E4]", "F1:4"),
            "G9": ("[G2 D3 B3 F4]", "G1:4"),
            "Dm9": ("[D3 A3 C4 E4]", "D2:4"),
            "G13": ("[G2 F3 A3 B3]", "G1:4"),
        },
        "progressions": [
            ["Cmaj9", "Am9", "Fmaj9", "G9"],
            ["Dm9", "G13", "Cmaj9", "Am9"],
        ],
    },
    "cinematic": {
        "bpm": 72,
        "mood": "awe",
        "key": "C",
        "mode": "major",
        "groove": "pulse",
        "meter": "4/4",
        "drums": True,
        "chords": {
            "Cmaj9": ("[C3 G3 E4 B4]", "C2:4"),
            "Am9": ("[A2 E3 C4 G4]", "A1:4"),
            "Fmaj9": ("[F2 C3 A3 E4]", "F1:4"),
            "G9": ("[G2 D3 B3 F4]", "G1:4"),
        },
        "progressions": [["Cmaj9", "Am9", "Fmaj9", "G9"]],
    },
    "folk": {
        "bpm": 96,
        "mood": "wistful",
        "key": "G",
        "mode": "major",
        "groove": "hand",
        "meter": "4/4",
        "drums": True,
        "chords": {
            "Gmaj9": ("[G2 D3 B3 F#4]", "G2:4"),
            "Em9": ("[E3 B3 G4 D5]", "E2:4"),
            "Cmaj9": ("[C3 G3 E4 B4]", "C2:4"),
            "D9": ("[D2 A2 F#3 C4]", "D2:4"),
        },
        "progressions": [["Gmaj9", "Em9", "Cmaj9", "D9"]],
    },
    "musicBox": {
        "bpm": 118,
        "mood": "curious",
        "key": "C",
        "mode": "major",
        "groove": None,
        "meter": "12/8",
        "drums": False,
        "chords": {
            "Cmaj9": ("[C5 G5 E6 B6]", "C4:4"),
            "Am9": ("[A4 E5 C6 G6]", "A4:4"),
            "Fmaj9": ("[F4 C5 A5 E6]", "F4:4"),
            "G9": ("[G4 D5 B5 F6]", "G4:4"),
        },
        "progressions": [["Cmaj9", "Am9", "Fmaj9", "G9"]],
    },
}


def _job_dir() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = output_root() / f"music-{stamp}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def _motifs(key: str, mode: str, seed: int) -> dict[str, str]:
    """One-bar cells with a rhythm and contour chosen by seed.

    A different rhythm per seed matters: the novelty gate compares melodic
    rhythm and contour as well as pitch, and a fixed "eighth, eighth, quarter"
    cell lands too close to anidoodle's own launch score.
    """

    if mode in ("minor", "aeolian", "harmonicMinor", "melodicMinor", "dorian"):
        a, b, c, d, e = ["A4", "C5", "D5", "E5", "G5"]
    else:
        a, b, c, d, e = ["G4", "A4", "B4", "D5", "E5"]
    sets = [
        {
            "m0": f"{a}:.5 {b}:.5 {c}:1 {b}:1 {a}:1",
            "m1": f"{b}:.5 {c}:.5 {d}:1 {c}:1 {b}:1",
            "m2": f"{c}:.5 {d}:.5 {e}:1 {d}:1 {c}:1",
            "m3": f"{b}:1 {c}:.5 {b}:.5 {a}:2",
            "mi": f"{b}:4",
            "mo": f"{key}5:4",
        },
        {
            "m0": f"{a}:1 {b}:1 {c}:1.5 r:.5",
            "m1": f"{b}:.5 {c}:.5 {d}:1.5 {c}:1.5",
            "m2": f"{c}:1 {d}:.5 {e}:.5 {d}:1 {c}:1",
            "m3": f"{b}:1.5 {c}:.5 {b}:1 {a}:1",
            "mi": f"{d}:4",
            "mo": f"{key}5:4",
        },
    ]
    return sets[seed % len(sets)]


def _voice_credits(text: str) -> list[str]:
    """Split the engine's voice line into credits.

    "chords (piano), lead (marimba, sparse, max shift 3 semitones)" splits on
    commas outside the parentheses.  Code-only renders say "none", which is not
    a recorded voice and must not be reported as one.
    """

    out: list[str] = []
    depth = 0
    current = ""
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            if current.strip():
                out.append(current.strip())
            current = ""
        else:
            current += ch
    if current.strip():
        out.append(current.strip())
    return [item for item in out if item.strip().lower() not in {"", "none"}]


def _material(
    style: str,
    *,
    mood: str,
    key: str,
    bpm: int,
    bars: int,
    seed: int,
    sound: str,
) -> tuple[dict[str, Any], bool]:
    """The written score: same notes whether or not the sound pack is installed."""

    tpl = TEMPLATES[style]
    use_mood = mood or tpl["mood"]
    if key and key != tpl["key"]:
        raise AnidoodleError(
            f"template {style} is written in {tpl['key']}; "
            "leave key blank or add a transposed template first"
        )
    use_key = key or tpl["key"]
    use_bpm = int(bpm or tpl["bpm"])
    progression = tpl["progressions"][seed % len(tpl["progressions"])]
    chords = {
        name: {"voicing": tpl["chords"][name][0], "bass": tpl["chords"][name][1]}
        for name in tpl["chords"]
    }
    motifs = _motifs(use_key, tpl["mode"], int(seed))

    hook_bars = max(4, bars - 4)
    no_drums = {} if tpl["drums"] else {"groove": None}
    sections = [
        {
            "kind": "intro",
            "bars": 1,
            "harmony": [progression[0]],
            "chordVel": 0.35,
            "lead": ["mi"],
            **no_drums,
        },
        {"kind": "groove", "bars": 2, "harmony": progression[:2], "lead": ["m0", "m1"], **no_drums},
        {
            "kind": "hook",
            "bars": hook_bars,
            "harmony": progression,
            "chordVel": 0.55,
            "lead": ["m0", "m1", "m2", "m3"],
            "loopLines": True,
            **no_drums,
        },
        {
            "kind": "outro",
            "bars": 1,
            "harmony": [tpl["progressions"][0][0]],
            "bass": tpl["chords"][tpl["progressions"][0][0]][1],
            "chordVel": 0.5,
            "lead": ["mo"],
            **({} if tpl["drums"] else {"groove": None}),
        },
    ]
    recorded = sound != "code"
    if recorded:
        counter = soundpack.counter_line(style)
        if counter:
            for section in sections:
                if section["kind"] in {"groove", "hook"}:
                    section["counter"] = counter
    material = {
        "style": style,
        "title": f"hevi bed ({style})",
        "seed": int(seed),
        "mood": use_mood,
        "bpm": use_bpm,
        "key": use_key,
        "mode": tpl["mode"],
        "meter": tpl["meter"],
        "tail": 2.5,
        "chords": chords,
        "motifs": motifs,
        "grooves": ({"main": {"family": tpl["groove"]}} if tpl["groove"] else {}),
        # A recorded piano under a recorded lead masks more than the code pad
        # did: the measured fix (S30) is +2 dB on the lead, -3.5 dB on the
        # chords.  Code mode keeps the S29 levels.
        "levels": (soundpack.recorded_levels(style) if recorded else {"lead": 3, "chords": 1.5}),
        "sections": sections,
    }
    if recorded:
        material["voices"] = soundpack.voices_for(style)

    return material, recorded


def _write_score(job: Path, material: dict[str, Any]) -> Path:
    score = job / "score.ts"
    compose_path = engine_dir() / "src" / "canvas-core" / "music" / "compose.ts"
    score.write_text(
        'import { composePiece, type Material } from "'
        + compose_path.as_posix()
        + '";\n'
        + "const M = "
        + json.dumps(material, ensure_ascii=False, indent=2)
        + " as Material;\nexport const score = () => composePiece(M);\n",
        encoding="utf-8",
    )
    return score


def write_score(
    *,
    style: str = "lofiElectronic",
    mood: str = "",
    key: str = "",
    bpm: int = 0,
    bars: int = 12,
    seed: int = 29,
    sound: str = "auto",
) -> dict[str, Any]:
    """Write the score module without rendering it (A/B takes, see tools/listen.mjs)."""

    if style not in TEMPLATES:
        raise AnidoodleError(f"no validated code-music template for {style}")
    if bars < 6 or bars > 96:
        raise AnidoodleError("bars must be between 6 and 96")
    if sound not in {"auto", "pack", "code"}:
        raise AnidoodleError("sound must be auto, pack or code")
    material, recorded = _material(
        style, mood=mood, key=key, bpm=bpm, bars=bars, seed=seed, sound=sound
    )
    job = _job_dir()
    score = _write_score(job, material)
    return {
        "style": style,
        "path": str(score),
        "job": str(job),
        "material": material,
        "recorded": recorded,
    }


def compose_bgm(
    *,
    style: str = "lofiElectronic",
    mood: str = "",
    key: str = "",
    bpm: int = 0,
    bars: int = 12,
    seed: int = 29,
    fmt: str = "mp3",
    sound: str = "auto",
) -> dict[str, Any]:
    """Compose, render and check a written bed.

    ``sound``: ``auto`` plays the recorded pack when it is installed and falls
    back to code instruments per slot when it is not; ``pack`` asks for it and
    says so when it had to fall back; ``code`` reproduces the S29 code-only
    arrangement exactly.
    """

    if style not in TEMPLATES:
        raise AnidoodleError(
            f"no validated code-music template for {style}; "
            f"validated: {', '.join(sorted(TEMPLATES))}"
        )
    if bars < 6 or bars > 96:
        raise AnidoodleError("bars must be between 6 and 96")
    if fmt not in {"mp3", "wav"}:
        raise AnidoodleError("fmt must be mp3 or wav")
    if sound not in {"auto", "pack", "code"}:
        raise AnidoodleError("sound must be auto, pack or code")
    if sound != "code" and style not in soundpack.RECORDED_VOICES:
        sound = "code"
    material, recorded = _material(
        style, mood=mood, key=key, bpm=bpm, bars=bars, seed=seed, sound=sound
    )
    use_mood = str(material["mood"])
    use_key = str(material["key"])
    use_bpm = int(material["bpm"])

    job = _job_dir()
    score = _write_score(job, material)
    out = job / f"bed.{fmt}"
    # auto/pack asked for recordings: with the pack absent the same score renders
    # on every slot's code instrument, and the result says so.
    env = soundpack.render_env() if recorded else {}
    if env:
        # A worker pool re-decodes every bank in each worker: 4 workers held 7 GB
        # and thrashed the host (measured 2026-11-11).  One voice at a time keeps
        # the decoded pack at ~1-2 GB; the engine's own decode is the slow part.
        env["ANIDOODLE_THREADS"] = "1"
    render = run_node(
        ["tools/music.mjs", "render", f"{score}#score", str(out)],
        timeout=1800,
        env=env or None,
    )
    if render.returncode != 0 or not out.is_file():
        raise AnidoodleError(
            "music render failed: " + ((render.stderr or render.stdout or "")[-1600:])
        )
    check = run_node(
        ["tools/music.mjs", "check", f"{score}#score"], timeout=1800, env=env or None
    )
    check_text = (check.stdout or "") + ("\n" + check.stderr if check.stderr else "")
    check_log = job / "music-check.log"
    check_log.write_text(check_text, encoding="utf-8")
    verdict = "pass" if re.search(r"CHECK PASS", check_text) else "fail"
    if "CHECK FAIL" not in check_text and "CHECK PASS" not in check_text:
        verdict = "unknown"
    lufs = re.search(r"([+-]?\d+\.\d+)\s+LUFS", check_text)
    peak = re.search(r"true peak\s+([+-]?\d+\.\d+)\s+dBTP", check_text)
    guards = re.search(r"guards\s+(.+)", check_text)
    stems = re.search(r"stems\s+(PASS|FAIL)", check_text)
    novelty = re.search(r"novelty\s+(PASS|FAIL)", check_text)
    sections_out = [
        line.strip() for line in check_text.splitlines() if line.strip().startswith("ARC ")
    ]
    voices_line = ""
    for line in (render.stdout or "").splitlines():
        if line.strip().startswith("voices"):
            voices_line = line.strip()
    recorded_voices: list[str] = []
    modeled_voices: list[str] = []
    match = re.search(r"recordings:\s*(.*?);\s*modeled:\s*(.*)$", voices_line)
    if match:
        recorded_voices = _voice_credits(match.group(1))
        modeled_voices = _voice_credits(match.group(2))
    pack = soundpack.pack_status() if recorded else {"installed": False}
    fallback_reason = ""
    if recorded and not pack.get("installed"):
        fallback_reason = "sound pack not installed; every slot used its code instrument"
    elif recorded and pack.get("installed") and not recorded_voices:
        fallback_reason = "no requested bank was used by the written parts"
    return {
        "style": style,
        "mood": use_mood,
        "key": use_key,
        "bpm": use_bpm,
        "bars": bars,
        "seed": int(seed),
        "material": material,
        "score_source": str(score),
        "format": fmt,
        "path": str(out),
        "sha256": sha256_file(out),
        "check": {
            "verdict": verdict,
            "exit_code": check.returncode,
            "lufs": float(lufs.group(1)) if lufs else None,
            "true_peak_dbtp": float(peak.group(1)) if peak else None,
            "guards": guards.group(1).strip() if guards else "",
            "stems": stems.group(1) if stems else "",
            "novelty": novelty.group(1) if novelty else "",
            "arc": sections_out[-1] if sections_out else "",
            "log": str(check_log),
            "log_tail": check_text[-3000:],
        },
        "sound": {
            "requested": sound,
            "used": "pack" if recorded_voices else "code",
            "pack_installed": bool(pack.get("installed")),
            "pack_root": pack.get("root", ""),
            "recordings": recorded_voices,
            "modeled": modeled_voices,
            "fallback_reason": fallback_reason,
        },
        "note": (
            "recorded VCSL instruments where the pack supplies them, code "
            "instruments elsewhere; same written score in both modes"
            if recorded_voices
            else "synthesized in code; no recordings"
        ),
    }
