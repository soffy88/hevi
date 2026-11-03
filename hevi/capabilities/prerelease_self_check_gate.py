"""Pre-release three-item self-check gate (``qa.prerelease_self_check_gate``).

Clean-room restatement of the tutorial method in
``hevi-vs-3d-cartoon-tutorial-6steps.md`` section 2 item 6: before a
film ships, three things are checked against evidence -- the hook
lands in the first three seconds, the subtitles never cover a face,
and the ending closes in one sentence with no trailing tail. In
hevi's caliber:

1. All three items must be present, each marked checked, each
   passed, and each carrying non-empty evidence. An unchecked item,
   a failed item, or an evidence-free pass all fail the gate.
2. When face boxes and subtitle rectangles are supplied, the gate
   cross-checks the geometry itself: any overlap between a subtitle
   rectangle and a face box fails, whatever the caller claimed.
   Coordinates are fractions of the frame (0..1).

This module judges check reports only. It renders nothing and
never takes a caller's bare word for a checked item.
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

_ITEMS = ("hook_first_3s", "subtitle_no_face_block", "ending_one_sentence")


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


def check_prerelease_self_check(report: Any) -> dict[str, Any]:
    """Judge one pre-release self-check report. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only.
    """
    issues: list[dict[str, Any]] = []
    items_out: list[dict[str, Any]] = []
    if not isinstance(report, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("report_not_object", "report must be an object")],
            "items": [],
        }
    items = report.get("items")
    if not isinstance(items, dict):
        issues.append(_issue("items_missing", "report must declare an 'items' object"))
        items = {}
    for name in _ITEMS:
        item = items.get(name)
        if not isinstance(item, dict):
            issues.append(_issue("item_missing", f"self-check item '{name}' is missing"))
            continue
        checked = item.get("checked") is True
        passed = item.get("passed") is True
        evidence = item.get("evidence")
        if not checked:
            issues.append(_issue("item_unchecked", f"self-check item '{name}' is unchecked"))
        if checked and not passed:
            issues.append(_issue("item_failed", f"self-check item '{name}' is marked failed"))
        if checked and passed and not _is_nonempty_str(evidence):
            issues.append(
                _issue(
                    "item_evidence_missing",
                    f"self-check item '{name}' passed without evidence",
                )
            )
        items_out.append({"item": name, "checked": checked, "passed": passed})
    faces = report.get("face_boxes")
    subtitles = report.get("subtitle_rects")
    if isinstance(faces, list) and isinstance(subtitles, list):
        for face in faces:
            if not isinstance(face, dict):
                continue
            for rect in subtitles:
                if isinstance(rect, dict) and _rects_overlap(face, rect):
                    issues.append(
                        _issue(
                            "subtitle_covers_face",
                            "a subtitle rectangle overlaps a face box",
                        )
                    )
                    break
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "items": items_out,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    report = check_prerelease_self_check(params.get("report"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "prerelease_self_check_gate_report.json"
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


def register_prerelease_self_check_gate_capabilities_once() -> list[str]:
    """Register ``qa.prerelease_self_check_gate`` on the unified registry (once)."""
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.prerelease_self_check_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "report": {"type": "object"},
                },
                "required": ["report"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Pre-release self-check gate: hook in the first 3 seconds, "
                "subtitles clear of faces, and a one-sentence ending, each "
                "evidenced; subtitle/face geometry is cross-checked when "
                "supplied. Reports are judged, never taken on trust."
            ),
            line="qa",
        )
    )
    return ["qa.prerelease_self_check_gate"]


register_prerelease_self_check_gate_capabilities_once()
