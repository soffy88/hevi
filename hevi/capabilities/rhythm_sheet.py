"""Rhythm-sheet capability (``motion.rhythm_sheet``).

Wraps :mod:`hevi.motion.rhythm_sheet` — validate a launch-film rhythm
sheet against ``docs/rules/launch_rhythm.md`` and, when a cut is given,
measure it against the plan — as one registry capability, following the
``motion_taste.py`` registration pattern (``kind="line"``,
``line="motion_taste"``).

This module is deliberately *not* wired into
``hevi/capabilities/__init__.py`` yet: call
:func:`register_rhythm_sheet_capabilities` (importing this module does
it once) to make ``motion.rhythm_sheet`` visible to the registry.

A failed validation is *data*, not an exception — ``qa["ok"]`` /
``qa["violations"]`` carry the outcome so pipelines decide how to
react, exactly like ``audio.earshot_gate`` / ``qa.export_gate``.  Only
an uninspectable input (a ``media_path`` that cannot be decoded) raises
``CapabilityError``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import Capability, CapabilityResult, register

RULES_VERSION = "launch-rhythm-r1"

_SHEET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "route": {"type": "string", "enum": ["continuous", "montage", "hybrid"]},
        "bpm": {"type": "number", "exclusiveMinimum": 0},
        "duration_s": {"type": "number", "exclusiveMinimum": 0},
        "stretches": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "start_s": {"type": "number", "minimum": 0},
                    "end_s": {"type": "number", "exclusiveMinimum": 0},
                    "role": {
                        "type": "string",
                        "enum": ["hook", "build", "stop", "peak", "resolve", "section"],
                    },
                    "energy": {"type": "number", "minimum": 0, "maximum": 10},
                    "events_per_bar": {"type": "number", "minimum": 0},
                    "changes": {"type": "array", "items": {"type": "string"}},
                    "music": {"type": "string"},
                    "hero": {"type": "boolean"},
                    "first_event_s": {"type": "number", "minimum": 0},
                },
                "required": ["name", "start_s", "end_s", "role",
                             "energy", "events_per_bar", "changes"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "route", "bpm", "duration_s", "stretches"],
    "additionalProperties": False,
}


def _render_rhythm_sheet(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.motion.rhythm_sheet import coerce_sheet, measure_rhythm, validate_sheet

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = coerce_sheet(params["sheet"])
    validation = validate_sheet(sheet)

    measurement: dict[str, Any] | None = None
    media_path = params.get("media_path")
    if media_path:
        # CapabilityError from an unreadable medium propagates on purpose:
        # a measurement that could not look must never pass silently.
        measurement = measure_rhythm(media_path, sheet)

    report = {
        "rules_version": RULES_VERSION,
        "rules_doc": "docs/rules/launch_rhythm.md",
        "title": sheet.title,
        "sheet": sheet.to_dict(),
        "ok": bool(validation["ok"]),
        "validation": validation,
        "measurement": measurement,
    }
    report_path = out_dir / "rhythm_sheet_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if media_path:
        from hevi.capabilities.registry import compute_sha256
        sha = compute_sha256(Path(media_path))
        mp4: str | None = str(media_path)
    else:
        sha = hashlib.sha256(report_path.read_bytes()).hexdigest()
        mp4 = None

    return CapabilityResult(
        mp4=mp4,
        duration_s=float(sheet.duration_s),
        sha256=sha,
        qa={
            "ok": bool(validation["ok"]),
            "violations": validation["violations"],
            "warnings": validation["warnings"],
            "report": str(report_path),
            "measured": measurement is not None,
            "dead_stretches": (
                measurement["dead_stretches"] if measurement else []),
            "shape_correlation": (
                measurement["shape_correlation"] if measurement else None),
            "rules_version": RULES_VERSION,
        },
    )


def register_rhythm_sheet_capabilities() -> list[str]:
    """Register ``motion.rhythm_sheet``; safe to call repeatedly."""
    register(Capability(
        name="motion.rhythm_sheet",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {
                "sheet": _SHEET_SCHEMA,
                "media_path": {"type": "string", "minLength": 1},
            },
            "required": ["sheet"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.2,
        render=_render_rhythm_sheet,
        description=(
            "发布片节奏单校验/验收（launch rhythm）：按 "
            "docs/rules/launch_rhythm.md 的硬规则校验 RhythmSheet"
            "（覆盖/钩子≤3s/中段爆发/hero/停顿/对比/死段）；"
            "给定 media_path 时再逐段实测音频 RMS 与画面运动量、"
            "比对计划能量曲线形状并检出死段。只校验不测片时不传 "
            "media_path。报告落 rhythm_sheet_report.json，"
            "qa['ok'] 为校验结论。"
        ),
        line="motion_taste",
    ))
    return ["motion.rhythm_sheet"]


# Alias following the *_once naming used by earshot_gate / export_qa.
register_rhythm_sheet_capabilities_once = register_rhythm_sheet_capabilities

register_rhythm_sheet_capabilities()

__all__ = [
    "RULES_VERSION",
    "register_rhythm_sheet_capabilities",
    "register_rhythm_sheet_capabilities_once",
]
