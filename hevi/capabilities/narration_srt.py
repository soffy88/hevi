"""Shot narration timeline and subtitle (SRT) export.

Complements the edit assembly line: where ``edit_assemble`` arranges
finished clips into an EDL (fields ``shot_id``, ``dialogue`` and
``duration_sec``, plus per-shot ``sound_cues`` and subtitle lines),
this module completes the voice layer and the subtitle file. It only
produces text and a timeline -- it never mixes audio, never renders
video, and never calls any external API.

Inputs are shot dicts, in order. Each shot carries:

* ``shot_id``: required, non-empty string.
* ``duration``: required, a positive number of seconds. The
  ``edit_assemble`` spelling ``duration_sec`` is accepted as a
  fallback when ``duration`` is absent.
* ``dialogue``: optional spoken lines -- a string, or a list of
  strings / ``{"text": ...}`` dicts as in ``edit_assemble``.
* ``narration``: optional voice-over text for the shot. Note that
  ``edit_assemble`` has no ``narration`` field, so the shot dict's
  own ``narration`` field is authoritative here.

Rules that are never bent:

* A shot without narration gets ``text == ""`` and
  ``missing == True`` in the narration timeline, and no narration
  cue in the SRT. Narration is never invented to fill a gap.
* The timeline starts at 0, shots butt-join with no gaps, and the
  last shot ends exactly at the total duration.
* Inside one shot, a dialogue cue takes the first half of the shot
  and a narration cue the second half; when only one kind is
  present it takes the whole shot.
* Cue text keeps its line breaks but never contains a blank line:
  blank lines fold into a single space so the SRT block structure
  cannot break.

Any contract violation raises :class:`CapabilityError`.
"""

from __future__ import annotations

import json
import math
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

__all__ = ["build_narration", "build_srt"]


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _text_of(value: Any) -> str:
    """Normalise a dialogue/narration field to plain stripped text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                piece = item.get("text")
            else:
                piece = item
            if isinstance(piece, str) and piece.strip():
                parts.append(piece.strip())
        return "\n".join(parts)
    return ""


def _duration_of(shot: dict[str, Any]) -> float:
    """Return the shot duration in seconds, or raise CapabilityError."""
    shot_id = shot.get("shot_id")
    if "duration" in shot and shot.get("duration") is not None:
        raw = shot.get("duration")
    else:
        raw = shot.get("duration_sec")
    if raw is None or not _is_number(raw):
        raise CapabilityError(
            f"narration_srt: shot {shot_id!r} needs a numeric duration"
        )
    duration = float(raw)
    if not math.isfinite(duration) or duration <= 0:
        raise CapabilityError(
            f"narration_srt: shot {shot_id!r} duration must be > 0, "
            f"got {raw!r}"
        )
    return duration


def _timeline(shots: Any) -> list[dict[str, Any]]:
    """Validate shots and lay them end to end from 0 seconds."""
    if not isinstance(shots, (list, tuple)) or len(shots) == 0:
        raise CapabilityError("narration_srt: shots must be a non-empty list")
    timeline: list[dict[str, Any]] = []
    start = 0.0
    for shot in shots:
        if not isinstance(shot, dict):
            raise CapabilityError("narration_srt: every shot must be a dict")
        shot_id = shot.get("shot_id")
        if not isinstance(shot_id, str) or not shot_id.strip():
            raise CapabilityError("narration_srt: every shot needs a shot_id")
        duration = _duration_of(shot)
        end = start + duration
        narration = _text_of(shot.get("narration"))
        timeline.append(
            {
                "shot_id": shot_id,
                "start_sec": float(start),
                "end_sec": float(end),
                "dialogue": _text_of(shot.get("dialogue")),
                "narration": narration,
                "missing": narration == "",
            }
        )
        start = end
    return timeline


def _format_timestamp(seconds: float) -> str:
    """Format seconds as HH:MM:SS,mmm, milliseconds floored."""
    total_ms = int(math.floor(seconds * 1000 + 1e-6))
    hours, rem = divmod(total_ms, 3600 * 1000)
    minutes, rem = divmod(rem, 60 * 1000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _fold_blank_lines(text: str) -> str:
    """Keep line breaks, but fold each blank line into a single space.

    A blank line between two lines joins them with one space instead
    of a newline, so the result never contains an empty line (which
    would split one SRT cue into two blocks). Leading and trailing
    blank lines are dropped by the strip.
    """
    lines: list[str] = []
    pending_space = False
    for raw_line in text.strip().splitlines():
        stripped = raw_line.strip()
        if not stripped:
            pending_space = True
            continue
        if lines and pending_space:
            lines[-1] = lines[-1] + " " + stripped
        else:
            lines.append(stripped)
        pending_space = False
    return "\n".join(lines)


def build_narration(shots: Any) -> dict[str, Any]:
    """Build the narration timeline for ``shots``.

    Returns ``{"narration": [...]}`` where each entry is
    ``{"shot_id", "text", "start_sec", "end_sec", "missing"}``.
    ``text`` is the shot's ``narration`` field, or ``""`` with
    ``missing`` set to ``True`` when it is absent or empty; no
    narration is ever invented.
    """
    timeline = _timeline(shots)
    return {
        "narration": [
            {
                "shot_id": entry["shot_id"],
                "text": entry["narration"],
                "start_sec": entry["start_sec"],
                "end_sec": entry["end_sec"],
                "missing": entry["missing"],
            }
            for entry in timeline
        ]
    }


def build_srt(
    shots: Any,
    *,
    include_dialogue: bool = True,
    include_narration: bool = True,
) -> str:
    """Build standard SRT text for ``shots``.

    Within each shot, cues appear in order: dialogue first, then
    narration. Each cue is emitted only when its source field is
    non-empty and its kind is enabled. When both kinds are present
    in a shot, dialogue takes the first half of the shot and
    narration the second half; with only one kind present it takes
    the whole shot. Cue numbers run from 1 without gaps.
    """
    if not include_dialogue and not include_narration:
        raise CapabilityError(
            "narration_srt: include_dialogue and include_narration "
            "cannot both be False"
        )
    timeline = _timeline(shots)
    blocks: list[str] = []
    number = 0
    for entry in timeline:
        cues: list[tuple[str, float, float]] = []
        dialogue = entry["dialogue"]
        narration = entry["narration"]
        want_dialogue = include_dialogue and dialogue != ""
        want_narration = include_narration and narration != ""
        if want_dialogue and want_narration:
            mid = (entry["start_sec"] + entry["end_sec"]) / 2.0
            cues.append((dialogue, entry["start_sec"], mid))
            cues.append((narration, mid, entry["end_sec"]))
        elif want_dialogue:
            cues.append((dialogue, entry["start_sec"], entry["end_sec"]))
        elif want_narration:
            cues.append((narration, entry["start_sec"], entry["end_sec"]))
        for text, cue_start, cue_end in cues:
            folded = _fold_blank_lines(text)
            if not folded:
                continue
            number += 1
            blocks.append(
                f"{number}\n"
                f"{_format_timestamp(cue_start)} --> "
                f"{_format_timestamp(cue_end)}\n"
                f"{folded}"
            )
    if not blocks:
        return ""
    return "\n\n".join(blocks) + "\n"


_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "shots": {"type": "array"},
        "include_dialogue": {"type": "boolean", "default": True},
        "include_narration": {"type": "boolean", "default": True},
    },
    "required": ["shots"],
    "additionalProperties": False,
}


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    # Report/file capability: aspect is declared but ignored (S-03).
    # Products are the narration timeline JSON and the SRT text file.
    shots = params["shots"]
    narration = build_narration(shots)
    srt = build_srt(
        shots,
        include_dialogue=params.get("include_dialogue", True),
        include_narration=params.get("include_narration", True),
    )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    srt_path = out / "narration.srt"
    srt_path.write_text(srt, encoding="utf-8")
    payload = {**narration, "srt": srt, "srt_path": str(srt_path)}
    report = out / "narration_srt.json"
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def register_narration_srt_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="story.narration_srt",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,
            render=_render,
            description=(
                "旁白时间线＋SRT 导出：按镜次 butt-join 排布对白与旁白，"
                "无旁白的镜标 missing、绝不编造；双轨同镜时对白占前半、"
                "旁白占后半。报告／文件类能力：产物为 narration 时间线"
                " JSON 与 SRT 文本（aspects 仅声明，渲染忽略）。"
            ),
            line="narration_srt",
            has_media_output=False,
        )
    )
    return ["story.narration_srt"]


register_narration_srt_capabilities_once()
