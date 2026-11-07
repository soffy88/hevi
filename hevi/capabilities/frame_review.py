"""Frame-return review report (``qa.frame_review``).

Clean-room method intake, written from the method description only.
It adds the layer ``edit.video_use`` does not have: video_use checks
cut points deterministically from files it renders itself, while
this module reviews a finished timeline from frames the caller
returns -- one frame, one timecode, one finding list each.

Honesty boundary, stated in every output: this capability never
looks at a frame. There is no vision model call here, no pixel is
read, and no finding is invented. The caller supplies the frames
and their findings; this module only verifies that frame index and
timecode map one-to-one, aggregates the findings, and derives a
verdict. The structured ``model_report_entry`` is an entry a vision
model can consume later -- it is not evidence that any model has
already seen the frames.

Method:
* Timecodes are HH:MM:SS:FF at the declared fps. The first frame's
  timecode must equal ``start_timecode``, and every later frame's
  frame-number offset from the start must equal its
  frame_index offset from the first frame. A mismatch, a duplicate
  index, a duplicate timecode, or an out-of-order frame raises.
* Findings carry a closed category and a closed severity. Free-text
  notes are kept verbatim, never rewritten.
* Verdict: any blocker finding fails the timeline; any major
  finding, or any frame without a source reference, needs fixing;
  otherwise it passes. Frames missing a source reference are
  counted, not silently filled in.

Failure contract: empty frames, an unparseable timecode, a frame
number at or above fps, a frame/timecode mapping mismatch,
duplicate indices or timecodes, unknown categories or severities,
or a non-positive fps all raise CapabilityError.
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
_CATEGORIES = (
    "freeze",
    "jump_cut",
    "artifact",
    "subtitle_overlap",
    "audio_pop",
    "exposure",
    "framing",
    "other",
)
_SEVERITIES = ("info", "minor", "major", "blocker")


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"qa.frame_review: {what} must be a non-empty string")
    return value.strip()


def _parse_timecode(text: Any, fps: int) -> int:
    """Return the absolute frame number for HH:MM:SS:FF, or raise."""
    if not isinstance(text, str):
        raise CapabilityError("qa.frame_review: timecode must be a string HH:MM:SS:FF")
    parts = text.strip().split(":")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        raise CapabilityError(f"qa.frame_review: unparseable timecode {text!r}")
    hh, mm, ss, ff = (int(p) for p in parts)
    if ff >= fps:
        raise CapabilityError(f"qa.frame_review: timecode frame {ff} is at or above fps {fps}")
    if mm >= 60 or ss >= 60:
        raise CapabilityError(f"qa.frame_review: timecode {text!r} has minutes/seconds out of range")
    return ((hh * 60 + mm) * 60 + ss) * fps + ff


def build_frame_review(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise CapabilityError("qa.frame_review: plan must be a JSON object")
    fps = plan.get("fps")
    if not _is_num(fps) or int(fps) != fps or fps <= 0:
        raise CapabilityError("qa.frame_review: fps must be a positive integer")
    fps = int(fps)
    start_tc = _require_str(plan.get("start_timecode"), "start_timecode")
    start_frame_no = _parse_timecode(start_tc, fps)
    frames_raw = plan.get("frames")
    if not isinstance(frames_raw, list) or not frames_raw:
        raise CapabilityError("qa.frame_review: frames must be a non-empty list")
    seen_index: set[int] = set()
    seen_tc: set[str] = set()
    table: list[dict[str, Any]] = []
    by_category: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    missing_source: list[int] = []
    first_index: int | None = None
    prev_index: int | None = None
    for i, fr in enumerate(frames_raw):
        if not isinstance(fr, dict):
            raise CapabilityError(f"qa.frame_review: frame {i} must be a JSON object")
        idx = fr.get("frame_index")
        if not isinstance(idx, int) or isinstance(idx, bool):
            raise CapabilityError(f"qa.frame_review: frame {i}.frame_index must be an integer")
        if idx in seen_index:
            raise CapabilityError(f"qa.frame_review: duplicate frame_index {idx}")
        seen_index.add(idx)
        tc = _require_str(fr.get("timecode"), f"frame {i}.timecode")
        if tc in seen_tc:
            raise CapabilityError(f"qa.frame_review: duplicate timecode {tc!r}")
        seen_tc.add(tc)
        frame_no = _parse_timecode(tc, fps)
        if first_index is None:
            first_index = idx
            if tc != start_tc:
                raise CapabilityError("qa.frame_review: first frame timecode must equal start_timecode")
        if frame_no - start_frame_no != idx - first_index:
            raise CapabilityError(
                f"qa.frame_review: frame {idx} timecode {tc} does not map to its frame_index"
            )
        if prev_index is not None and idx <= prev_index:
            raise CapabilityError("qa.frame_review: frames must be in increasing frame_index order")
        prev_index = idx
        source_ref = fr.get("source_ref")
        if source_ref is not None and (not isinstance(source_ref, str) or not source_ref.strip()):
            raise CapabilityError(f"qa.frame_review: frame {idx}.source_ref must be a non-empty string")
        if source_ref is None:
            missing_source.append(idx)
        findings_raw = fr.get("findings", [])
        if not isinstance(findings_raw, list):
            raise CapabilityError(f"qa.frame_review: frame {idx}.findings must be a list")
        findings: list[dict[str, Any]] = []
        for j, f in enumerate(findings_raw):
            if not isinstance(f, dict):
                raise CapabilityError(f"qa.frame_review: frame {idx} finding {j} must be a JSON object")
            cat = f.get("category")
            if cat not in _CATEGORIES:
                raise CapabilityError(f"qa.frame_review: frame {idx} unknown finding category {cat!r}")
            sev = f.get("severity")
            if sev not in _SEVERITIES:
                raise CapabilityError(f"qa.frame_review: frame {idx} unknown finding severity {sev!r}")
            note = _require_str(f.get("note"), f"frame {idx} finding {j}.note")
            by_category[cat] = by_category.get(cat, 0) + 1
            by_severity[sev] = by_severity.get(sev, 0) + 1
            findings.append({"category": cat, "severity": sev, "note": note})
        table.append({
            "frame_index": idx,
            "timecode": tc,
            "seconds_from_start": round((frame_no - start_frame_no) / fps, 3),
            "source_ref": source_ref,
            "findings": findings,
            "issue_count": len(findings),
        })
    total_issues = sum(len(t["findings"]) for t in table)
    if by_severity.get("blocker", 0) > 0:
        verdict = "fail"
    elif by_severity.get("major", 0) > 0 or missing_source:
        verdict = "needs_fix"
    else:
        verdict = "pass"
    top_issues: list[dict[str, Any]] = []
    for t in table:
        for f in t["findings"]:
            if f["severity"] in ("blocker", "major"):
                top_issues.append({"frame_index": t["frame_index"], "timecode": t["timecode"], **f})
    return {
        "capability": "qa.frame_review",
        "fps": fps,
        "start_timecode": start_tc,
        "frame_count": len(table),
        "first_frame_index": first_index,
        "last_frame_index": table[-1]["frame_index"],
        "frame_table": table,
        "issue_count": total_issues,
        "issues_by_category": by_category,
        "issues_by_severity": by_severity,
        "frames_missing_source_ref": missing_source,
        "verdict": verdict,
        "model_visual_review": "not_performed",
        "visual_evidence": "caller_supplied_frames_only",
        "model_report_entry": {
            "verdict": verdict,
            "frame_count": len(table),
            "issue_count": total_issues,
            "top_issues": top_issues[:5],
            "note": (
                "Structured report for a vision model to consume later; "
                "no model has viewed any frame in this capability."
            ),
        },
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = build_frame_review(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "frame_review.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "verdict": result["verdict"], "frame_count": result["frame_count"]},
    )


def register_frame_review_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="qa.frame_review",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {"plan": {"type": "object"}},
            "required": ["plan"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render,
        has_media_output=False,
        description=(
            "Frame-return review report (clean-room): caller-supplied frames "
            "verified one-to-one against timecodes, findings aggregated by "
            "category and severity, and a pass/needs_fix/fail verdict. No "
            "model views any frame here; the model entry is a structured "
            "report slot only."
        ),
        line="qa",
    ))
    return ["qa.frame_review"]


register_frame_review_capabilities_once()
