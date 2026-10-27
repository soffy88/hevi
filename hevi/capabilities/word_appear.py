"""Word appear plan with local word alignment (``explain.word_appear_plan``).

Clean-room method intake, written from the method description only.
It is distinct from ``audio.forced_align`` (which runs a cloud
forced-alignment service) and from ``edit.word_subtitle_contract``
(which owns the shared contract): this module owns the
word-appear plan itself -- when each word appears on screen --
plus a local alignment hook that either measures real word
timestamps or honestly reports pending.

Method:
* With caller-supplied word timings, words must already be
  sorted and non-overlapping; the plan emits one appear event
  per word (appear at its start, highlighted until its end) and
  groups words into lines of at most 10 words or 5 seconds.
* With no timings at all, the plan emits the same shape with
  ``appear_at_sec`` null and status pending_alignment. No timing
  is estimated, averaged or invented: a word without a measured
  time has no appear time.
* Mixed input (some words timed, some not) raises: a half-timed
  plan would silently mix measured and missing data.
* Local alignment (``align_words_local``) imports faster-whisper
  lazily. When it is not installed -- the case on this machine --
  it returns pending with reason faster_whisper_not_installed and
  no words, instead of raising or fabricating timings. When it is
  installed, it runs a real WhisperModel with word timestamps
  and returns measured words; a missing audio file raises.
* TTS is a slot, not a call. Kokoro, when requested, is probed
  by import only: present means ready, absent means pending, and
  no audio is synthesised here. ElevenLabs is excluded by prior
  decision: requesting it raises, and no ElevenLabs code path
  exists. Any key-like field in the input raises.

Failure contract: empty words, unsorted or overlapping timed
words, mixed timed/untimed words, an ElevenLabs TTS request, a
key-like field, or a missing audio file for local alignment all
raise CapabilityError (except the faster-whisper-absent case,
which is a pending result by design).
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
_TOL = 1e-3
_MAX_WORDS_PER_LINE = 10
_MAX_LINE_SEC = 5.0
_KEY_FIELDS = ("api_key", "apikey", "token", "secret", "password", "key")


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"explain.word_appear_plan: {what} must be a non-empty string")
    return value.strip()


def _reject_keys(obj: Any, what: str) -> None:
    if isinstance(obj, dict):
        for field in _KEY_FIELDS:
            if field in obj:
                raise CapabilityError(f"explain.word_appear_plan: key-like fields are not accepted ({what})")


def build_appear_plan(plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise CapabilityError("explain.word_appear_plan: plan must be a JSON object")
    _reject_keys(plan, "plan")
    words_raw = plan.get("words")
    if not isinstance(words_raw, list) or not words_raw:
        raise CapabilityError("explain.word_appear_plan: words must be a non-empty list")
    timed_flags: list[bool] = []
    words: list[dict[str, Any]] = []
    for i, w in enumerate(words_raw):
        if not isinstance(w, dict):
            raise CapabilityError(f"explain.word_appear_plan: word {i} must be a JSON object")
        text = _require_str(w.get("word"), f"word {i}.word")
        has_start = w.get("start_sec") is not None
        has_end = w.get("end_sec") is not None
        if has_start != has_end:
            raise CapabilityError(f"explain.word_appear_plan: word {i} must have both start_sec and end_sec or neither")
        timed_flags.append(has_start)
        if has_start:
            start = w.get("start_sec")
            end = w.get("end_sec")
            if not _is_num(start) or not _is_num(end):
                raise CapabilityError(f"explain.word_appear_plan: word {i} times must be numbers")
            words.append({"word": text, "start_sec": float(start), "end_sec": float(end)})
        else:
            words.append({"word": text, "start_sec": None, "end_sec": None})
    if any(timed_flags) and not all(timed_flags):
        raise CapabilityError("explain.word_appear_plan: mixed timed and untimed words are not allowed")
    timed = all(timed_flags)
    if timed:
        prev_start, prev_end = -1.0, -1.0
        for i, w in enumerate(words):
            if w["start_sec"] < 0 or w["end_sec"] <= w["start_sec"]:
                raise CapabilityError(f"explain.word_appear_plan: word {i} has an invalid time range")
            if w["start_sec"] < prev_start - _TOL:
                raise CapabilityError(f"explain.word_appear_plan: word {i} is out of order")
            if w["start_sec"] < prev_end - _TOL:
                raise CapabilityError(f"explain.word_appear_plan: word {i} overlaps the previous word")
            prev_start, prev_end = w["start_sec"], w["end_sec"]
    events = [{
        "word": w["word"],
        "appear_at_sec": w["start_sec"],
        "highlight_until_sec": w["end_sec"],
    } for w in words]
    lines: list[dict[str, Any]] = []
    if timed:
        cur: list[dict[str, Any]] = []
        for w in words:
            trial = cur + [w]
            if cur and (len(trial) > _MAX_WORDS_PER_LINE or trial[-1]["end_sec"] - trial[0]["start_sec"] > _MAX_LINE_SEC + _TOL):
                lines.append({"text": " ".join(x["word"] for x in cur), "start_sec": cur[0]["start_sec"],
                              "end_sec": cur[-1]["end_sec"], "word_count": len(cur)})
                cur = [w]
            else:
                cur = trial
        if cur:
            lines.append({"text": " ".join(x["word"] for x in cur), "start_sec": cur[0]["start_sec"],
                          "end_sec": cur[-1]["end_sec"], "word_count": len(cur)})
    else:
        lines.append({"text": " ".join(w["word"] for w in words), "start_sec": None, "end_sec": None, "word_count": len(words)})
    return {
        "capability": "explain.word_appear_plan",
        "word_count": len(words),
        "alignment_status": "aligned_supplied" if timed else "pending_alignment",
        "alignment_note": "Measured word timings supplied by the caller." if timed else (
            "No timings supplied and none measured here; appear times are null, not estimated."),
        "word_events": events,
        "lines": lines,
        "line_count": len(lines),
    }


def tts_slot(provider: str | None) -> dict[str, Any]:
    if provider is None:
        return {"provider": None, "status": "not_requested", "note": "No TTS provider was requested."}
    if provider == "elevenlabs":
        raise CapabilityError("explain.word_appear_plan: elevenlabs is excluded by prior decision and is not connected here")
    if provider == "kokoro":
        present = importlib.util.find_spec("kokoro") is not None
        return {"provider": "kokoro",
                "status": "ready" if present else "pending",
                "note": "Kokoro is installed." if present else "Kokoro is not installed on this machine; no audio is synthesised here."}
    raise CapabilityError(f"explain.word_appear_plan: unknown TTS provider {provider!r}")


def align_words_local(audio_path: str, transcript_text: str, model_size: str = "tiny", model_path: str | None = None) -> dict[str, Any]:
    """Measure word timestamps with faster-whisper, or report pending.

    Pending (not an exception) when faster-whisper is absent: that
    is the honest state on a machine without it, and the caller can
    still use build_appear_plan with supplied timings instead.
    """
    if not isinstance(audio_path, str) or not audio_path.strip():
        raise CapabilityError("explain.word_appear_plan: audio_path must be a non-empty string")
    if not isinstance(transcript_text, str) or not transcript_text.strip():
        raise CapabilityError("explain.word_appear_plan: transcript_text must be a non-empty string")
    audio = Path(audio_path)
    if not audio.is_file():
        raise CapabilityError(f"explain.word_appear_plan: audio file not found: {audio_path}")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return {"status": "pending", "reason": "faster_whisper_not_installed",
                "words": [], "note": "No timings were measured and none were fabricated."}
    kwargs: dict[str, Any] = {"device": "cpu", "compute_type": "int8"}
    if model_path is not None:
        kwargs["download_root"] = model_path
    model = WhisperModel(model_size, **kwargs)
    segments, _info = model.transcribe(str(audio), word_timestamps=True)
    words: list[dict[str, Any]] = []
    for seg in segments:
        for w in (seg.words or []):
            words.append({"word": w.word.strip(), "start_sec": round(float(w.start), 3), "end_sec": round(float(w.end), 3)})
    words = [w for w in words if w["word"]]
    return {"status": "aligned_local" if words else "pending_no_words",
            "reason": None if words else "transcription produced no word timestamps",
            "words": words, "alignment_source": "faster_whisper_local"}


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    _reject_keys(params, "params")
    result = build_appear_plan(params.get("plan"))
    result["tts_slot"] = tts_slot(params.get("tts_provider"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "word_appear_plan.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), "word_count": result["word_count"], "alignment_status": result["alignment_status"]},
    )


def register_word_appear_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="explain.word_appear_plan",
        kind="line",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "properties": {"plan": {"type": "object"}, "tts_provider": {"type": "string"}},
            "required": ["plan"],
            "additionalProperties": False,
        },
        cpu_cost_hint=0.0,
        render=_render,
        has_media_output=False,
        description=(
            "Word appear plan (clean-room): per-word appear/highlight events "
            "from supplied timings, or an honest pending plan with null times "
            "when unmeasured; local faster-whisper alignment hook and a "
            "Kokoro TTS slot. ElevenLabs is excluded, no keys accepted."
        ),
        line="explain",
    ))
    return ["explain.word_appear_plan"]


register_word_appear_capabilities_once()
