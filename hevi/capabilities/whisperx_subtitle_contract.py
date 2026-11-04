"""WhisperX word-level subtitle contract (``qa.whisperx_subtitle_contract``).

Contract gate only. The WhisperX method (``m-bain/whisperX``,
BSD-2-Clause; word-level timestamps plus speaker separation) is
intaken here as a subtitle shape contract: every segment must
carry ordered word-level timestamps inside its own bounds, and a
multi-speaker plan must declare diarization. This gate judges the
contract only and transcribes nothing. Two honest boundaries are
recorded in every report: WhisperX execution is a separate GPU
case (in hevi, WhisperX exists only as a stub comment in
``hevi/audio/omnivoice_service.py`` and must never be presented
as executed), and hevi's live ASR runs on faster-whisper
(``audio.asr_transcribe``) — the two engines must never be run
over the same audio without a written adjudication. See
OPEN_SKILLS_ATTRIBUTION.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

ASR_ENGINES: frozenset[str] = frozenset({"whisperx", "faster-whisper"})

# Live ASR in hevi runs here; WhisperX execution lives elsewhere.
LIVE_ASR_ENGINE = "faster-whisper"
LIVE_ASR_CAPABILITY = "audio.asr_transcribe"
WHISPERX_STUB_LOCATION = "hevi/audio/omnivoice_service.py"


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_whisperx_subtitle_contract(plan: Any) -> dict[str, Any]:
    """Validate a word-level subtitle plan. Returns a report; never raises.

    Verdicts are ``pass`` / ``fail`` only. Segments need ordered
    word timestamps inside their bounds; multi-speaker plans need
    a diarization declaration; the execution status must stay
    ``contract_only``.
    """
    issues: list[dict[str, Any]] = []
    segments_out: list[dict[str, Any]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [
                _issue("plan_not_object", "subtitle plan must be a JSON object")
            ],
            "segments": [],
            "live_asr_engine": LIVE_ASR_ENGINE,
            "whisperx_executed_here": False,
        }
    engine = plan.get("asr_engine")
    if not isinstance(engine, str) or engine not in ASR_ENGINES:
        issues.append(
            _issue(
                "asr_engine_undeclared",
                "plan must declare asr_engine 'whisperx' or "
                "'faster-whisper'",
            )
        )
    execution_status = plan.get("execution_status")
    if execution_status != "contract_only":
        issues.append(
            _issue(
                "execution_status_invalid",
                "execution_status must be 'contract_only': this "
                "contract transcribes nothing, and the WhisperX stub "
                "must never be presented as executed",
            )
        )
    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        issues.append(
            _issue(
                "segments_missing",
                "plan must declare a non-empty segments list",
            )
        )
        segments = segments if isinstance(segments, list) else []
    speakers_seen: set[str] = set()
    for index, segment in enumerate(segments):
        label = f"segments[{index}]"
        entry: dict[str, Any] = {"index": index, "ok": True, "issues": []}
        if not isinstance(segment, dict):
            entry["ok"] = False
            entry["issues"].append(
                _issue(f"{label}:not_object", "each segment must be an object")
            )
            segments_out.append(entry)
            continue
        start = segment.get("start")
        end = segment.get("end")
        if not _is_number(start) or not _is_number(end) or start >= end:
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:bounds_invalid",
                    "each segment needs numeric start < end",
                )
            )
            start = start if _is_number(start) else 0.0
            end = end if _is_number(end) else 0.0
        speaker = segment.get("speaker")
        if isinstance(speaker, str) and speaker:
            speakers_seen.add(speaker)
            entry["speaker"] = speaker
        words = segment.get("words")
        if not isinstance(words, list) or not words:
            entry["ok"] = False
            entry["issues"].append(
                _issue(
                    f"{label}:words_missing",
                    "each segment must declare a non-empty words list "
                    "with word-level timestamps",
                )
            )
            words = words if isinstance(words, list) else []
        previous_end: float | None = None
        for word_index, word in enumerate(words):
            word_label = f"{label}:words[{word_index}]"
            if not isinstance(word, dict):
                entry["ok"] = False
                entry["issues"].append(
                    _issue(f"{word_label}:not_object", "each word must be an object")
                )
                continue
            text = word.get("word")
            if not isinstance(text, str) or not text:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(f"{word_label}:text_missing", "each word needs text")
                )
            word_start = word.get("start")
            word_end = word.get("end")
            if (
                not _is_number(word_start)
                or not _is_number(word_end)
                or word_start >= word_end
            ):
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{word_label}:bounds_invalid",
                        "each word needs numeric start < end",
                    )
                )
                continue
            if word_start < start or word_end > end:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{word_label}:outside_segment",
                        "word timestamps must stay inside the segment bounds",
                    )
                )
            if previous_end is not None and word_start < previous_end:
                entry["ok"] = False
                entry["issues"].append(
                    _issue(
                        f"{word_label}:out_of_order",
                        "word timestamps must be ordered and "
                        "non-overlapping",
                    )
                )
            previous_end = word_end
        if entry["issues"]:
            entry["ok"] = False
        segments_out.append(entry)
        issues.extend(entry["issues"])
    declared_speakers = plan.get("speakers")
    if isinstance(declared_speakers, list):
        speakers_seen.update(
            s for s in declared_speakers if isinstance(s, str) and s
        )
    if len(speakers_seen) > 1 and plan.get("diarization_declared") is not True:
        issues.append(
            _issue(
                "diarization_undeclared",
                "a multi-speaker plan must declare diarization",
            )
        )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
        "segments": segments_out,
        "speakers": sorted(speakers_seen),
        "live_asr_engine": LIVE_ASR_ENGINE,
        "live_asr_capability": LIVE_ASR_CAPABILITY,
        "whisperx_stub_location": WHISPERX_STUB_LOCATION,
        "whisperx_executed_here": False,
    }


def _render(params: dict[str, Any], out_dir: Any, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_whisperx_subtitle_contract(params.get("plan"))
    report_path = out_dir / "whisperx_subtitle_contract.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_whisperx_subtitle_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.whisperx_subtitle_contract",
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
            layer="oskill",
            description=(
                "WhisperX subtitle contract: segments need ordered "
                "word-level timestamps inside their bounds, "
                "multi-speaker plans need a diarization declaration, "
                "and execution stays contract-only; live ASR runs on "
                "faster-whisper."
            ),
        )
    )
    return ["qa.whisperx_subtitle_contract"]


__all__ = [
    "ASR_ENGINES",
    "LIVE_ASR_ENGINE",
    "check_whisperx_subtitle_contract",
    "register_whisperx_subtitle_contract_capabilities_once",
]
