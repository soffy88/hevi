"""Five-segment commentary-short template (``story.five_segment_short``).

Clean-room template for the Lu Shihao five-segment method, compressed
into a commentary short (target about 120 seconds, allowed 90-150):

1. 现场还原 -- restore the scene, big picture and key stakes.
2. 困局代入 -- push to the decision point and STOP, ask the viewer.
3. 古人怎么做 -- the point of the film, told here as COMMENTARY:
   narration + still frames / slow push-pull + subtitles. This is
   NOT a live-action performance video, and the template refuses
   any claim that it is (see the S3 delivery check).
4. 对照抽理 -- contrast the ancient choice with the viewer's, draw
   the shared principle out of this episode's facts.
5. 鉴今升华 -- land the principle in a modern situation.

Hard rules, all enforced by raising CapabilityError (never by
silently fixing the input):

* exactly five segments, in the fixed order above;
* total duration 90-150 seconds; every segment inside its quota
  duration range and its narration character range, with a
  per-segment image-count quota;
* segment 2 must carry a decision pause (2-5 seconds) AND an
  on-screen question subtitle containing "如果是你" plus either
  "你会怎么做" or "你会怎么答" (the Wang Yangming episode asks
  "如果是你，你会怎么答"); either missing is an error;
* modern elements are banned in segments 1-4: a non-empty
  ``modern_terms`` list, an ``allows_modern`` flag, or any term
  from the heuristic modern-vocabulary list in the narration
  text is an error there. Segment 5 is the only place modern
  elements are released;
* segment 3 delivery must be "commentary"; ``is_live_action``
  true (or a live-action delivery value) is an error, because a
  commentary short must not be labelled a performed film;
* no word-count / dialogue-ratio gate is applied here: the
  standing decision removed those gates, and this template
  judges by duration quotas and readability fields only.

Narration character counts count non-whitespace characters
(Chinese text has no word separators, so a word count would be
meaningless). TTS is a slot, not a call: "local" only probes for
a locally installed engine and reports pending when none is
found; "doubao" is refused (key not in place) and "elevenlabs"
is refused by prior decision. No audio is synthesised here and
no voice is fabricated.
"""

from __future__ import annotations

import importlib.util
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

_SEGMENT_NAMES = ["现场还原", "困局代入", "古人怎么做", "对照抽理", "鉴今升华"]
# index -> (min_duration, max_duration, min_chars, max_chars, min_images, max_images)
_QUOTAS = {
    1: (20.0, 36.0, 90, 150, 3, 5),
    2: (18.0, 32.0, 75, 125, 2, 5),
    3: (20.0, 36.0, 100, 150, 3, 5),
    4: (14.0, 26.0, 70, 105, 2, 3),
    5: (10.0, 22.0, 50, 85, 1, 3),
}
_TOTAL_MIN = 90.0
_TOTAL_MAX = 150.0
_TARGET_TOTAL = 120.0
_PAUSE_MIN = 2.0
_PAUSE_MAX = 5.0
_TOL = 0.5
# Heuristic modern-vocabulary scan for segments 1-4. It is a tripwire,
# not an exhaustive list: the explicit modern_terms list and the
# allows_modern flag are the authoritative declarations.
_MODERN_TERMS = (
    "手机", "互联网", "公司", "上班", "股票", "微信", "电脑", "汽车",
    "飞机", "网络", "APP", "App", "程序员", "办公室", "会议室",
    "高铁", "地铁", "电商", "直播", "短视频", "团队",
)
_KEY_FIELDS = ("api_key", "apikey", "token", "secret", "password", "key")
_DISCLAIMER = (
    "解说短片，不是演绎真片：第 3 段为旁白 + 静帧 / 推拉 + 字幕讲述"
    "关键抉择场面，无真人表演视频；静音可懂、人物会动会说话的"
    "演绎标准不适用于本片，不得谎称演绎真片。"
)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"story.five_segment_short: {what} must be a non-empty string")
    return value.strip()


def _reject_keys(obj: Any, what: str) -> None:
    if isinstance(obj, dict):
        for field in _KEY_FIELDS:
            if field in obj:
                raise CapabilityError(
                    f"story.five_segment_short: key-like fields are not accepted ({what})"
                )


def _char_count(text: str) -> int:
    return len([c for c in text if not c.isspace()])


def tts_slot(provider: str | None) -> dict[str, Any]:
    if provider is None:
        return {"provider": None, "status": "not_requested",
                "note": "No TTS provider was requested; no voice is claimed."}
    if provider == "doubao":
        raise CapabilityError(
            "story.five_segment_short: doubao TTS is excluded here (key not in place); "
            "use the local TTS route and report a pending voice instead"
        )
    if provider == "elevenlabs":
        raise CapabilityError(
            "story.five_segment_short: elevenlabs is excluded by prior decision"
        )
    if provider == "local":
        present = (
            importlib.util.find_spec("kokoro") is not None
            or importlib.util.find_spec("edge_tts") is not None
        )
        return {"provider": "local",
                "status": "ready" if present else "pending",
                "note": ("A local TTS engine was found by import probe; no audio "
                         "is synthesised here.")
                if present else
                ("No local TTS engine was found by import probe; voice is "
                 "pending, not fabricated. Route narration through hevi's "
                 "existing local TTS path at production time.")}
    raise CapabilityError(f"story.five_segment_short: unknown TTS provider {provider!r}")


def build_template(spec: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict):
        raise CapabilityError("story.five_segment_short: spec must be a JSON object")
    _reject_keys(spec, "spec")
    title = _require_str(spec.get("title"), "title")
    topic = _require_str(spec.get("topic"), "topic")
    segments_raw = spec.get("segments")
    if not isinstance(segments_raw, list) or len(segments_raw) != 5:
        raise CapabilityError(
            "story.five_segment_short: segments must be a list of exactly 5 segments"
        )
    quota_rows: list[dict[str, Any]] = []
    checked_segments: list[dict[str, Any]] = []
    total_duration = 0.0
    total_chars = 0
    total_images = 0
    for pos, seg in enumerate(segments_raw):
        index = pos + 1
        if not isinstance(seg, dict):
            raise CapabilityError(f"story.five_segment_short: segment {index} must be a JSON object")
        _reject_keys(seg, f"segment {index}")
        if seg.get("index", index) != index:
            raise CapabilityError(
                f"story.five_segment_short: segment at position {pos} must have index {index}"
            )
        name = _require_str(seg.get("name"), f"segment {index}.name")
        if name != _SEGMENT_NAMES[pos]:
            raise CapabilityError(
                f"story.five_segment_short: segment {index} must be "
                f"{_SEGMENT_NAMES[pos]!r}, got {name!r} (five-segment order is fixed)"
            )
        duration = seg.get("duration_sec")
        if not _is_num(duration):
            raise CapabilityError(f"story.five_segment_short: segment {index} duration_sec must be a number")
        duration = float(duration)
        narration = _require_str(seg.get("narration"), f"segment {index}.narration")
        chars = _char_count(narration)
        images = seg.get("image_count")
        if not isinstance(images, int) or isinstance(images, bool):
            raise CapabilityError(f"story.five_segment_short: segment {index} image_count must be an integer")
        d_min, d_max, c_min, c_max, i_min, i_max = _QUOTAS[index]
        if not (d_min - _TOL <= duration <= d_max + _TOL):
            raise CapabilityError(
                f"story.five_segment_short: segment {index} duration {duration}s outside "
                f"quota {d_min}-{d_max}s"
            )
        if not (c_min <= chars <= c_max):
            raise CapabilityError(
                f"story.five_segment_short: segment {index} narration {chars} chars outside "
                f"quota {c_min}-{c_max} chars"
            )
        if not (i_min <= images <= i_max):
            raise CapabilityError(
                f"story.five_segment_short: segment {index} image_count {images} outside "
                f"quota {i_min}-{i_max}"
            )
        modern_terms = seg.get("modern_terms", [])
        if not isinstance(modern_terms, list) or not all(isinstance(t, str) for t in modern_terms):
            raise CapabilityError(f"story.five_segment_short: segment {index} modern_terms must be a list of strings")
        if seg.get("allows_modern") and index < 5:
            raise CapabilityError(
                f"story.five_segment_short: segment {index} must not allow modern elements "
                "(only segment 5 may)"
            )
        if index < 5:
            if modern_terms:
                raise CapabilityError(
                    f"story.five_segment_short: segment {index} declares modern_terms "
                    f"{modern_terms}, but modern elements are banned in segments 1-4"
                )
            hits = [t for t in _MODERN_TERMS if t in narration]
            if hits:
                raise CapabilityError(
                    f"story.five_segment_short: segment {index} narration contains modern "
                    f"terms {hits}, banned in segments 1-4 (move modern elements to segment 5)"
                )
        checked: dict[str, Any] = {
            "index": index, "name": name, "duration_sec": duration,
            "narration_chars": chars, "image_count": images,
            "narration": narration, "modern_terms": modern_terms,
        }
        if index == 2:
            pause = seg.get("decision_pause_sec")
            if not _is_num(pause):
                raise CapabilityError(
                    "story.five_segment_short: segment 2 must carry decision_pause_sec "
                    "(missing decision pause is an error)"
                )
            pause = float(pause)
            if not (_PAUSE_MIN <= pause <= _PAUSE_MAX):
                raise CapabilityError(
                    f"story.five_segment_short: segment 2 decision_pause_sec {pause}s "
                    f"outside {_PAUSE_MIN}-{_PAUSE_MAX}s"
                )
            question = seg.get("question_subtitle")
            if not isinstance(question, str) or not question.strip():
                raise CapabilityError(
                    "story.five_segment_short: segment 2 must carry question_subtitle "
                    "(missing on-screen question is an error)"
                )
            question = question.strip()
            if "如果是你" not in question or (
                "你会怎么做" not in question and "你会怎么答" not in question
            ):
                raise CapabilityError(
                    "story.five_segment_short: segment 2 question_subtitle must ask "
                    "in the form '如果是你，你会怎么做' or '如果是你，你会怎么答' "
                    f"(got {question!r})"
                )
            checked["decision_pause_sec"] = pause
            checked["question_subtitle"] = question
            checked["speaking_sec"] = round(duration - pause, 3)
        if index == 3:
            delivery = seg.get("delivery", "commentary")
            if delivery != "commentary" or seg.get("is_live_action"):
                raise CapabilityError(
                    "story.five_segment_short: segment 3 delivery must be 'commentary' "
                    "(narration + stills / push-pull); a commentary short must not "
                    "claim live-action performance"
                )
            checked["delivery"] = "commentary"
            checked["is_live_action"] = False
        quota_rows.append({
            "segment": index, "name": name,
            "duration_quota_sec": [d_min, d_max], "duration_sec": duration,
            "narration_quota_chars": [c_min, c_max], "narration_chars": chars,
            "image_quota": [i_min, i_max], "image_count": images,
        })
        checked_segments.append(checked)
        total_duration += duration
        total_chars += chars
        total_images += images
    declared_total = spec.get("total_duration_sec")
    if declared_total is not None:
        if not _is_num(declared_total):
            raise CapabilityError("story.five_segment_short: total_duration_sec must be a number")
        if abs(float(declared_total) - total_duration) > _TOL:
            raise CapabilityError(
                f"story.five_segment_short: total_duration_sec {declared_total} does not "
                f"equal the sum of segment durations {total_duration}"
            )
    if not (_TOTAL_MIN <= total_duration <= _TOTAL_MAX):
        raise CapabilityError(
            f"story.five_segment_short: total duration {total_duration}s outside "
            f"{_TOTAL_MIN}-{_TOTAL_MAX}s (target about {_TARGET_TOTAL}s)"
        )
    return {
        "capability": "story.five_segment_short",
        "format_label": "解说短片",
        "disclaimer": _DISCLAIMER,
        "title": title, "topic": topic,
        "total_duration_sec": round(total_duration, 3),
        "target_duration_sec": _TARGET_TOTAL,
        "total_duration_range_sec": [_TOTAL_MIN, _TOTAL_MAX],
        "total_narration_chars": total_chars,
        "total_image_count": total_images,
        "quota_table": quota_rows,
        "segments": checked_segments,
        "checks": [
            "five segments in fixed order",
            "total duration within 90-150s",
            "per-segment duration, narration-char and image quotas met",
            "segment 2 decision pause + on-screen question present",
            "modern elements banned in segments 1-4, released only in segment 5",
            "segment 3 labelled commentary, not live-action performance",
        ],
        "tts_slot": tts_slot(spec.get("tts_provider")),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    _reject_keys(params, "params")
    result = build_template(params.get("spec"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "five_segment_short.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "format_label": "解说短片",
            "total_duration_sec": result["total_duration_sec"]},
    )


def register_five_segment_short_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="story.five_segment_short",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {"spec": {"type": "object"}, "tts_provider": {"type": "string"}},
            "required": ["spec"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render,
        has_media_output=False,
        description=(
            "Five-segment commentary-short template (clean-room): Lu Shihao "
            "five-segment method compressed to 90-150s with per-segment "
            "duration / narration-char / image quotas, a mandatory segment-2 "
            "decision pause + on-screen question, modern elements banned in "
            "segments 1-4, and segment 3 honestly labelled commentary, not "
            "live-action performance. Outputs a quota table and a structure "
            "validation report; no media is rendered."
        ),
        line="story",
    ))
    return ["story.five_segment_short"]


register_five_segment_short_capabilities_once()
