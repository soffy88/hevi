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
    fit_grid: bool = True,
    residual_tolerance_sec: float | None = None,
    rendered_beats: list[float] | None = None,
    cut_times: list[float] | None = None,
    fps: float | None = None,
) -> dict[str, Any]:
    """Pure core: beats + shot durations -> per-seam snapped durations.

    Separated from file IO / librosa so it is unit-testable offline with
    synthetic beat lists. ``fallback`` is True exactly when ``beats`` is
    empty; in that case snapped durations (if durations were given) are
    the uniform base value, per ``beat_snapped_xfade_durations``.

    With ``fit_grid`` (the default) the report also carries the
    least-squares beat-grid fit (see ``hevi.assembly.beat_align``):
    the +/-15 ms residual bar is kept, not widened, half/double
    tempo ambiguity is tested, and -- when ``rendered_beats`` are
    supplied -- the grid is re-fitted after rendering and the
    period drift is reported. ``cut_times`` + ``fps`` add the
    cut-to-beat error in seconds and frames (3-frame bar, at the
    measuring fps). A fit on fewer than 2 beats is undetermined,
    never a pass.
    """
    from hevi.assembly.beat_align import (
        beat_snapped_xfade_durations,
        cut_errors,
        fit_beat_grid,
        refit_after_render,
    )

    snapped: list[float] = []
    if durations:
        snapped = beat_snapped_xfade_durations(
            list(durations),
            base_xfade_d=float(base_xfade_d),
            beats=list(beats),
            max_shift=float(max_shift),
        )
    result: dict[str, Any] = {
        "beats": [float(b) for b in beats],
        "beat_count": len(beats),
        "snapped_durations": [float(d) for d in snapped],
        "fallback": len(beats) == 0,
    }
    if fit_grid:
        kwargs: dict[str, Any] = {}
        if residual_tolerance_sec is not None:
            kwargs["residual_tolerance_sec"] = float(residual_tolerance_sec)
        result["grid_fit"] = fit_beat_grid(list(beats), **kwargs)
        if rendered_beats is not None:
            result["grid_refit"] = refit_after_render(
                list(beats), list(rendered_beats), **kwargs)
        if cut_times is not None:
            if fps is None:
                raise CapabilityError(
                    "assembly.beat_align: cut_times needs fps to measure cut error in frames")
            result["cut_errors"] = cut_errors(list(cut_times), list(beats), float(fps))
    return result


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
        fit_grid=bool(params.get("fit_grid", True)),
        residual_tolerance_sec=(
            float(params["residual_tolerance_sec"])
            if params.get("residual_tolerance_sec") is not None else None),
        rendered_beats=(
            [float(b) for b in params["rendered_beats"]]
            if params.get("rendered_beats") is not None else None),
        cut_times=(
            [float(c) for c in params["cut_times"]]
            if params.get("cut_times") is not None else None),
        fps=float(params["fps"]) if params.get("fps") is not None else None,
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
    qa: dict[str, Any] = {
        "report": str(report_path),
        "beats": result["beats"],
        "beat_count": result["beat_count"],
        "snapped_durations": result["snapped_durations"],
        "fallback": result["fallback"],
    }
    if "grid_fit" in result:
        qa["grid_fit"] = result["grid_fit"]
    if "grid_refit" in result:
        qa["grid_refit"] = result["grid_refit"]
    if "cut_errors" in result:
        qa["cut_errors"] = result["cut_errors"]
    return CapabilityResult(
        wav=str(audio_path) if is_audio else None,
        mp4=None if is_audio else str(audio_path),
        duration_s=float(beats[-1]) if beats else 0.0,
        sha256=compute_sha256(audio_path),
        qa=qa,
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
                    "fit_grid": {
                        "type": "boolean",
                        "default": True,
                        "description": "Also fit a least-squares beat grid (15ms residual bar, half/double-tempo check)",
                    },
                    "residual_tolerance_sec": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "description": "Residual bar for the grid fit; default 0.015s, kept not widened",
                    },
                    "rendered_beats": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Beats detected in the rendered film, for a post-render refit",
                    },
                    "cut_times": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Planned cut times (s); needs fps for the 3-frame cut-error bar",
                    },
                    "fps": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "description": "Frame rate the cut error is measured at",
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
                "uniform base durations, never a fake snap. Also fits "
                "a least-squares beat grid (residual bar +/-15ms, "
                "half/double-tempo check) and, with rendered_beats, "
                "re-fits after rendering; cut_times + fps add the "
                "cut-to-beat error (3-frame bar). Writes "
                "beat_align_report.json; qa carries beats/snapped/fallback."
            ),
            line="assembly",
        )
    )
    return ["assembly.beat_align"]
