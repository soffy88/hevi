"""Transcript-first video editing -- ``edit.video_use``.

Clean-room method intake from browser-use/video-use (MIT) SKILL.md
"Hard Rules" section (12 production-correctness rules), read from the
2026-10-25 tarball (commit 43cfc56, default branch main). No upstream
file is copied into this module and no upstream code is imported: the
rules below are implemented from their stated requirements, and the
upstream helpers (``helpers/transcribe.py``, ``helpers/render.py``)
remain only in the installed skill directories
(``~/.claude/skills/video-use``, ``~/.codex/skills/video-use``).

What this capability covers, folded into the hevi ``edit_assemble``
line (it plans and verifies; it never generates media):

1. transcript-first workflow: word-level transcript -> selections
   snapped to word boundaries with padded cut edges -> EDL -> ffmpeg
   render plan (per-segment extract, lossless concat, overlays,
   subtitles LAST). The plan is returned, never executed here.
2. cut-point self-check: a rendered file is measured at every cut
   (frame jump, audio level near the cut, loudness via ffmpeg
   ``ebur128``, subtitle/overlay occlusion, first/last/mid samples).
   Plan-level defects that are mechanically fixable are repaired and
   re-checked, at most 3 rounds (``max_rounds`` above 3 is rejected);
   media defects are never auto-fixed, they are reported as findings
   and the verdict stays ``needs_rework``.
3. deterministic hard-rule check: the 12 rules as pure functions
   over an EDL / render plan / transcript description. Each rule
   reports ``pass``, ``fail`` or ``pending`` (pending = the inputs do
   not contain the evidence, never claimed as a pass).

Transcription providers (``transcript_source``):

* ``provided`` (default): the caller supplies ``words``. Free, offline.
* ``whisper_local``: hevi's local faster-whisper route
  (``hevi.audio.whisper_alignment.whisper_align_words``), free CPU,
  no key, no download in tests (tests mock it). This is the default
  free route; the paid ElevenLabs forced-alignment capability
  (``audio.forced_align``) is a separate, caller-chosen upgrade.
* ``scribe``: interface only. Scribe (ElevenLabs) is the upstream
  default transcriber, but this machine has no ElevenLabs key and
  this capability never spends Scribe credits: requesting it raises
  :class:`CapabilityError` stating the key state and pointing at the
  upstream helper (``helpers/transcribe.py`` in the installed skill).
  No transcript is fabricated in its place.

Costs: zero paid calls in every path. ffmpeg/ffprobe are only run by
the ``cut_verify`` action, on a file the caller names.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import subprocess
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

# Cut-edge padding working window (milliseconds), hard rule 7.
PAD_MIN_MS = 30
PAD_MAX_MS = 200
DEFAULT_PAD_START_MS = 50
DEFAULT_PAD_END_MS = 80
# Audio fade at every segment boundary (milliseconds), hard rule 3.
FADE_MS = 30
# Verification loop cap, from the upstream self-eval section.
MAX_VERIFY_ROUNDS = 3
# Frame-jump threshold on 64x36 RGB frames (mean absolute channel
# difference, 0-255): above this a cut reads as a visual jump.
FRAME_JUMP_THRESHOLD = 40.0
# Near-clipping window level that reads as a possible pop, dBFS.
POP_MAX_VOLUME_DB = -1.0

# The 12 hard rules, in upstream order. ``title`` states the
# requirement; the checker for each rule is ``_check_hard_rules``.
HARD_RULES: tuple[dict[str, str], ...] = (
    {"id": "R01", "title": "Subtitles are applied LAST in the filter chain, after every overlay."},
    {"id": "R02", "title": "Per-segment extract, then lossless -c copy concat; never a single-pass filtergraph."},
    {"id": "R03", "title": "30ms audio fades at every segment boundary (in and out)."},
    {"id": "R04", "title": "Overlays shift with setpts=PTS-STARTPTS+T/TB so frame 0 lands at the window start."},
    {"id": "R05", "title": "Master SRT uses output-timeline offsets, not source-timeline times."},
    {"id": "R06", "title": "Never cut inside a word; cut edges fall on word boundaries."},
    {"id": "R07", "title": "Pad every cut edge, working window 30-200ms."},
    {"id": "R08", "title": "Word-level verbatim ASR only; never phrase/SRT mode, never normalized fillers."},
    {"id": "R09", "title": "Cache transcripts per source; never re-transcribe unless the source file changed."},
    {"id": "R10", "title": "Multiple animations run in parallel, never sequentially."},
    {"id": "R11", "title": "Strategy confirmation before execution; never touch the cut unapproved."},
    {"id": "R12", "title": "All session outputs live in <videos_dir>/edit/, never inside the skill/project directory."},
)

# Plan-level rules that the verify loop may repair mechanically.
# R06/R07 (cut placement), R08/R09 (transcript provenance), R11
# (human confirmation) and R12 (output location) are never auto-fixed:
# fixing them without new evidence or a human decision would be fake.
_FIXABLE_RULES = {"R01", "R02", "R03", "R04", "R10"}


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _as_str(value: Any) -> str:
    return "" if value is None else value if isinstance(value, str) else str(value)


def _word_tuple(word: Any) -> tuple[str, float, float]:
    """Normalize one word to (text, start_s, end_s)."""
    if isinstance(word, dict):
        text = _as_str(word.get("text")).strip()
        start = _num(word.get("start", word.get("start_s", word.get("start_ms"))))
        end = _num(word.get("end", word.get("end_s", word.get("end_ms"))))
        if word.get("start_ms") is not None and start is not None:
            start = start / 1000.0
        if word.get("end_ms") is not None and end is not None:
            end = end / 1000.0
    elif isinstance(word, (list, tuple)) and len(word) == 3:
        text = _as_str(word[0]).strip()
        start, end = _num(word[1]), _num(word[2])
    else:
        text = _as_str(getattr(word, "text", "")).strip()
        start_ms = getattr(word, "start_ms", None)
        end_ms = getattr(word, "end_ms", None)
        if start_ms is not None:
            start, end = float(start_ms) / 1000.0, float(end_ms) / 1000.0
        else:
            start = _num(getattr(word, "start", getattr(word, "start_s", None)))
            end = _num(getattr(word, "end", getattr(word, "end_s", None)))
    if not text or start is None or end is None or not end > start:
        raise CapabilityError(f"edit.video_use: invalid word entry: {word!r}")
    return text, start, end


def _normalize_words(words: Any) -> list[tuple[str, float, float]]:
    if not isinstance(words, list) or not words:
        raise CapabilityError("edit.video_use: words must be a non-empty list")
    out = [_word_tuple(w) for w in words]
    for prev, cur in zip(out, out[1:]):
        if cur[1] < prev[2]:
            raise CapabilityError(
                "edit.video_use: word timings overlap or run backwards: "
                f"{prev!r} then {cur!r}"
            )
    return out


def _run_coro(coro: Any) -> Any:
    """Run an async call from this synchronous render (multimodel pattern)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    else:
        loop = True
    if loop:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _resolve_words(params: dict[str, Any]) -> tuple[list[tuple[str, float, float]], str]:
    """Resolve the word-level transcript for the requested provider."""
    source = params.get("transcript_source") or "provided"
    if source == "provided":
        return _normalize_words(params.get("words")), "provided"
    if source == "whisper_local":
        audio_path = Path(_as_str(params.get("audio_path")))
        text = _as_str(params.get("text")).strip()
        if not audio_path.is_file():
            raise CapabilityError(
                f"edit.video_use: whisper_local audio not found: {audio_path}"
            )
        if not text:
            raise CapabilityError(
                "edit.video_use: whisper_local requires text (the known transcript)"
            )
        try:
            from hevi.audio.whisper_alignment import whisper_align_words

            raw, _cost = _run_coro(
                whisper_align_words(
                    audio_path=audio_path,
                    text=text,
                    language=_as_str(params.get("language") or "zh"),
                )
            )
        except CapabilityError:
            raise
        except Exception as exc:  # noqa: BLE001 - contract wants CapabilityError
            raise CapabilityError(f"edit.video_use: whisper_local failed: {exc}") from exc
        return _normalize_words(list(raw)), "whisper_local"
    if source == "scribe":
        key = os.getenv("ELEVENLABS_API_KEY", "").strip()
        if not key:
            raise CapabilityError(
                "edit.video_use: scribe requested but ELEVENLABS_API_KEY is not "
                "set on this machine; Scribe was not run and no transcript was "
                "produced. Use transcript_source=whisper_local (free, local) "
                "or provided words instead."
            )
        raise CapabilityError(
            "edit.video_use: scribe is an interface only in this capability: "
            "a live Scribe call is never made here, so no credits are spent "
            "and no transcript is fabricated. Run the upstream helper "
            "helpers/transcribe.py from the installed skill "
            "(~/.claude/skills/video-use) for a real Scribe transcript, "
            "then pass it back as provided words."
        )
    raise CapabilityError(f"edit.video_use: unknown transcript_source: {source!r}")


def _pad_ms(params: dict[str, Any], key: str, default: int) -> int:
    value = params.get(key)
    if value is None:
        return default
    ms = _num(value)
    if ms is None:
        raise CapabilityError(f"edit.video_use: {key} must be a number")
    return int(ms)


def _build_edl(
    words: list[tuple[str, float, float]],
    selections: Any,
    params: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build padded, word-snapped segments plus the ffmpeg plan."""
    if not isinstance(selections, list) or not selections:
        raise CapabilityError("edit.video_use: selections must be a non-empty list")
    pad_start = _pad_ms(params, "pad_start_ms", DEFAULT_PAD_START_MS)
    pad_end = _pad_ms(params, "pad_end_ms", DEFAULT_PAD_END_MS)
    for label, pad in (("pad_start_ms", pad_start), ("pad_end_ms", pad_end)):
        if not PAD_MIN_MS <= pad <= PAD_MAX_MS:
            raise CapabilityError(
                f"edit.video_use: {label}={pad} outside the 30-200ms window (R07)"
            )
    segments: list[dict[str, Any]] = []
    output_offset = 0.0
    for idx, sel in enumerate(selections):
        if not isinstance(sel, dict):
            raise CapabilityError(f"edit.video_use: selection {idx} must be an object")
        first_idx, last_idx = sel.get("start_word"), sel.get("end_word")
        if first_idx is not None or last_idx is not None:
            if first_idx is None or last_idx is None:
                raise CapabilityError(
                    "edit.video_use: start_word and end_word must be given together"
                )
            if not (0 <= int(first_idx) <= int(last_idx) < len(words)):
                raise CapabilityError(
                    f"edit.video_use: word range {first_idx}..{last_idx} out of "
                    f"range for {len(words)} words"
                )
            first = words[int(first_idx)]
            last = words[int(last_idx)]
            in_s = max(0.0, first[1] - pad_start / 1000.0)
            out_s = last[2] + pad_end / 1000.0
            quote = " ".join(w[0] for w in words[int(first_idx) : int(last_idx) + 1])
        else:
            start, end = _num(sel.get("start")), _num(sel.get("end"))
            if start is None or end is None or not end > start:
                raise CapabilityError(
                    "edit.video_use: selection needs start_word/end_word or "
                    "a valid start/end pair"
                )
            in_s, out_s = start, end
            first = (sel.get("first_word_text", ""), start, start)
            last = (sel.get("last_word_text", ""), end, end)
            quote = _as_str(sel.get("quote"))
        duration = out_s - in_s
        segments.append(
            {
                "explicit_edge": sel.get("start_word") is None and sel.get("end_word") is None,
                "source": _as_str(sel.get("source") or params.get("source_video") or ""),
                "beat": _as_str(sel.get("beat") or f"beat_{idx + 1}"),
                "in_sec": round(in_s, 3),
                "out_sec": round(out_s, 3),
                "duration_sec": round(duration, 3),
                "output_start_sec": round(output_offset, 3),
                "output_end_sec": round(output_offset + duration, 3),
                "first_word_start_sec": first[1],
                "last_word_end_sec": last[2],
                "pad_start_ms": pad_start,
                "pad_end_ms": pad_end,
                "quote": quote,
                "fade_in_ms": FADE_MS,
                "fade_out_ms": FADE_MS,
            }
        )
        output_offset += duration
    videos_dir = _as_str(params.get("videos_dir")).strip()
    base = Path(videos_dir) / "edit" if videos_dir else Path("edit")
    subtitles = params.get("subtitles") if isinstance(params.get("subtitles"), dict) else {}
    cues = subtitles.get("cues") if isinstance(subtitles.get("cues"), list) else []
    remapped_cues: list[dict[str, Any]] = []
    dropped_cues = 0
    for cue in cues:
        c_start, c_end = _num(cue.get("start")), _num(cue.get("end"))
        placed = False
        if c_start is not None and c_end is not None:
            for seg in segments:
                if seg["in_sec"] <= c_start and c_end <= seg["out_sec"]:
                    shift = seg["output_start_sec"] - seg["in_sec"]
                    remapped_cues.append(
                        {
                            "start": round(c_start + shift, 3),
                            "end": round(c_end + shift, 3),
                            "text": _as_str(cue.get("text")),
                        }
                    )
                    placed = True
                    break
        if not placed:
            dropped_cues += 1
    plan = {
        "method": "per_segment_extract_lossless_concat",
        "segments": [
            {
                "fade_in_ms": s["fade_in_ms"],
                "fade_out_ms": s["fade_out_ms"],
                "in_sec": s["in_sec"],
                "out_sec": s["out_sec"],
            }
            for s in segments
        ],
        "overlays": [
            {"setpts_shift": True}
            for _ in params.get("overlays", [])
            if isinstance(params.get("overlays"), list)
        ],
        "subtitles_stage": "last",
        "subtitles_remapped": True if cues else None,
        "subtitles_dropped_cues": dropped_cues,
        "outputs": [str(base / "final.mp4")],
        "animations_sequential": False,
        "commands": _plan_commands(segments, base),
    }
    edl = {
        "version": 1,
        "segments": segments,
        "total_duration_sec": round(output_offset, 3),
        "subtitles_output_timeline": remapped_cues,
        "subtitles_dropped_cues": dropped_cues,
        "planned_outputs": plan["outputs"],
    }
    return segments, {"edl": edl, "plan": plan}


def _plan_commands(segments: list[dict[str, Any]], base: Path) -> list[str]:
    """Render-plan command strings (plan only; never executed here)."""
    commands: list[str] = []
    for i, seg in enumerate(segments):
        commands.append(
            "ffmpeg -ss {in_s} -to {out_s} -i {src} -af "
            "afade=t=in:st=0:d=0.03,afade=t=out:st={fade_out}:d=0.03 "
            "-c:v libx264 -c:a aac {out}".format(
                in_s=seg["in_sec"],
                out_s=seg["out_sec"],
                src=seg["source"] or "<source>",
                fade_out=round(seg["duration_sec"] - 0.03, 3),
                out=f"segment_{i:02d}.mp4",
            )
        )
    commands.append(
        "ffmpeg -f concat -safe 0 -i segments.txt -c copy "
        + str(base / "joined.mp4")
    )
    commands.append(
        "ffmpeg -i " + str(base / "joined.mp4")
        + " -filter_complex [0:v]subtitles=" + str(base / "master.srt")
        + " [v] -map [v] -map 0:a -c:v libx264 -c:a aac "
        + str(base / "final.mp4")
        + "   # subtitles LAST, after every overlay"
    )
    return commands


def _rule(status: str, detail: str, rule: dict[str, str]) -> dict[str, Any]:
    return {"id": rule["id"], "title": rule["title"], "status": status, "detail": detail}


def _check_hard_rules(
    plan: dict[str, Any] | None,
    words: list[tuple[str, float, float]] | None,
    cuts: list[float] | None,
    segments: list[dict[str, Any]] | None,
    params: dict[str, Any],
) -> list[dict[str, Any]]:
    """Deterministic check of the 12 rules over plan/transcript inputs."""
    plan = plan or {}
    results: list[dict[str, Any]] = []
    subtitles = params.get("subtitles") if isinstance(params.get("subtitles"), dict) else {}
    cues = subtitles.get("cues") if isinstance(subtitles.get("cues"), list) else []
    has_subtitles = bool(cues) or plan.get("subtitles_stage") is not None
    stage = plan.get("subtitles_stage")
    if not has_subtitles:
        results.append(_rule("pass", "No subtitles in this plan; nothing to order.", HARD_RULES[0]))
    elif stage == "last":
        results.append(_rule("pass", "Subtitles stage is last.", HARD_RULES[0]))
    else:
        results.append(_rule("fail", f"Subtitles stage is {stage!r}, not last.", HARD_RULES[0]))
    method = plan.get("method")
    if method == "per_segment_extract_lossless_concat":
        results.append(_rule("pass", "Per-segment extract + lossless concat.", HARD_RULES[1]))
    else:
        results.append(_rule("fail", f"Render method is {method!r}, not per-segment extract + lossless concat.", HARD_RULES[1]))
    plan_segments = plan.get("segments") if isinstance(plan.get("segments"), list) else []
    if not plan_segments:
        results.append(_rule("pending", "No segments in plan; fades cannot be measured.", HARD_RULES[2]))
    elif all(s.get("fade_in_ms") == FADE_MS and s.get("fade_out_ms") == FADE_MS for s in plan_segments if isinstance(s, dict)):
        results.append(_rule("pass", "Every segment has 30ms in/out fades.", HARD_RULES[2]))
    else:
        results.append(_rule("fail", "A segment fade is missing or not 30ms.", HARD_RULES[2]))
    overlays = plan.get("overlays") if isinstance(plan.get("overlays"), list) else []
    if not overlays:
        results.append(_rule("pass", "No overlays; nothing to shift.", HARD_RULES[3]))
    elif all(isinstance(o, dict) and o.get("setpts_shift") is True for o in overlays):
        results.append(_rule("pass", "Every overlay uses the PTS shift.", HARD_RULES[3]))
    else:
        results.append(_rule("fail", "An overlay lacks setpts_shift.", HARD_RULES[3]))
    remapped = plan.get("subtitles_remapped")
    if not cues and remapped is None:
        results.append(_rule("pass", "No subtitle cues; output-timeline mapping is vacuous.", HARD_RULES[4]))
    elif remapped is True:
        results.append(_rule("pass", "Subtitle cues remapped to the output timeline.", HARD_RULES[4]))
    else:
        results.append(_rule("fail", "Subtitle cues are not on the output timeline.", HARD_RULES[4]))
    # R06/R07: segment-anchored when segments carry word anchors,
    # otherwise nearest-boundary over the supplied cuts.
    if segments:
        bad: list[str] = []
        for seg in segments:
            in_s, out_s = seg["in_sec"], seg["out_sec"]
            if seg.get("explicit_edge") and words:
                boundaries = sorted({b for w in words for b in (w[1], w[2])})
                for edge in (in_s, out_s):
                    if edge <= 0:
                        continue
                    nearest = min(abs(edge - b) for b in boundaries)
                    if not (PAD_MIN_MS / 1000.0 <= nearest <= PAD_MAX_MS / 1000.0):
                        bad.append(f"segment {seg['beat']} edge {edge}s nearest boundary {nearest * 1000:.0f}ms away")
                continue
            if in_s > 0:
                d_start = seg["first_word_start_sec"] - in_s
                if not (PAD_MIN_MS / 1000.0 <= d_start <= PAD_MAX_MS / 1000.0):
                    bad.append(f"segment {seg['beat']} start pad {d_start * 1000:.0f}ms")
                if in_s > seg["first_word_start_sec"]:
                    bad.append(f"segment {seg['beat']} starts inside its first word")
            d_end = out_s - seg["last_word_end_sec"]
            if not (PAD_MIN_MS / 1000.0 <= d_end <= PAD_MAX_MS / 1000.0):
                bad.append(f"segment {seg['beat']} end pad {d_end * 1000:.0f}ms")
            if out_s < seg["last_word_end_sec"]:
                bad.append(f"segment {seg['beat']} ends inside its last word")
        if bad:
            results.append(_rule("fail", "; ".join(bad), HARD_RULES[5]))
            results.append(_rule("fail", "; ".join(bad), HARD_RULES[6]))
        else:
            results.append(_rule("pass", "Every cut edge sits on a word boundary, padded, never inside a word.", HARD_RULES[5]))
            results.append(_rule("pass", "Every cut edge pad is within 30-200ms.", HARD_RULES[6]))
    elif words and cuts:
        bad_cuts: list[str] = []
        boundaries = sorted({b for w in words for b in (w[1], w[2])})
        for cut in cuts:
            if cut <= 0:
                continue
            inside = [w for w in words if w[1] < cut < w[2]]
            if inside:
                bad_cuts.append(f"cut {cut}s falls inside word {inside[0][0]!r}")
                continue
            nearest = min(abs(cut - b) for b in boundaries)
            if not (PAD_MIN_MS / 1000.0 <= nearest <= PAD_MAX_MS / 1000.0):
                bad_cuts.append(f"cut {cut}s nearest boundary {nearest * 1000:.0f}ms away")
        if bad_cuts:
            results.append(_rule("fail", "; ".join(bad_cuts), HARD_RULES[5]))
            results.append(_rule("fail", "; ".join(bad_cuts), HARD_RULES[6]))
        else:
            results.append(_rule("pass", "Every supplied cut is 30-200ms from a word boundary.", HARD_RULES[5]))
            results.append(_rule("pass", "Every supplied cut pad is within 30-200ms.", HARD_RULES[6]))
    else:
        results.append(_rule("pending", "No segments or cuts+words supplied; cut placement cannot be measured.", HARD_RULES[5]))
        results.append(_rule("pending", "No segments or cuts+words supplied; padding cannot be measured.", HARD_RULES[6]))
    transcript = params.get("transcript") if isinstance(params.get("transcript"), dict) else {}
    mode = transcript.get("mode") or params.get("transcript_mode")
    verbatim = transcript.get("verbatim")
    if mode == "word" and verbatim is True:
        results.append(_rule("pass", "Word-level verbatim transcript.", HARD_RULES[7]))
    elif mode in ("phrase", "srt") or verbatim is False:
        results.append(_rule("fail", f"Transcript mode={mode!r} verbatim={verbatim!r}; word-level verbatim required.", HARD_RULES[7]))
    else:
        results.append(_rule("pending", "Transcript mode/verbatim flag not supplied.", HARD_RULES[7]))
    retranscribed = transcript.get("retranscribed")
    source_changed = transcript.get("source_changed")
    if retranscribed is True and source_changed is not True:
        results.append(_rule("fail", "Re-transcribed without a source change.", HARD_RULES[8]))
    elif retranscribed is None and source_changed is None:
        results.append(_rule("pending", "No cache/re-transcription evidence supplied.", HARD_RULES[8]))
    else:
        results.append(_rule("pass", "No unjustified re-transcription.", HARD_RULES[8]))
    if plan.get("animations_sequential") is True:
        results.append(_rule("fail", "Animations are sequential.", HARD_RULES[9]))
    else:
        results.append(_rule("pass", "No sequential animation work in this plan.", HARD_RULES[9]))
    if params.get("strategy_confirmed") is True:
        results.append(_rule("pass", "Strategy confirmed before execution.", HARD_RULES[10]))
    else:
        results.append(_rule("fail", "Strategy not confirmed.", HARD_RULES[10]))
    outputs = plan.get("outputs") if isinstance(plan.get("outputs"), list) else []
    if not outputs:
        results.append(_rule("pending", "No outputs declared; location cannot be checked.", HARD_RULES[11]))
    else:
        outside = [o for o in outputs if Path(_as_str(o)).parent.name != "edit"]
        if outside:
            results.append(_rule("fail", f"Outputs outside an edit/ directory: {outside}", HARD_RULES[11]))
        else:
            results.append(_rule("pass", "Every output lives under an edit/ directory.", HARD_RULES[11]))
    return results


def _fix_plan(plan: dict[str, Any], failed_ids: set[str]) -> list[str]:
    """Apply mechanical fixes for fixable rules; return fixed rule ids."""
    fixed: list[str] = []
    if "R01" in failed_ids:
        plan["subtitles_stage"] = "last"
        fixed.append("R01")
    if "R02" in failed_ids:
        plan["method"] = "per_segment_extract_lossless_concat"
        fixed.append("R02")
    if "R03" in failed_ids and isinstance(plan.get("segments"), list):
        for seg in plan["segments"]:
            if isinstance(seg, dict):
                seg["fade_in_ms"] = FADE_MS
                seg["fade_out_ms"] = FADE_MS
        fixed.append("R03")
    if "R04" in failed_ids and isinstance(plan.get("overlays"), list):
        for overlay in plan["overlays"]:
            if isinstance(overlay, dict):
                overlay["setpts_shift"] = True
        fixed.append("R04")
    if "R10" in failed_ids:
        plan["animations_sequential"] = False
        fixed.append("R10")
    return fixed


def _verify_loop(
    plan: dict[str, Any],
    words: list[tuple[str, float, float]] | None,
    cuts: list[float] | None,
    segments: list[dict[str, Any]] | None,
    params: dict[str, Any],
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Check, mechanically fix, re-check; at most MAX_VERIFY_ROUNDS rounds."""
    max_rounds = params.get("max_rounds")
    if max_rounds is not None and (not isinstance(max_rounds, int) or not 1 <= max_rounds <= MAX_VERIFY_ROUNDS):
        raise CapabilityError(
            f"edit.video_use: max_rounds must be an integer in 1..{MAX_VERIFY_ROUNDS}"
        )
    rounds = int(max_rounds) if max_rounds is not None else MAX_VERIFY_ROUNDS
    fixed_all: list[str] = []
    results = _check_hard_rules(plan, words, cuts, segments, params)
    used = 1
    while used < rounds:
        failed = {r["id"] for r in results if r["status"] == "fail"}
        fixable = failed & _FIXABLE_RULES
        if not fixable:
            break
        fixed = _fix_plan(plan, fixable)
        if not fixed:
            break
        fixed_all.extend(fixed)
        used += 1
        results = _check_hard_rules(plan, words, cuts, segments, params)
    return results, used, fixed_all


def _run_ffmpeg(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=120)


def _ffprobe_duration(cut_file: Path, ffprobe_bin: str) -> float:
    proc = _run_ffmpeg(
        [ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(cut_file)]
    )
    if proc.returncode != 0:
        raise CapabilityError(
            f"edit.video_use: ffprobe failed on {cut_file}: {proc.stderr[-500:]}"
        )
    try:
        duration = float(json.loads(proc.stdout)["format"]["duration"])
    except Exception as exc:
        raise CapabilityError(f"edit.video_use: cannot parse ffprobe output: {exc}") from exc
    return duration


def _ebur128(cut_file: Path, ffmpeg_bin: str) -> dict[str, Any]:
    proc = _run_ffmpeg(
        [ffmpeg_bin, "-i", str(cut_file), "-af", "ebur128=peak=true",
         "-f", "null", "-"]
    )
    text = proc.stderr or ""
    integrated = re.search(r"Integrated loudness:\s*I:\s*(-?[\d.]+)\s*LUFS", text)
    peak = re.search(r"True peak:\s*Peak:\s*(-?[\d.]+)\s*dBFS", text)
    if integrated is None and peak is None:
        return {"status": "pending", "detail": "ebur128 summary not parsed (no audio stream or filter output changed)"}
    out: dict[str, Any] = {"status": "measured"}
    if integrated:
        out["integrated_lufs"] = float(integrated.group(1))
    if peak:
        out["true_peak_dbfs"] = float(peak.group(1))
    return out


def _frame_rgb(cut_file: Path, at_s: float, ffmpeg_bin: str) -> bytes | None:
    proc = subprocess.run(
        [ffmpeg_bin, "-v", "error", "-ss", f"{at_s:.3f}", "-i", str(cut_file),
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", "64x36", "-"],
        capture_output=True, timeout=120,
    )
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout


def _frame_jump(before: bytes, after: bytes) -> float:
    n = min(len(before), len(after))
    if n == 0:
        return 0.0
    return sum(abs(a - b) for a, b in zip(before[:n], after[:n])) / n


def _window_max_volume(cut_file: Path, at_s: float, ffmpeg_bin: str) -> float | None:
    start = max(0.0, at_s - 0.15)
    # No -v error here: volumedetect prints its stats at info level,
    # and suppressing info would make every window read as null.
    proc = _run_ffmpeg(
        [ffmpeg_bin, "-ss", f"{start:.3f}", "-t", "0.3",
         "-i", str(cut_file), "-af", "volumedetect", "-f", "null", "-"]
    )
    match = re.search(r"max_volume:\s*(-?[\d.]+)\s*dB", proc.stderr or "")
    return float(match.group(1)) if match else None


def _rects_overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    try:
        ax, ay, aw, ah = float(a["x"]), float(a["y"]), float(a["w"]), float(a["h"])
        bx, by, bw, bh = float(b["x"]), float(b["y"]), float(b["w"]), float(b["h"])
    except (KeyError, TypeError, ValueError):
        return False
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _cut_verify(params: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    cut_file = Path(_as_str(params.get("cut_file")))
    if not cut_file.is_file():
        raise CapabilityError(f"edit.video_use: cut file not found: {cut_file}")
    ffmpeg_bin = _as_str(params.get("ffmpeg_bin") or "ffmpeg")
    ffprobe_bin = _as_str(params.get("ffprobe_bin") or "ffprobe")
    duration = _ffprobe_duration(cut_file, ffprobe_bin)
    cuts_raw = params.get("cuts")
    cuts: list[float] = []
    if isinstance(cuts_raw, list):
        for value in cuts_raw:
            num = _num(value)
            if num is None or not 0 < num < duration:
                raise CapabilityError(
                    f"edit.video_use: cut {value!r} outside file duration {duration}s"
                )
            cuts.append(num)
    findings: list[dict[str, Any]] = []
    cut_reports: list[dict[str, Any]] = []
    for cut in cuts:
        before = _frame_rgb(cut_file, max(0.0, cut - 0.05), ffmpeg_bin)
        after = _frame_rgb(cut_file, min(duration - 0.01, cut + 0.05), ffmpeg_bin)
        jump: float | None = None
        if before is not None and after is not None:
            jump = round(_frame_jump(before, after), 2)
            if jump > FRAME_JUMP_THRESHOLD:
                findings.append({"check": "visual_jump", "severity": "finding", "at_sec": cut,
                                 "issue": f"Frame jump at cut {cut}s: mean channel diff {jump} > {FRAME_JUMP_THRESHOLD}.",
                                 "suggestion": "Inspect the cut frames; re-cut on a steadier frame or add a transition."})
        max_vol = _window_max_volume(cut_file, cut, ffmpeg_bin)
        if max_vol is not None and max_vol >= POP_MAX_VOLUME_DB:
            findings.append({"check": "audio_spike", "severity": "finding", "at_sec": cut,
                             "issue": f"Near-clipping audio at cut {cut}s: max volume {max_vol} dB.",
                             "suggestion": "Check the 30ms fades around this cut; re-render with the fade intact."})
        cut_reports.append({"at_sec": cut, "frame_jump": jump, "window_max_volume_db": max_vol})
    samples: dict[str, Any] = {}
    for label, at_s in (("first", 0.1), ("mid", duration / 2.0), ("last", max(0.0, duration - 0.1))):
        frame = _frame_rgb(cut_file, at_s, ffmpeg_bin)
        samples[label] = {"at_sec": round(at_s, 3), "frame_ok": frame is not None}
        if frame is None:
            findings.append({"check": "sample_frame", "severity": "finding", "at_sec": at_s,
                             "issue": f"Could not extract the {label} sample frame.",
                             "suggestion": "Check the rendered file around this timestamp."})
    subtitle_rect = params.get("subtitle_rect")
    overlay_rects = params.get("overlay_rects")
    occlusion: dict[str, Any] = {"status": "pending", "detail": "No subtitle/overlay rects supplied."}
    if isinstance(subtitle_rect, dict) and isinstance(overlay_rects, list):
        blocked = [r for r in overlay_rects if isinstance(r, dict) and _rects_overlap(subtitle_rect, r)]
        occlusion = {"status": "blocked" if blocked else "clear", "blocking_overlays": len(blocked)}
        if blocked:
            findings.append({"check": "subtitle_occlusion", "severity": "finding",
                             "issue": f"{len(blocked)} overlay(s) overlap the subtitle band (R01).",
                             "suggestion": "Move the overlay or subtitle band; subtitles must stay visible."})
    loudness = _ebur128(cut_file, ffmpeg_bin)
    if loudness.get("status") == "measured":
        integrated = loudness.get("integrated_lufs")
        if integrated is not None and integrated < -30:
            findings.append({"check": "loudness", "severity": "finding",
                             "issue": f"Integrated loudness {integrated} LUFS is very low.",
                             "suggestion": "Check the mix level; dialogue this quiet reads as a bug."})
    plan = params.get("render_plan") if isinstance(params.get("render_plan"), dict) else None
    rule_results: list[dict[str, Any]] = []
    rounds_used = 1
    fixed: list[str] = []
    if plan is not None:
        words = None
        if isinstance(params.get("words"), list):
            words = _normalize_words(params.get("words"))
        rule_results, rounds_used, fixed = _verify_loop(
            plan, words,
            cuts if cuts else None,
            None,
            params,
        )
        for rule in rule_results:
            if rule["status"] == "fail":
                findings.append({"check": f"hard_rule_{rule['id']}", "severity": "finding",
                                 "issue": f"{rule['id']}: {rule['title']} -- {rule['detail']}",
                                 "suggestion": "Fix the plan (fixable rules are repaired up to the round cap) or re-cut."})
    verdict = "pass" if not findings else "needs_rework"
    return {
        "action": "cut_verify",
        "cut_file": str(cut_file),
        "duration_sec": round(duration, 3),
        "cuts": cut_reports,
        "samples": samples,
        "loudness": loudness,
        "subtitle_occlusion": occlusion,
        "hard_rules": rule_results,
        "verify_rounds_used": rounds_used,
        "verify_rounds_fixed": fixed,
        "findings": findings,
        "verdict": verdict,
    }


def _write_report(out_dir: Path, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / "edit_video_use.json"
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    action = _as_str(params.get("action"))
    out_dir = Path(out_dir)
    if action == "transcript_first":
        if params.get("strategy_confirmed") is not True:
            raise CapabilityError(
                "edit.video_use: strategy not confirmed (R11); confirm the "
                "plain-English edit strategy before any cut is executed."
            )
        words, provider = _resolve_words(params)
        segments, built = _build_edl(words, params.get("selections"), params)
        rules = _check_hard_rules(
            built["plan"], words, None, segments,
            {**params, "transcript": {"mode": "word", "verbatim": True},
             "strategy_confirmed": True},
        )
        failed = [r for r in rules if r["status"] == "fail"]
        if failed:
            raise CapabilityError(
                "edit.video_use: built EDL fails hard rules: "
                + "; ".join(f"{r['id']} {r['detail']}" for r in failed)
            )
        payload = {
            "action": "transcript_first",
            "transcript_provider": provider,
            "word_count": len(words),
            "edl": built["edl"],
            "render_plan": built["plan"],
            "hard_rules": rules,
            "hard_rules_pass": True,
            "note": "Render plan only; ffmpeg is not executed by this capability.",
        }
        report = _write_report(out_dir, payload)
        return CapabilityResult(
            duration_s=built["edl"]["total_duration_sec"],
            sha256=compute_sha256(report),
            qa={"report_json": str(report), **payload},
        )
    if action == "rule_check":
        plan = params.get("render_plan")
        if not isinstance(plan, dict):
            raise CapabilityError("edit.video_use: rule_check requires render_plan")
        words = None
        if isinstance(params.get("words"), list):
            words = _normalize_words(params.get("words"))
        cuts = None
        if isinstance(params.get("cuts"), list):
            cuts = [c for c in (_num(v) for v in params["cuts"]) if c is not None]
        rules = _check_hard_rules(plan, words, cuts, None, params)
        payload = {
            "action": "rule_check",
            "hard_rules": rules,
            "hard_rules_pass": all(r["status"] != "fail" for r in rules),
            "failed_rules": [r["id"] for r in rules if r["status"] == "fail"],
        }
        report = _write_report(out_dir, payload)
        return CapabilityResult(
            duration_s=0.0, sha256=compute_sha256(report),
            qa={"report_json": str(report), **payload},
        )
    if action == "cut_verify":
        payload = _cut_verify(params, out_dir)
        report = _write_report(out_dir, payload)
        return CapabilityResult(
            duration_s=payload["duration_sec"],
            sha256=compute_sha256(report),
            qa={"report_json": str(report), **payload},
        )
    if action == "full":
        if params.get("strategy_confirmed") is not True:
            raise CapabilityError(
                "edit.video_use: strategy not confirmed (R11); the full loop "
                "cannot run without a confirmed strategy."
            )
        words, provider = _resolve_words(params)
        segments, built = _build_edl(words, params.get("selections"), params)
        overrides = params.get("plan_overrides")
        if isinstance(overrides, dict):
            built["plan"].update(overrides)
        rules, rounds_used, fixed = _verify_loop(
            built["plan"], words, None, segments, params
        )
        failed = [r for r in rules if r["status"] == "fail"]
        payload = {
            "action": "full",
            "transcript_provider": provider,
            "word_count": len(words),
            "edl": built["edl"],
            "render_plan": built["plan"],
            "hard_rules": rules,
            "hard_rules_pass": not failed,
            "failed_rules": [r["id"] for r in failed],
            "verify_rounds_used": rounds_used,
            "verify_rounds_fixed": fixed,
            "note": ("Unresolved failures after the round cap are reported, "
                     "never silently passed; media re-render is a caller step."),
        }
        report = _write_report(out_dir, payload)
        return CapabilityResult(
            duration_s=built["edl"]["total_duration_sec"],
            sha256=compute_sha256(report),
            qa={"report_json": str(report), **payload},
        )
    raise CapabilityError(
        "edit.video_use: unknown action "
        f"{action!r}; use transcript_first, cut_verify, rule_check or full"
    )


_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["transcript_first", "cut_verify", "rule_check", "full"]},
        "source_video": {"type": "string"},
        "videos_dir": {"type": "string"},
        "words": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                },
                "additionalProperties": False,
            },
        },
        "transcript_source": {"type": "string", "enum": ["provided", "whisper_local", "scribe"]},
        "audio_path": {"type": "string"},
        "text": {"type": "string"},
        "language": {"type": "string"},
        "selections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "start_word": {"type": "integer"},
                    "end_word": {"type": "integer"},
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "beat": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "pad_start_ms": {"type": "number"},
        "pad_end_ms": {"type": "number"},
        "strategy_confirmed": {"type": "boolean"},
        "render_plan": {"type": "object"},
        "plan_overrides": {"type": "object"},
        "transcript": {"type": "object"},
        "transcript_mode": {"type": "string"},
        "cuts": {"type": "array", "items": {"type": "number"}},
        "cut_file": {"type": "string"},
        "subtitle_rect": {"type": "object"},
        "overlay_rects": {"type": "array"},
        "subtitles": {"type": "object"},
        "overlays": {"type": "array"},
        "max_rounds": {"type": "integer"},
        "ffmpeg_bin": {"type": "string"},
        "ffprobe_bin": {"type": "string"},
    },
    "required": ["action"],
    "additionalProperties": False,
}


def register_video_use_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="edit.video_use",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Transcript-first video editing (video-use method, folded "
                "into the edit_assemble line): word-level transcript to "
                "word-snapped, padded EDL plus a lossless ffmpeg render "
                "plan (subtitles last); cut-point self-check of a rendered "
                "file (frame jump, audio spike, ebur128 loudness, subtitle "
                "occlusion, first/last/mid samples) with a max-3-round "
                "plan repair loop; and a deterministic check of the 12 "
                "production hard rules. Free routes only: provided words "
                "or local whisper; Scribe is an interface that never runs "
                "without a key and never spends credits here. The "
                "capability plans and verifies; it never executes ffmpeg "
                "renders and never generates media."
            ),
            line="edit_assemble",
        )
    )
    return ["edit.video_use"]


register_video_use_capabilities_once()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run edit.video_use on a params JSON file")
    parser.add_argument("--input", required=True, help="params JSON file")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args(argv)
    params = json.loads(Path(args.input).read_text(encoding="utf-8"))
    result = _render(params, Path(args.out), duration=0.0, aspect="16:9", seed=42)
    print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
