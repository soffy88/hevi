"""Dialogue-rate and timeline-arithmetic gate (``qa.dialogue_timeline_gate``).

Clean-room rewrite of the *method* in ``hevi-vs-ai-manju-skills.md``
section 2 / A4: a shot's timeline is arithmetic, not vibes. The
segments must tile the declared total exactly -- no gap, no
overlap -- and the dialogue in each segment must fit the time
its segment actually has. The speaking rate is caller-given
(``chars_per_second``); this module never hard-codes a default
rate, so no source-template number becomes a hevi default. A
segment whose dialogue overflows its budget must be split into
``a`` / ``b`` sub-segments that tile the same window, each
fitting its own budget; an unsplit overflow fails. Sub-segment
windows are offsets within their parent segment (0.000 is the
parent segment's start), not absolute timeline times.

Timecodes in the evidence carry milliseconds, matching
``qa.three_layer_clip``.

This module judges plans only. It reads no media bytes and
calls no generator.
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

_EPS = 1e-6


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _fmt_time(seconds: float) -> str:
    return f"{float(seconds):.3f}"


def _check_window(
    segments: list[dict[str, Any]],
    total: float,
    rate: float,
    issues: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    prefix: str,
) -> None:
    """Tile-check one window and budget-check its segments in place."""
    cursor = 0.0
    for pos, segment in enumerate(segments):
        label = f"{prefix} segment {pos + 1}"
        start = segment.get("t_start_s")
        end = segment.get("t_end_s")
        if not _is_number(start) or not _is_number(end) or end <= start:
            issues.append(
                _issue(
                    "segment_window_invalid",
                    f"qa.dialogue_timeline_gate: {label} needs "
                    "t_start_s < t_end_s numbers",
                )
            )
            continue
        if abs(float(start) - cursor) > _EPS:
            issues.append(
                _issue(
                    "timeline_not_tiled",
                    f"qa.dialogue_timeline_gate: {label} starts at "
                    f"{_fmt_time(float(start))}s but the previous segment "
                    f"ended at {_fmt_time(cursor)}s; segments must tile "
                    "with no gap and no overlap",
                )
            )
        cursor = float(end)
        chars = segment.get("dialogue_chars")
        subsegments = segment.get("subsegments")
        if isinstance(subsegments, list) and subsegments:
            parts = [s.get("part") for s in subsegments if isinstance(s, dict)]
            if sorted(parts) != ["a", "b"] or len(subsegments) != 2:
                issues.append(
                    _issue(
                        "split_parts_invalid",
                        f"qa.dialogue_timeline_gate: {label} split must "
                        "carry exactly two sub-segments with parts 'a' "
                        "and 'b'",
                    )
                )
            sub_rows: list[dict[str, Any]] = []
            _check_window(subsegments, float(end) - float(start), rate, issues, sub_rows, label)
            sub_total = sum(
                r["dialogue_chars"] for r in sub_rows if isinstance(r.get("dialogue_chars"), int)
            )
            if isinstance(chars, int) and chars != sub_total:
                issues.append(
                    _issue(
                        "split_char_count_mismatch",
                        f"qa.dialogue_timeline_gate: {label} declares "
                        f"{chars} dialogue chars but its a/b parts sum "
                        f"to {sub_total}",
                    )
                )
            rows.append(
                {
                    "label": label,
                    "window_s": [_fmt_time(float(start)), _fmt_time(float(end))],
                    "dialogue_chars": chars,
                    "split": True,
                }
            )
            continue
        if not isinstance(chars, int) or isinstance(chars, bool) or chars < 0:
            issues.append(
                _issue(
                    "dialogue_chars_missing",
                    f"qa.dialogue_timeline_gate: {label} must declare "
                    "'dialogue_chars' as a non-negative integer",
                )
            )
            continue
        budget = (float(end) - float(start)) * rate
        rows.append(
            {
                "label": label,
                "window_s": [_fmt_time(float(start)), _fmt_time(float(end))],
                "dialogue_chars": chars,
                "budget_chars": round(budget, 3),
            }
        )
        if chars > budget + _EPS:
            issues.append(
                _issue(
                    "dialogue_overflows_budget",
                    f"qa.dialogue_timeline_gate: {label} carries {chars} "
                    f"dialogue chars in "
                    f"{_fmt_time(float(end) - float(start))}s at "
                    f"{rate:g} chars/s (budget {budget:.3f}); split it "
                    "into a/b sub-segments or lengthen the window",
                )
            )
    if abs(cursor - total) > _EPS:
        issues.append(
            _issue(
                "timeline_total_mismatch",
                f"qa.dialogue_timeline_gate: {prefix} segments end at "
                f"{_fmt_time(cursor)}s but the declared total is "
                f"{_fmt_time(total)}s; the segments must sum to the total",
            )
        )


def check_dialogue_timeline(plan: Any) -> dict[str, Any]:
    """Judge one dialogue timeline. Returns a report; never raises for a bad plan.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    rate = None
    total = None

    if not isinstance(plan, dict):
        return {
            "ok": False,
            "verdict": "fail",
            "chars_per_second": None,
            "segments": [],
            "issues": [
                _issue(
                    "plan_not_object",
                    "qa.dialogue_timeline_gate: timeline plan must be an "
                    "object",
                )
            ],
        }

    total = plan.get("total_duration_s")
    if not _is_number(total) or total <= 0:
        issues.append(
            _issue(
                "total_duration_missing",
                "qa.dialogue_timeline_gate: the plan must declare a "
                "positive 'total_duration_s'",
            )
        )
        total = 0.0
    rate = plan.get("chars_per_second")
    if not _is_number(rate) or rate <= 0:
        issues.append(
            _issue(
                "rate_undeclared",
                "qa.dialogue_timeline_gate: the plan must declare "
                "'chars_per_second' (caller-given); no default rate is "
                "assumed",
            )
        )
        rate = 0.0

    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        issues.append(
            _issue(
                "segments_missing",
                "qa.dialogue_timeline_gate: the plan needs a non-empty "
                "'segments' list in play order",
            )
        )
    elif rate > 0 and total > 0:
        _check_window(segments, float(total), float(rate), issues, rows, "timeline")

    verdict = "pass" if not issues else "fail"
    return {
        "ok": verdict == "pass",
        "verdict": verdict,
        "chars_per_second": rate if _is_number(rate) and rate > 0 else None,
        "total_duration_s": total,
        "segments": rows,
        "issues": issues,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_dialogue_timeline(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "dialogue_timeline_gate_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "ok": report["ok"],
        },
    )


def register_dialogue_timeline_gate_capabilities_once() -> list[str]:
    """Register ``qa.dialogue_timeline_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.dialogue_timeline_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Dialogue timeline gate: segments must tile the declared "
                "total exactly and each segment's dialogue must fit its "
                "window at the caller-given chars-per-second rate; an "
                "overflow must split into a/b sub-segments. No default "
                "rate is assumed. Plans are judged, never rewritten."
            ),
            line="qa",
        )
    )
    return ["qa.dialogue_timeline_gate"]


register_dialogue_timeline_gate_capabilities_once()
