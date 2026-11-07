"""Unified export QA gate capability (``qa.export_gate``).

Wraps :func:`hevi.quality.export_qa.run_export_qa` — the pre-delivery
checklist (container/codecs, resolution/aspect, fps, black frames via
zerolines ``frame_stats``, loudness via the earshot ``measure`` path with
``audio.earshot_gate`` thresholds, A/V sync, ending integrity, subtitles)
— as one registry capability, following the ``earshot_gate.py``
registration pattern.

The gate always writes ``export_qa_report.json`` (same style as
``earshot_gate_report.json``); ``qa["verdict"]`` / ``qa["pass"]`` carry
the outcome so pipelines decide how to react.  A fail verdict is *data*,
not an exception — exactly like ``audio.earshot_gate``.  Only an
uninspectable input (missing file, unprobeable media) raises
``CapabilityError``: a gate that could not look never passes silently.
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

_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
_AUDIO_SUFFIXES = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus"}


def _render_export_qa(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.quality.export_qa import run_export_qa

    media_path = Path(params["media_path"])
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not media_path.is_file():
        raise CapabilityError(f"qa.export_gate: media file not found: {media_path}")

    expect: dict[str, Any] = {}
    # Explicit expect_aspect wins; otherwise the render call's aspect is
    # the caller's statement of what the export should be.
    expect_aspect = params.get("expect_aspect") or aspect
    if expect_aspect:
        expect["aspect"] = expect_aspect
    if params.get("expect_fps") is not None:
        expect["fps"] = float(params["expect_fps"])
    if params.get("expect_subtitles") is not None:
        expect["subtitles"] = bool(params["expect_subtitles"])
    for key in ("max_black_ratio", "lufs_target", "lufs_tolerance",
                "true_peak_ceiling", "av_sync_tolerance_s"):
        if params.get(key) is not None:
            expect[key] = float(params[key])

    try:
        report = run_export_qa(media_path, expect=expect)
    except FileNotFoundError as exc:
        raise CapabilityError(f"qa.export_gate: {exc}") from exc
    except Exception as exc:
        raise CapabilityError(f"qa.export_gate failed: {exc}") from exc

    if report.get("probe") is None:
        raise CapabilityError(
            f"qa.export_gate: could not probe media file: {media_path}"
        )

    report_path = out_dir / "export_qa_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    probe = report.get("probe") or {}
    duration_s = float(probe.get("duration_s") or 0.0)
    suffix = media_path.suffix.lower()
    is_audio = suffix in _AUDIO_SUFFIXES and suffix not in _VIDEO_SUFFIXES
    return CapabilityResult(
        wav=str(media_path) if is_audio else None,
        mp4=None if is_audio else str(media_path),
        duration_s=duration_s,
        sha256=compute_sha256(media_path),
        qa={
            "report": str(report_path),
            "pass": bool(report["pass"]),
            "verdict": report["verdict"],
            "failed_checks": report["failed_checks"],
            "warned_checks": report["warned_checks"],
            "checks": report["checks"],
        },
    )


def register_export_qa_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    registered: list[str] = []

    register(
        Capability(
            name="qa.export_gate",
            kind="video",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "media_path": {
                        "type": "string",
                        "description": "Local media file to gate (final export)",
                    },
                    "expect_aspect": {
                        "type": "string",
                        "pattern": "^[0-9]+:[0-9]+$",
                        "description": "Expected aspect, e.g. '9:16'; "
                        "defaults to the render call's aspect",
                    },
                    "expect_fps": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                        "maximum": 240,
                        "description": "Expected frame rate (optional)",
                    },
                    "expect_subtitles": {
                        "type": "boolean",
                        "description": "Require embedded subtitles or a "
                        "same-stem .srt sidecar",
                    },
                    "max_black_ratio": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                        "default": 0.1,
                        "description": "Black-frame ratio ceiling "
                        "(zerolines frame_stats: frame mean luma < 12)",
                    },
                    "lufs_target": {
                        "type": "number",
                        "minimum": -40.0,
                        "maximum": -5.0,
                        "default": -14.0,
                    },
                    "lufs_tolerance": {
                        "type": "number",
                        "minimum": 0.1,
                        "maximum": 10.0,
                        "default": 2.0,
                    },
                    "true_peak_ceiling": {
                        "type": "number",
                        "minimum": -10.0,
                        "maximum": 0.0,
                        "default": -1.0,
                        "description": "True-peak ceiling in dBTP",
                    },
                    "av_sync_tolerance_s": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 5.0,
                        "default": 0.5,
                    },
                },
                "required": ["media_path"],
                "additionalProperties": False,
            },
            cpu_cost_hint=1.0,
            render=_render_export_qa,
            description=(
                "Unified pre-delivery export QA gate (local, offline): "
                "container/codecs (mov/mp4 + h264 + aac), resolution/aspect, "
                "fps, black-frame ratio (zerolines frame_stats, luma < 12, "
                "max 0.1), loudness/true-peak/clipping via earshot measure "
                "with audio.earshot_gate thresholds, A/V duration sync "
                "(<= 0.5 s), ending integrity (abrupt-cut warn, last-frame "
                "black warn) and optional subtitle presence. Writes "
                "export_qa_report.json; qa['verdict'] is pass|warn|fail and "
                "qa['pass'] is verdict != fail. Use on final exports "
                "before delivery."
            ),
            line="export_qa",
        )
    )
    registered.append("qa.export_gate")

    return registered
