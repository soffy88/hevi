"""Word-pop subtitle animation contract (``qa.word_pop_subtitle_contract``).

Clean-room restatement of the tutorial method in
``hevi-vs-3d-cartoon-tutorial-6steps.md`` section 2 item 6: subtitles
appear one word at a time in large type at the bottom of the frame,
never covering a face. In hevi's caliber this is a contract judged
before any render:

1. A word-level timestamp source must be declared, and the words
   must be sorted by start time with no overlap (1ms tolerance),
   following the same discipline as ``edit.word_subtitle_contract``.
2. The pop animation must be declared: bottom position, a pop scale
   that grows (scale_from < scale_to, both positive), and a pop
   window in seconds.
3. When face boxes and a subtitle zone are supplied (fractions of
   the frame, 0..1), the zone must not intersect any face box;
   a zone that covers a face fails the contract outright.

This module judges contracts only. It renders nothing; the
renderer lives in ``video.word_pop_renderer``.
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

_TOL = 1e-3


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _rects_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    try:
        ax, ay, aw, ah = (float(a[k]) for k in ("x", "y", "w", "h"))
        bx, by, bw, bh = (float(b[k]) for k in ("x", "y", "w", "h"))
    except (KeyError, TypeError, ValueError):
        return False
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def check_word_pop_subtitle_contract(contract: Any) -> dict[str, Any]:
    """Judge one word-pop subtitle contract. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    words_out: list[dict[str, Any]] = []
    if not isinstance(contract, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("contract_not_object", "contract must be an object")],
            "words": [],
        }
    if not _is_nonempty_str(contract.get("timestamp_source")):
        issues.append(
            _issue(
                "timestamp_source_missing",
                "contract must declare a word-level timestamp source",
            )
        )
    words = contract.get("words")
    if not isinstance(words, list) or not words:
        issues.append(_issue("words_missing", "contract must declare a non-empty 'words' list"))
        words = []
    previous_end: float | None = None
    for index, word in enumerate(words):
        if not isinstance(word, dict):
            issues.append(_issue("word_not_object", f"words[{index}] must be an object"))
            continue
        if not _is_nonempty_str(word.get("word")):
            issues.append(_issue("word_text_missing", f"words[{index}] must carry text"))
        start = word.get("start_s")
        end = word.get("end_s")
        if not _is_number(start) or not _is_number(end):
            issues.append(
                _issue("word_times_invalid", f"words[{index}] start_s/end_s must be numbers")
            )
            continue
        if float(end) <= float(start):
            issues.append(
                _issue("word_end_before_start", f"words[{index}] end_s must exceed start_s")
            )
        if previous_end is not None and float(start) < previous_end - _TOL:
            issues.append(
                _issue("words_overlap_or_reordered", f"words[{index}] starts before the previous word ends")
            )
        previous_end = max(previous_end or 0.0, float(end))
        words_out.append(
            {"word": word.get("word"), "start_s": float(start), "end_s": float(end)}
        )
    pop = contract.get("pop")
    if not isinstance(pop, dict):
        issues.append(_issue("pop_missing", "contract must declare the pop animation"))
        pop = {}
    if pop.get("position") != "bottom":
        issues.append(_issue("pop_position_wrong", "pop position must be 'bottom'"))
    scale_from = pop.get("scale_from")
    scale_to = pop.get("scale_to")
    if not _is_number(scale_from) or not _is_number(scale_to):
        issues.append(_issue("pop_scale_invalid", "pop scale_from/scale_to must be numbers"))
    elif not 0 < float(scale_from) < float(scale_to):
        issues.append(
            _issue("pop_scale_not_growing", "pop scale must grow: 0 < scale_from < scale_to")
        )
    pop_window = pop.get("window_s")
    if not _is_number(pop_window) or float(pop_window) <= 0:
        issues.append(_issue("pop_window_invalid", "pop window_s must be > 0"))
    zone = contract.get("subtitle_zone")
    faces = contract.get("face_boxes")
    if isinstance(zone, dict) and isinstance(faces, list):
        for face in faces:
            if isinstance(face, dict) and _rects_overlap(zone, face):
                issues.append(
                    _issue(
                        "subtitle_zone_covers_face",
                        "the subtitle zone overlaps a face box",
                    )
                )
                break
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "words": words_out,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_word_pop_subtitle_contract(params.get("contract"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "word_pop_subtitle_contract_report.json"
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


def register_word_pop_subtitle_contract_capabilities_once() -> list[str]:
    """Register ``qa.word_pop_subtitle_contract`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.word_pop_subtitle_contract",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "contract": {"type": "object"},
                },
                "required": ["contract"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Word-pop subtitle contract: declared word-level timestamp "
                "source, sorted non-overlapping words, a growing bottom "
                "pop animation, and a subtitle zone clear of faces. "
                "Contracts are judged, never rendered."
            ),
            line="qa",
        )
    )
    return ["qa.word_pop_subtitle_contract"]


register_word_pop_subtitle_contract_capabilities_once()
