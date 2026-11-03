"""Karaoke vertical plan (``edit.karaoke_vertical``).

Clean-room method intake, written from the method description only.
It complements, and does not duplicate, two existing capabilities:
``edit.word_subtitle_contract`` owns the shared word-timestamp
contract, and ``edit.publish_plan`` owns platform/schedule/post
planning. This module owns only what neither provides: karaoke
per-word highlight timing laid out for a vertical frame, plus the
vertical frame spec and caption copy templates.

Method:
* Words arrive with absolute source seconds and must already be
  sorted and non-overlapping; a bad transcript raises, it is never
  silently repaired or re-timed here.
* Each word gets one highlight event: active exactly over its own
  [start_sec, end_sec) window, inactive otherwise. Lines group at
  most 10 words or 5 seconds, whichever comes first, so a renderer
  never has to guess line breaks.
* The vertical preset is 1080x1920 by default. Any caller-supplied
  size must still be 9:16 within tolerance, and subtitle margins
  must fit inside the frame; otherwise the plan raises.
* Caption templates are copy only: rendered from a supplied title
  and topic, or left as placeholders when those inputs are absent.
  Nothing here schedules or posts anything.

Failure contract: empty words, unsorted or overlapping words,
negative or end<=start times, a word past the declared source
duration, a non-9:16 frame, margins that overflow the frame, or a
non-string caption input all raise CapabilityError.
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
_MAX_WORDS_PER_LINE = 10
_MAX_LINE_SEC = 5.0


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_num(value: Any, what: str) -> float:
    if not _is_num(value):
        raise CapabilityError(f"edit.karaoke_vertical: {what} must be a number")
    return float(value)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"edit.karaoke_vertical: {what} must be a non-empty string")
    return value.strip()


def build_karaoke_vertical(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise CapabilityError("edit.karaoke_vertical: plan must be a JSON object")
    words_raw = plan.get("words")
    if not isinstance(words_raw, list) or not words_raw:
        raise CapabilityError("edit.karaoke_vertical: words must be a non-empty list")
    source_duration = plan.get("source_duration_sec")
    if source_duration is not None:
        source_duration = _require_num(source_duration, "source_duration_sec")
        if source_duration <= 0:
            raise CapabilityError("edit.karaoke_vertical: source_duration_sec must be > 0")
    words: list[dict[str, Any]] = []
    prev_start, prev_end = -1.0, -1.0
    for i, w in enumerate(words_raw):
        if not isinstance(w, dict):
            raise CapabilityError(f"edit.karaoke_vertical: word {i} must be a JSON object")
        text = _require_str(w.get("word"), f"word {i}.word")
        start = _require_num(w.get("start_sec"), f"word {i}.start_sec")
        end = _require_num(w.get("end_sec"), f"word {i}.end_sec")
        if start < 0 or end <= start:
            raise CapabilityError(f"edit.karaoke_vertical: word {i} has an invalid time range")
        if start < prev_start - _TOL:
            raise CapabilityError(f"edit.karaoke_vertical: word {i} is out of order")
        if start < prev_end - _TOL:
            raise CapabilityError(f"edit.karaoke_vertical: word {i} overlaps the previous word")
        if source_duration is not None and end > source_duration + _TOL:
            raise CapabilityError(f"edit.karaoke_vertical: word {i} ends past source_duration_sec")
        prev_start, prev_end = start, end
        words.append({"word": text, "start_sec": start, "end_sec": end})

    vert = plan.get("vertical", {})
    if not isinstance(vert, dict):
        raise CapabilityError("edit.karaoke_vertical: vertical must be a JSON object")
    width = vert.get("width", 1080)
    height = vert.get("height", 1920)
    if not _is_num(width) or not _is_num(height) or width <= 0 or height <= 0:
        raise CapabilityError("edit.karaoke_vertical: vertical width/height must be positive numbers")
    width, height = int(width), int(height)
    if abs(width / height - 9 / 16) > 0.01:
        raise CapabilityError("edit.karaoke_vertical: vertical frame must be 9:16")
    margin_side = vert.get("margin_side_px", 80)
    safe_top = vert.get("safe_top_px", 140)
    safe_bottom = vert.get("safe_bottom_px", 220)
    for name, val in (("margin_side_px", margin_side), ("safe_top_px", safe_top), ("safe_bottom_px", safe_bottom)):
        if not _is_num(val) or val < 0:
            raise CapabilityError(f"edit.karaoke_vertical: vertical {name} must be a non-negative number")
    margin_side, safe_top, safe_bottom = int(margin_side), int(safe_top), int(safe_bottom)
    if 2 * margin_side >= width or safe_top + safe_bottom >= height:
        raise CapabilityError("edit.karaoke_vertical: vertical margins overflow the frame")
    font_size = vert.get("font_size_px", 64)
    if not _is_num(font_size) or font_size <= 0:
        raise CapabilityError("edit.karaoke_vertical: vertical font_size_px must be > 0")
    band_height = 180
    band_y = height - safe_bottom - band_height
    if band_y <= safe_top:
        raise CapabilityError("edit.karaoke_vertical: subtitle band does not fit between the safe areas")
    vertical_spec = {
        "width": width,
        "height": height,
        "aspect": "9:16",
        "margin_side_px": margin_side,
        "safe_top_px": safe_top,
        "safe_bottom_px": safe_bottom,
        "font_size_px": int(font_size),
        "highlight_color": vert.get("highlight_color", "#FFD84D"),
        "base_color": vert.get("base_color", "#FFFFFF"),
        "subtitle_band": {"x": margin_side, "y": band_y, "width": width - 2 * margin_side, "height": band_height},
    }
    if not isinstance(vertical_spec["highlight_color"], str) or not isinstance(vertical_spec["base_color"], str):
        raise CapabilityError("edit.karaoke_vertical: highlight/base colors must be strings")

    word_events = [{
        "word": w["word"],
        "active_start_sec": w["start_sec"],
        "active_end_sec": w["end_sec"],
        "highlight": "active only inside its own word window; inactive otherwise",
    } for w in words]
    lines: list[dict[str, Any]] = []
    cur: list[dict[str, Any]] = []
    for w in words:
        trial = cur + [w]
        if cur and (len(trial) > _MAX_WORDS_PER_LINE or trial[-1]["end_sec"] - trial[0]["start_sec"] > _MAX_LINE_SEC + _TOL):
            lines.append({
                "text": " ".join(x["word"] for x in cur),
                "start_sec": cur[0]["start_sec"],
                "end_sec": cur[-1]["end_sec"],
                "word_count": len(cur),
                "word_events": [{
                    "word": x["word"], "active_start_sec": x["start_sec"], "active_end_sec": x["end_sec"],
                } for x in cur],
            })
            cur = [w]
        else:
            cur = trial
    if cur:
        lines.append({
            "text": " ".join(x["word"] for x in cur),
            "start_sec": cur[0]["start_sec"],
            "end_sec": cur[-1]["end_sec"],
            "word_count": len(cur),
            "word_events": [{
                "word": x["word"], "active_start_sec": x["start_sec"], "active_end_sec": x["end_sec"],
            } for x in cur],
        })

    caption_in = plan.get("caption", {})
    if not isinstance(caption_in, dict):
        raise CapabilityError("edit.karaoke_vertical: caption must be a JSON object")
    title = caption_in.get("title")
    topic = caption_in.get("topic")
    if title is not None and not isinstance(title, str):
        raise CapabilityError("edit.karaoke_vertical: caption.title must be a string")
    if topic is not None and not isinstance(topic, str):
        raise CapabilityError("edit.karaoke_vertical: caption.topic must be a string")
    ready = bool(title and title.strip() and topic and topic.strip())
    t = (title or "[title]").strip() or "[title]"
    tp = (topic or "[topic]").strip() or "[topic]"
    templates = [
        {"name": "hook", "text": f"{t} | {tp} in one minute"},
        {"name": "description", "text": f"{t} -- {tp}. Full words timed line by line in the video."},
        {"name": "hashtags", "text": f"#{tp.replace(' ', '')} #shorts #karaoke"},
    ]
    return {
        "capability": "edit.karaoke_vertical",
        "word_count": len(words),
        "first_start_sec": words[0]["start_sec"],
        "last_end_sec": words[-1]["end_sec"],
        "source_duration_sec": source_duration,
        "timestamp_basis": "absolute source seconds",
        "vertical_spec": vertical_spec,
        "word_events": word_events,
        "karaoke_lines": lines,
        "karaoke_line_count": len(lines),
        "caption_templates": templates,
        "caption_status": "ready" if ready else "template_placeholders_only",
        "publish_status": "plan_only_not_posted",
        "publish_note": "Caption templates are copy only; scheduling and posting belong to edit.publish_plan, not here.",
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = build_karaoke_vertical(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "karaoke_vertical.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "word_count": result["word_count"], "karaoke_line_count": result["karaoke_line_count"]},
    )


def register_karaoke_vertical_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="edit.karaoke_vertical",
        kind="line",
        aspects=["9:16"],
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
            "Karaoke vertical plan (clean-room): per-word highlight timing over "
            "absolute source seconds, a 9:16 frame spec with a fitted subtitle "
            "band, and caption copy templates. Copy only; never posts."
        ),
        line="edit",
    ))
    return ["edit.karaoke_vertical"]


register_karaoke_vertical_capabilities_once()
