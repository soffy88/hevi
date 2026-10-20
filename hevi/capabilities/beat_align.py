"""BGM beat alignment as a first-class capability (``assembly.beat_align``).

Wraps ``hevi.assembly.beat_align`` (librosa beat detection + per-seam
xfade snapping, HEVI Phase2 #37) so any product line can call it by name
instead of only via ``assemble_longvideo(bgm_beat_align=True)``.

Semantics mirror the underlying pure functions exactly -- no new policy:

* Missing audio file -> ``CapabilityError`` (never a fake success).
* Audio present but no beats detected (detection failure / silent /
  un-decodable) -> *not* an error: the report carries ``beats: []``,
  ``fallback: true`` and, when ``durations`` were given, the uniform
  ``[base_xfade_d] * (n-1)`` snapped durations -- the same fallback
  ``beat_snapped_xfade_durations`` / ``assemble_longvideo`` have always
  used. Callers can see the fallback happened from ``qa["fallback"]``.
* Beats found -> per-seam snapped durations, one per seam
  (``len == len(durations)-1`` when durations are given).

The render writes ``beat_align_report.json`` into ``out_dir`` and points
``wav`` at the source audio (same convention as ``audio.earshot_gate``:
analysis capabilities report on the input artefact, they do not
re-render it). Fully local / offline; librosa is an existing dependency.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"}


def compute_beat_alignment(
    *,
    beats: list[float],
    durations: list[float] | None,
    base_xfade_d: float = 0.5,
    max_shift: float = 0.3,
) -> dict[str, Any]:
    """Pure core: beats + shot durations -> per-seam snapped durations.

    Separated from file IO / librosa so it is unit-testable offline with
    synthetic beat lists. ``fallback`` is True exactly when ``beats`` is
    empty; in that case snapped durations (if durations were given) are
    the uniform base value, per ``beat_snapped_xfade_durations``.
    """
    from hevi.assembly.beat_align import beat_snapped_xfade_durations

    snapped: list[float] = []
    if durations:
        snapped = beat_snapped_xfade_durations(
            list(durations),
            base_xfade_d=float(base_xfade_d),
            beats=list(beats),
            max_shift=float(max_shift),
        )
    return {
        "beats": [float(b) for b in beats],
        "beat_count": len(beats),
        "snapped_durations": [float(d) for d in snapped],
        "fallback": len(beats) == 0,
    }


def _render_beat_align(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.assembly.beat_align import detect_beat_times

    audio_path = Path(params["audio_path"])
    durations = params.get("durations")
    base_xfade_d = float(params.get("base_xfade_d", 0.5))
    max_shift = float(params.get("max_shift", 0.3))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not audio_path.is_file():
        raise CapabilityError(f"assembly.beat_align: audio file not found: {audio_path}")

    beats = detect_beat_times(audio_path)
    result = compute_beat_alignment(
        beats=beats,
        durations=[float(d) for d in durations] if durations else None,
        base_xfade_d=base_xfade_d,
        max_shift=max_shift,
    )
    report = {
        "audio_path": str(audio_path),
        "durations": [float(d) for d in durations] if durations else None,
        "base_xfade_d": base_xfade_d,
        "max_shift": max_shift,
        **result,
    }
    report_path = out_dir / "beat_align_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    is_audio = audio_path.suffix.lower() in _AUDIO_SUFFIXES
    return CapabilityResult(
        wav=str(audio_path) if is_audio else None,
        mp4=None if is_audio else str(audio_path),
        duration_s=float(beats[-1]) if beats else 0.0,
        sha256=compute_sha256(audio_path),
        qa={
            "report": str(report_path),
            "beats": result["beats"],
            "beat_count": result["beat_count"],
            "snapped_durations": result["snapped_durations"],
            "fallback": result["fallback"],
        },
    )


def register_beat_align_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True

    register(
        Capability(
            name="assembly.beat_align",
            kind="audio",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "audio_path": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Local BGM/audio file to detect beats in",
                    },
                    "durations": {
                        "type": "array",
                        "items": {"type": "number", "exclusiveMinimum": 0},
                        "minItems": 1,
                        "description": "Shot durations (s); snapped durations are returned per seam (len-1)",
                    },
                    "base_xfade_d": {
                        "type": "number",
                        "minimum": 0.05,
                        "maximum": 2.0,
                        "default": 0.5,
                        "description": "Base xfade overlap duration (s) before snapping",
                    },
                    "max_shift": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "default": 0.3,
                        "description": "Max snap shift (s) around base_xfade_d",
                    },
                },
                "required": ["audio_path"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.5,
            render=_render_beat_align,
            description=(
                "BGM beat alignment (librosa, local/offline): detect beat "
                "times in an audio file and, given shot durations, return "
                "per-seam xfade durations snapped to the nearest beat "
                "(base +/- max_shift). No beats -> fallback=true with "
                "uniform base durations, never a fake snap. Writes "
                "beat_align_report.json; qa carries beats/snapped/fallback."
            ),
            line="assembly",
        )
    )
    return ["assembly.beat_align"]
