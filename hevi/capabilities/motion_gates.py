"""Motion-method gates (``edit.*`` / ``audio.*`` / ``qa.*``).

Clean-room method intake, written from the method descriptions only.
No upstream research file, sample, demo media, font, or prompt text is
copied here, and no upstream identifier is registered as a hevi asset.
All five capabilities below are plan / gate only: they validate a plan
or a gate request and return a report. None of them renders video,
runs speech recognition, or visually accepts a film. Those three jobs
stay with their own stages (renderer, an ASR provider interface, and
human visual acceptance) and are reported as pending / not-done here
when they are asked for, never faked.

Capabilities:
* ``edit.semantic_shot_list`` -- shot-by-shot orchestration table.
* ``edit.reuse_baseline_gate`` -- reuse only from a registered baseline.
* ``audio.transcript_once`` -- one transcription per source hash, cached.
* ``qa.sample_first_gate`` -- 15-20s sample before any full film.
* ``edit.caption_plan_gate`` -- voice plans must carry a caption plan.
"""

from __future__ import annotations

import json
import threading
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
_LOCK = threading.Lock()

# Canonical semantic reasons a cut may exist. Keys are the accepted
# spellings (English and Chinese); values are the canonical reason.
_TRANSITION_REASONS = {
    "deepen": "deepen",
    "深入": "deepen",
    "choose": "choose",
    "选择": "choose",
    "connect": "connect",
    "联系": "connect",
    "contrast": "contrast",
    "对比": "contrast",
    "cause": "cause",
    "因果": "cause",
    "expand": "expand",
    "展开": "expand",
    "callback": "callback",
    "呼应": "callback",
    "sequence": "sequence",
    "顺承": "sequence",
    "推进": "sequence",
}

_SAMPLE_MIN_SEC = 15.0
_SAMPLE_MAX_SEC = 20.0
_MAX_SUBTITLE_BAND_FRACTION = 0.25


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _require_num(value: Any, what: str) -> float:
    if not _is_num(value):
        raise CapabilityError(f"motion_gates: {what} must be a number")
    return float(value)


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError(f"motion_gates: {what} must be a non-empty string")
    return value.strip()


def _require_dict(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CapabilityError(f"motion_gates: {what} must be a JSON object")
    return value


def _is_title_center_card(shot: dict[str, Any]) -> bool:
    opening = shot.get("opening", shot.get("opening_template"))
    if isinstance(opening, str) and opening.strip() == "title_center_card":
        return True
    return shot.get("title_card") is True and shot.get("center_card") is True


# ---------------------------------------------------------------- 1. shot list

def build_semantic_shot_list(plan: dict[str, Any]) -> dict[str, Any]:
    plan = _require_dict(plan, "plan")
    shots_raw = plan.get("shots")
    if not isinstance(shots_raw, list) or not shots_raw:
        raise CapabilityError("edit.semantic_shot_list: shots must be a non-empty list")
    shots: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for i, raw in enumerate(shots_raw):
        shot = _require_dict(raw, f"shot {i}")
        shot_id = _require_str(shot.get("id"), f"shot {i}.id")
        if shot_id in seen_ids:
            raise CapabilityError(f"edit.semantic_shot_list: duplicate shot id {shot_id!r}")
        seen_ids.add(shot_id)
        start = _require_num(shot.get("start_sec"), f"shot {i}.start_sec")
        end = _require_num(shot.get("end_sec"), f"shot {i}.end_sec")
        if start < 0 or end <= start:
            raise CapabilityError(f"edit.semantic_shot_list: shot {i} has an invalid time range")
        meaning = _require_str(shot.get("meaning"), f"shot {i}.meaning")
        focus = shot.get("focus")
        focuses = shot.get("focuses")
        if focuses is not None:
            if not isinstance(focuses, list) or len(focuses) != 1:
                raise CapabilityError(
                    f"edit.semantic_shot_list: shot {i} must have exactly one main focus"
                )
            focus = focuses[0]
        focus = _require_str(focus, f"shot {i}.focus")
        main_effect = _require_str(shot.get("main_effect"), f"shot {i}.main_effect")
        aux = shot.get("aux_effects", [])
        if not isinstance(aux, list) or any(not isinstance(a, str) or not a.strip() for a in aux):
            raise CapabilityError(f"edit.semantic_shot_list: shot {i}.aux_effects must be a list of strings")
        aux = [a.strip() for a in aux]
        if main_effect in aux:
            raise CapabilityError(f"edit.semantic_shot_list: shot {i} repeats its main effect as an auxiliary effect")
        enter = _require_str(shot.get("enter"), f"shot {i}.enter")
        exit_ = _require_str(shot.get("exit"), f"shot {i}.exit")
        window = shot.get("readable_window_sec")
        if isinstance(window, dict):
            w_start = _require_num(window.get("start_sec"), f"shot {i}.readable_window_sec.start_sec")
            w_end = _require_num(window.get("end_sec"), f"shot {i}.readable_window_sec.end_sec")
            if w_start < start - _TOL or w_end > end + _TOL or w_end <= w_start:
                raise CapabilityError(f"edit.semantic_shot_list: shot {i} readable window lies outside the shot")
            window_out: Any = {"start_sec": w_start, "end_sec": w_end}
        else:
            window = _require_num(window, f"shot {i}.readable_window_sec")
            if window <= 0 or window > (end - start) + _TOL:
                raise CapabilityError(f"edit.semantic_shot_list: shot {i} readable_window_sec must fit inside the shot")
            window_out = window
        handoff = shot.get("handoff_to")
        if handoff is not None and (not isinstance(handoff, str) or not handoff.strip()):
            raise CapabilityError(f"edit.semantic_shot_list: shot {i}.handoff_to must be a shot id or null")
        shots.append({
            "id": shot_id, "start_sec": start, "end_sec": end,
            "meaning": meaning, "focus": focus, "main_effect": main_effect,
            "aux_effects": aux, "enter": enter, "exit": exit_,
            "readable_window_sec": window_out, "handoff_to": handoff.strip() if isinstance(handoff, str) else None,
            "title_center_card": _is_title_center_card(shot),
        })
    shots.sort(key=lambda s: s["start_sec"])
    for prev, cur in zip(shots, shots[1:]):
        if cur["start_sec"] < prev["end_sec"] - _TOL:
            raise CapabilityError("edit.semantic_shot_list: shots must not overlap")
    for shot, nxt in zip(shots, shots[1:]):
        if shot["handoff_to"] is None:
            raise CapabilityError(f"edit.semantic_shot_list: shot {shot['id']!r} is missing its handoff_to")
        if shot["handoff_to"] not in seen_ids:
            raise CapabilityError(f"edit.semantic_shot_list: shot {shot['id']!r} hands off to unknown shot {shot['handoff_to']!r}")
    title_card_count = sum(1 for s in shots if s["title_center_card"])
    if title_card_count >= 2:
        raise CapabilityError(
            "edit.semantic_shot_list: repeated title-plus-center-card opening "
            f"({title_card_count} shots); the routine may appear at most once"
        )
    transitions_raw = plan.get("transitions", [])
    if len(shots) >= 2 and not isinstance(transitions_raw, list):
        raise CapabilityError("edit.semantic_shot_list: transitions must be a list")
    transitions: list[dict[str, Any]] = []
    if isinstance(transitions_raw, list):
        for i, raw in enumerate(transitions_raw):
            tr = _require_dict(raw, f"transition {i}")
            frm = _require_str(tr.get("from_shot"), f"transition {i}.from_shot")
            to = _require_str(tr.get("to_shot"), f"transition {i}.to_shot")
            if frm not in seen_ids or to not in seen_ids:
                raise CapabilityError(f"edit.semantic_shot_list: transition {i} references an unknown shot")
            reason_raw = tr.get("reason", tr.get("semantic_reason"))
            if not isinstance(reason_raw, str):
                raise CapabilityError(f"edit.semantic_shot_list: transition {i} must carry a semantic reason")
            reason = _TRANSITION_REASONS.get(reason_raw.strip())
            if reason is None:
                raise CapabilityError(
                    f"edit.semantic_shot_list: transition {i} reason {reason_raw!r} "
                    "is not a semantic reason (deepen / choose / connect / contrast / "
                    "cause / expand / callback / sequence)"
                )
            transitions.append({"from_shot": frm, "to_shot": to, "reason": reason})
    if len(shots) >= 2:
        covered = {(t["from_shot"], t["to_shot"]) for t in transitions}
        for prev, cur in zip(shots, shots[1:]):
            if (prev["id"], cur["id"]) not in covered:
                raise CapabilityError(
                    f"edit.semantic_shot_list: no transition with a semantic reason "
                    f"covers {prev['id']!r} -> {cur['id']!r}"
                )
    return {
        "capability": "edit.semantic_shot_list",
        "verdict": "pass",
        "shot_count": len(shots),
        "transition_count": len(transitions),
        "title_center_card_count": title_card_count,
        "checks": [
            "each shot has exactly one main focus",
            "each shot has one main effect and a readable window inside the shot",
            "each non-final shot hands off to a registered shot",
            "every consecutive pair has a transition with a semantic reason",
            "the title-plus-center-card routine appears at most once",
        ],
        "shots": shots,
        "transitions": transitions,
        "render_status": "plan_only_no_render",
        "render_note": "No frames or video are produced here; a renderer consumes this plan.",
    }


# ---------------------------------------------------------------- 2. reuse gate

def check_reuse_baseline(request: dict[str, Any]) -> dict[str, Any]:
    request = _require_dict(request, "request")
    reuse = _require_dict(request.get("reuse"), "reuse")
    baseline = request.get("baseline")
    base: dict[str, Any] = {
        "capability": "edit.reuse_baseline_gate",
        "default_card_rebuild": False,
        "fallback_used": None,
        "fallback_note": "No silent fallback to a default-card rebuild exists; a blocked reuse stays blocked.",
    }
    if baseline is None:
        base.update({"verdict": "blocked", "missing": ["baseline"],
                     "unknown_inherits": [], "missing_updates": [],
                     "inherited_approved": []})
        return base
    baseline = _require_dict(baseline, "baseline")
    missing: list[str] = []
    code = baseline.get("code")
    font = baseline.get("font")
    assets = baseline.get("licensed_assets")
    if not isinstance(code, str) or not code.strip():
        missing.append("baseline.code")
    if not isinstance(font, str) or not font.strip():
        missing.append("baseline.font")
    if not isinstance(assets, list):
        missing.append("baseline.licensed_assets")
    elif not assets and baseline.get("no_licensed_assets") is not True:
        missing.append("baseline.licensed_assets")
    elif any(not isinstance(a, str) or not a.strip() for a in assets):
        missing.append("baseline.licensed_assets")
    registered = baseline.get("registered_items")
    if registered is not None:
        if not isinstance(registered, list):
            raise CapabilityError("edit.reuse_baseline_gate: baseline.registered_items must be a list")
        registered_items = [r for r in registered if isinstance(r, str)]
    else:
        registered_items = []
        if isinstance(code, str) and code.strip():
            registered_items.append(code.strip())
        if isinstance(font, str) and font.strip():
            registered_items.append(font.strip())
        if isinstance(assets, list):
            registered_items.extend(a.strip() for a in assets if isinstance(a, str) and a.strip())
    inherits = reuse.get("inherits", [])
    if not isinstance(inherits, list) or any(not isinstance(x, str) for x in inherits):
        raise CapabilityError("edit.reuse_baseline_gate: reuse.inherits must be a list of strings")
    unknown = [x for x in inherits if x not in registered_items]
    new_content = reuse.get("new_content")
    missing_updates: list[str] = []
    if new_content is None:
        missing_updates = ["new_content.semantic_events", "new_content.subtitles", "new_content.asset_map"]
    else:
        new_content = _require_dict(new_content, "reuse.new_content")
        if not isinstance(new_content.get("semantic_events"), list) or not new_content["semantic_events"]:
            missing_updates.append("new_content.semantic_events")
        if not isinstance(new_content.get("subtitles"), list) or not new_content["subtitles"]:
            missing_updates.append("new_content.subtitles")
        if not isinstance(new_content.get("asset_map"), dict) or not new_content["asset_map"]:
            missing_updates.append("new_content.asset_map")
    blocked = bool(missing or unknown or missing_updates)
    base.update({
        "verdict": "blocked" if blocked else "approved",
        "missing": missing,
        "unknown_inherits": unknown,
        "missing_updates": missing_updates,
        "inherited_approved": [] if blocked else list(inherits),
        "is_new_film": not blocked,
        "new_film_note": ("Reuse inherits only registered baseline items, and the old timeline / "
                          "old narration count as a new film only after semantic events, "
                          "subtitles and the asset map are all updated.") if not blocked else None,
    })
    return base


# ---------------------------------------------------------------- 3. transcript once

_TRANSCRIPT_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def _validate_words(words: Any, what: str) -> list[dict[str, Any]]:
    if not isinstance(words, list) or not words:
        raise CapabilityError(f"audio.transcript_once: {what} must be a non-empty list")
    out: list[dict[str, Any]] = []
    prev_start, prev_end = -1.0, -1.0
    for i, raw in enumerate(words):
        w = _require_dict(raw, f"{what} word {i}")
        text = _require_str(w.get("word"), f"{what} word {i}.word")
        start = _require_num(w.get("start_sec"), f"{what} word {i}.start_sec")
        end = _require_num(w.get("end_sec"), f"{what} word {i}.end_sec")
        if start < 0 or end <= start:
            raise CapabilityError(f"audio.transcript_once: {what} word {i} has an invalid time range")
        if start < prev_start - _TOL or start < prev_end - _TOL:
            raise CapabilityError(f"audio.transcript_once: {what} word {i} is out of order or overlapping")
        prev_start, prev_end = start, end
        out.append({"word": text, "start_sec": start, "end_sec": end})
    return out


def _transcript_gaps(entry: dict[str, Any], request: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    language = request.get("language")
    if language is not None and str(language) != entry["language"]:
        gaps.append("language_mismatch")
    words = entry["words"]
    for prev, cur in zip(words, words[1:]):
        if cur["start_sec"] < prev["start_sec"] - _TOL or cur["start_sec"] < prev["end_sec"] - _TOL:
            gaps.append("word_timing_invalid")
            break
    duration = request.get("duration_sec", entry.get("duration_sec"))
    if _is_num(duration) and float(duration) > 0:
        coverage = words[-1]["end_sec"] / float(duration) if words else 0.0
        if coverage < 0.95:
            gaps.append("coverage_gap")
    expected = request.get("expected_proper_nouns", [])
    if isinstance(expected, list) and expected:
        joined = "".join(w["word"] for w in words)
        missing = [n for n in expected if isinstance(n, str) and n and n not in joined]
        if missing:
            gaps.append("proper_noun_missing:" + ",".join(missing))
    return gaps


def request_transcript(request: dict[str, Any]) -> dict[str, Any]:
    request = _require_dict(request, "request")
    media_id = _require_str(request.get("media_id"), "media_id")
    source_hash = _require_str(request.get("source_hash"), "source_hash")
    implementation = request.get("implementation", "primary")
    if not isinstance(implementation, str) or not implementation.strip():
        raise CapabilityError("audio.transcript_once: implementation must be a non-empty string")
    implementation = implementation.strip()
    provider = request.get("provider", "faster-whisper")
    if not isinstance(provider, str) or not provider.strip():
        raise CapabilityError("audio.transcript_once: provider must be a non-empty string")
    provider = provider.strip()
    key = (media_id, source_hash)
    with _LOCK:
        entry = _TRANSCRIPT_CACHE.get(key)
        if entry is not None:
            if request.get("full_rerun") is True:
                resume_from = entry["words"][-1]["end_sec"] if entry["words"] else 0.0
                return {"capability": "audio.transcript_once", "status": "blocked",
                        "reason": "full_rerun_blocked",
                        "detail": "A cached transcript exists; a tail stall resumes from the tail, it never reruns the full media.",
                        "resume_from_sec": resume_from, "verified": entry["verified"],
                        "provider": provider, "switched_provider": None}
            if implementation != entry["implementation"]:
                return {"capability": "audio.transcript_once", "status": "blocked",
                        "reason": "second_implementation_blocked",
                        "detail": f"Transcript already exists from implementation {entry['implementation']!r}; a parallel second implementation is not started.",
                        "verified": entry["verified"], "provider": provider, "switched_provider": None}
            supplied = request.get("words", request.get("transcript_words"))
            if supplied is not None:
                try:
                    supplied_words = _validate_words(supplied, "words")
                except CapabilityError:
                    raise
                if supplied_words != entry["words"]:
                    return {"capability": "audio.transcript_once", "status": "blocked",
                            "reason": "duplicate_transcribe_blocked",
                            "detail": "Same media and source hash already have a transcript; a conflicting re-transcription is not stored.",
                            "verified": entry["verified"], "provider": provider, "switched_provider": None}
            gaps = _transcript_gaps(entry, request)
            return {"capability": "audio.transcript_once", "status": "cache_hit",
                    "verified": entry["verified"],
                    "verified_note": "A cache hit never flips verified to True; verification needs an explicit verify call.",
                    "gaps": gaps, "language": entry["language"],
                    "word_count": len(entry["words"]),
                    "provider": provider, "switched_provider": None}
        if request.get("audio_present") is False:
            return {"capability": "audio.transcript_once", "status": "pending",
                    "reason": "missing_audio", "verified": False,
                    "provider": provider, "switched_provider": None}
        if request.get("model_available") is False:
            return {"capability": "audio.transcript_once", "status": "pending",
                    "reason": "missing_model_weights",
                    "detail": "No ASR model is built into this capability and the service is not switched automatically.",
                    "verified": False, "provider": provider, "switched_provider": None}
        supplied = request.get("words", request.get("transcript_words"))
        if supplied is None:
            return {"capability": "audio.transcript_once", "status": "pending",
                    "reason": "awaiting_transcript",
                    "detail": "No transcript payload was supplied and no ASR runs here; nothing is fabricated.",
                    "verified": False, "provider": provider, "switched_provider": None}
        words = _validate_words(supplied, "words")
        language = request.get("language")
        if language is not None and (not isinstance(language, str) or not language.strip()):
            raise CapabilityError("audio.transcript_once: language must be a non-empty string")
        duration = request.get("duration_sec")
        if duration is not None:
            duration = _require_num(duration, "duration_sec")
            if duration <= 0:
                raise CapabilityError("audio.transcript_once: duration_sec must be > 0")
        entry = {"media_id": media_id, "source_hash": source_hash,
                 "implementation": implementation, "provider": provider,
                 "language": language.strip() if isinstance(language, str) else None,
                 "words": words, "duration_sec": duration, "verified": False, "reviewer": None}
        _TRANSCRIPT_CACHE[key] = entry
        return {"capability": "audio.transcript_once", "status": "stored",
                "verified": False, "word_count": len(words),
                "provider": provider, "switched_provider": None}


def verify_cached_transcript(media_id: str, source_hash: str, reviewer: str,
                             duration_sec: float | None = None) -> dict[str, Any]:
    if not isinstance(media_id, str) or not media_id.strip():
        raise CapabilityError("audio.transcript_once: media_id must be a non-empty string")
    if not isinstance(source_hash, str) or not source_hash.strip():
        raise CapabilityError("audio.transcript_once: source_hash must be a non-empty string")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise CapabilityError("audio.transcript_once: reviewer must be a non-empty string")
    with _LOCK:
        entry = _TRANSCRIPT_CACHE.get((media_id.strip(), source_hash.strip()))
        if entry is None:
            raise CapabilityError("audio.transcript_once: no cached transcript for this media and source hash")
        gaps = _transcript_gaps(entry, {"language": entry["language"],
                                        "duration_sec": duration_sec if duration_sec is not None else entry.get("duration_sec"),
                                        "expected_proper_nouns": []})
        if gaps:
            raise CapabilityError(f"audio.transcript_once: cannot verify with open gaps: {gaps}")
        entry["verified"] = True
        entry["reviewer"] = reviewer.strip()
        return {"capability": "audio.transcript_once", "status": "verified",
                "media_id": entry["media_id"], "source_hash": entry["source_hash"],
                "reviewer": entry["reviewer"], "word_count": len(entry["words"])}


def clear_transcript_cache() -> dict[str, Any]:
    with _LOCK:
        count = len(_TRANSCRIPT_CACHE)
        _TRANSCRIPT_CACHE.clear()
    return {"cleared": count}


# ---------------------------------------------------------------- 4. sample first

def check_sample_first(plan: dict[str, Any]) -> dict[str, Any]:
    plan = _require_dict(plan, "plan")
    if plan.get("explicit_full_film") is True:
        return {"capability": "qa.sample_first_gate", "mode": "full_film_explicit",
                "verdict": "approved_explicit_bypass", "sample_required": False,
                "can_expand_to_full": True, "sample_duration_sec": None,
                "bypass_reason": "User explicitly requested the full film directly.",
                "tech_passed": None, "user_accepted": None}
    explicit_duration = plan.get("explicit_duration_request_sec")
    if explicit_duration is not None:
        explicit_duration = _require_num(explicit_duration, "explicit_duration_request_sec")
        if explicit_duration <= 0:
            raise CapabilityError("qa.sample_first_gate: explicit_duration_request_sec must be > 0")
        return {"capability": "qa.sample_first_gate", "mode": "explicit_duration",
                "verdict": "approved_explicit_bypass", "sample_required": False,
                "can_expand_to_full": True, "sample_duration_sec": explicit_duration,
                "bypass_reason": "User explicitly requested a different length.",
                "tech_passed": None, "user_accepted": None}
    sample = plan.get("sample")
    base: dict[str, Any] = {"capability": "qa.sample_first_gate", "mode": "sample_first",
                            "required_window_sec": [_SAMPLE_MIN_SEC, _SAMPLE_MAX_SEC]}
    if sample is None:
        base.update({"verdict": "sample_required", "sample_duration_sec": None,
                     "can_expand_to_full": False, "tech_passed": False, "user_accepted": False,
                     "note": "Default delivery is a 15-20s sample carrying the complete meaning."})
        return base
    sample = _require_dict(sample, "sample")
    duration = _require_num(sample.get("duration_sec"), "sample.duration_sec")
    if duration <= 0:
        raise CapabilityError("qa.sample_first_gate: sample.duration_sec must be > 0")
    tech = sample.get("tech_checks_passed")
    user = sample.get("user_accepted")
    if tech is not None and not isinstance(tech, bool):
        raise CapabilityError("qa.sample_first_gate: sample.tech_checks_passed must be a boolean")
    if user is not None and not isinstance(user, bool):
        raise CapabilityError("qa.sample_first_gate: sample.user_accepted must be a boolean")
    tech = bool(tech)
    user_accepted = user is True
    expand = plan.get("expand_to_full") is True
    base.update({"sample_duration_sec": duration, "tech_passed": tech, "user_accepted": user_accepted})
    if duration < _SAMPLE_MIN_SEC - _TOL or duration > _SAMPLE_MAX_SEC + _TOL:
        base.update({"verdict": "blocked", "reason": "duration_out_of_window",
                     "detail": "Sample length is outside 15-20s and no explicit other length was requested; it is not silently clamped.",
                     "can_expand_to_full": False})
        return base
    if sample.get("covers_full_meaning") is not True:
        base.update({"verdict": "blocked", "reason": "meaning_incomplete",
                     "detail": "The sample must carry the complete meaning, not a fragment.",
                     "can_expand_to_full": False})
        return base
    if not tech:
        base.update({"verdict": "blocked", "reason": "tech_not_passed",
                     "can_expand_to_full": False})
        return base
    if not user_accepted:
        base.update({"verdict": "awaiting_user_acceptance",
                     "reason": "tech_passed_not_user_accepted",
                     "detail": "Technical checks passing never counts as user acceptance.",
                     "can_expand_to_full": False})
        if expand:
            base["verdict"] = "blocked"
            base["reason"] = "expand_blocked_sample_not_accepted"
        return base
    base.update({"verdict": "approved", "can_expand_to_full": True,
                 "expanded_to_full": expand})
    return base


# ---------------------------------------------------------------- 5. caption plan

def _rect(value: Any, what: str) -> dict[str, float] | None:
    if value is None:
        return None
    rect = _require_dict(value, what)
    out: dict[str, float] = {}
    for key in ("x", "y", "w", "h"):
        out[key] = _require_num(rect.get(key), f"{what}.{key}")
    if out["w"] <= 0 or out["h"] <= 0:
        raise CapabilityError(f"edit.caption_plan_gate: {what} must have positive w/h")
    return out


def _rects_overlap(a: dict[str, float], b: dict[str, float]) -> bool:
    return (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
            and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])


def check_caption_plan(plan: dict[str, Any]) -> dict[str, Any]:
    plan = _require_dict(plan, "plan")
    if "has_voice" in plan:
        has_voice = plan.get("has_voice")
        if not isinstance(has_voice, bool):
            raise CapabilityError("edit.caption_plan_gate: has_voice must be a boolean")
    elif "voice" in plan:
        voice = plan.get("voice")
        has_voice = bool(voice) if not isinstance(voice, bool) else voice
    elif isinstance(plan.get("voice_plan"), dict):
        has_voice = bool(plan["voice_plan"])
    else:
        has_voice = False
    declined = plan.get("captions_explicitly_declined") is True
    captions = plan.get("captions")
    if captions is not None:
        captions = _require_dict(captions, "captions")
    base: dict[str, Any] = {"capability": "edit.caption_plan_gate", "has_voice": has_voice}
    if not has_voice:
        enabled = bool(captions.get("enabled")) if captions else False
        base.update({"verdict": "approved", "captions_enabled": enabled, "missing": [],
                     "violations": [], "main_visual_safe": True,
                     "note": "No voice plan, so captions are optional."})
        if captions and enabled:
            return _check_caption_geometry(plan, captions, base)
        return base
    if captions is None:
        if declined:
            base.update({"verdict": "approved", "captions_enabled": False, "missing": [],
                         "violations": [], "main_visual_safe": True,
                         "declined_explicit": True})
            return base
        base.update({"verdict": "blocked", "captions_enabled": False,
                     "missing": ["captions"],
                     "violations": ["voice plan without a caption plan"],
                     "main_visual_safe": False})
        return base
    enabled = captions.get("enabled")
    if enabled is not True and enabled is not False:
        raise CapabilityError("edit.caption_plan_gate: captions.enabled must be a boolean")
    if enabled is False:
        if declined:
            base.update({"verdict": "approved", "captions_enabled": False, "missing": [],
                         "violations": [], "main_visual_safe": True, "declined_explicit": True})
            return base
        base.update({"verdict": "blocked", "captions_enabled": False, "missing": [],
                     "violations": ["captions.enabled=false without the user explicitly declining captions"],
                     "main_visual_safe": False})
        return base
    base.update({"captions_enabled": True})
    return _check_caption_geometry(plan, captions, base)


def _check_caption_geometry(plan: dict[str, Any], captions: dict[str, Any],
                            base: dict[str, Any]) -> dict[str, Any]:
    violations: list[str] = []
    position = captions.get("position", "bottom")
    if not isinstance(position, str) or not position.strip():
        raise CapabilityError("edit.caption_plan_gate: captions.position must be a non-empty string")
    position = position.strip()
    if position == "center":
        violations.append("subtitle position center would cover the main visual; use a band outside the main visual")
    frame_h = captions.get("frame_height_px")
    band_h = captions.get("band_height_px")
    if frame_h is not None and band_h is not None:
        frame_h = _require_num(frame_h, "captions.frame_height_px")
        band_h = _require_num(band_h, "captions.band_height_px")
        if frame_h <= 0 or band_h <= 0:
            raise CapabilityError("edit.caption_plan_gate: captions frame/band heights must be > 0")
        if band_h > _MAX_SUBTITLE_BAND_FRACTION * frame_h + _TOL:
            violations.append("subtitle band exceeds 25 percent of frame height")
    sub_rect = _rect(captions.get("subtitle_rect"), "captions.subtitle_rect")
    main_rect = _rect(plan.get("main_visual_rect", captions.get("main_visual_rect")),
                      "main_visual_rect")
    if sub_rect is not None and main_rect is not None and _rects_overlap(sub_rect, main_rect):
        violations.append("subtitle rect overlaps the main visual rect")
    if violations:
        base.update({"verdict": "blocked", "missing": [], "violations": violations,
                     "main_visual_safe": False, "subtitle_position": position})
    else:
        base.update({"verdict": "approved", "missing": [], "violations": [],
                     "main_visual_safe": True, "subtitle_position": position,
                     "subtitle_rule": "Subtitles sit in a band outside the main visual, at most 25 percent of frame height."})
    return base


# ---------------------------------------------------------------- registration

def _render_semantic(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = build_semantic_shot_list(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "semantic_shot_list.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(duration_s=0.0, sha256=compute_sha256(report),
                            qa={"report_json": str(report), "verdict": result["verdict"],
                                "shot_count": result["shot_count"]})


def _render_reuse(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = check_reuse_baseline(params.get("request"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "reuse_baseline_gate.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(duration_s=0.0, sha256=compute_sha256(report),
                            qa={"report_json": str(report), "verdict": result["verdict"]})


def _render_transcript(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = request_transcript(params.get("request"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "transcript_once.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(duration_s=0.0, sha256=compute_sha256(report),
                            qa={"report_json": str(report), "status": result["status"]})


def _render_sample(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = check_sample_first(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "sample_first_gate.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(duration_s=0.0, sha256=compute_sha256(report),
                            qa={"report_json": str(report), "verdict": result["verdict"]})


def _render_caption(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    result = check_caption_plan(params.get("plan"))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "caption_plan_gate.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(duration_s=0.0, sha256=compute_sha256(report),
                            qa={"report_json": str(report), "verdict": result["verdict"]})


def register_motion_gates_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(Capability(
        name="edit.semantic_shot_list", kind="line", aspects=["16:9", "9:16"],
        params_schema={"type": "object", "properties": {"plan": {"type": "object"}},
                       "required": ["plan"], "additionalProperties": False},
        cpu_cost_hint=0.0, render=_render_semantic, has_media_output=False,
        description=("Semantic shot orchestration table (clean-room): one main focus, "
                     "one main effect, entry/exit and handoff per shot, a readable window, "
                     "and a semantic reason for every transition. Plan only, no rendering."),
        line="edit"))
    register(Capability(
        name="edit.reuse_baseline_gate", kind="line", aspects=["16:9", "9:16"],
        params_schema={"type": "object", "properties": {"request": {"type": "object"}},
                       "required": ["request"], "additionalProperties": False},
        cpu_cost_hint=0.0, render=_render_reuse, has_media_output=False,
        description=("Reuse baseline gate (clean-room): reuse runs only from a registered "
                     "baseline of code, font and licensed assets, inherits only registered "
                     "items, and counts as a new film only after semantic events, subtitles "
                     "and the asset map are updated. Never falls back to a default-card rebuild."),
        line="edit"))
    register(Capability(
        name="audio.transcript_once", kind="line", aspects=["16:9", "9:16"],
        params_schema={"type": "object", "properties": {"request": {"type": "object"}},
                       "required": ["request"], "additionalProperties": False},
        cpu_cost_hint=0.0, render=_render_transcript, has_media_output=False,
        description=("Transcribe once with cache (clean-room): one media id plus one source "
                     "hash is transcribed once; cache hits are re-validated for language, word "
                     "timings, coverage and proper nouns and never auto-verify. No ASR model "
                     "is built in and no provider is switched automatically."),
        line="audio"))
    register(Capability(
        name="qa.sample_first_gate", kind="line", aspects=["16:9", "9:16"],
        params_schema={"type": "object", "properties": {"plan": {"type": "object"}},
                       "required": ["plan"], "additionalProperties": False},
        cpu_cost_hint=0.0, render=_render_sample, has_media_output=False,
        description=("Sample-first gate (clean-room): default delivery is a 15-20s sample "
                     "carrying the complete meaning; technical pass never counts as user "
                     "acceptance, and expanding to the full film before acceptance is blocked. "
                     "Explicit other lengths or explicit full-film requests bypass the gate."),
        line="qa"))
    register(Capability(
        name="edit.caption_plan_gate", kind="line", aspects=["16:9", "9:16"],
        params_schema={"type": "object", "properties": {"plan": {"type": "object"}},
                       "required": ["plan"], "additionalProperties": False},
        cpu_cost_hint=0.0, render=_render_caption, has_media_output=False,
        description=("Caption plan gate (clean-room): a voice plan without a caption plan is "
                     "blocked; captions.enabled=false is allowed only when the user explicitly "
                     "declined captions; enabled subtitles must sit outside the main visual "
                     "in a band of at most 25 percent of frame height."),
        line="edit"))
    return ["edit.semantic_shot_list", "edit.reuse_baseline_gate", "audio.transcript_once",
            "qa.sample_first_gate", "edit.caption_plan_gate"]


register_motion_gates_capabilities_once()
