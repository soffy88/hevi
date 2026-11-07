"""Subtitle-driven step segmentation with a capped visual-check budget.

``video.step_segmentation`` turns a caller-supplied transcript and a local
video file into a step list: consecutive transcript segments are grouped
into steps, each step carries a confidence value, and the least confident
steps -- up to a small fixed budget -- get one extracted frame each plus
a verification request record for a human to check. Nothing here
transcribes, downloads, calls a model, judges a frame, rewrites step
text, or writes prose or PDF output.

What is borrowed, as a method idea only, from jiangsai1979/vid2guide
(MIT): segment an operation video from its subtitles, score every step
with a confidence value that is honest about vague subtitles, and spend
a capped number of frame inspections on the least confident steps
first, instead of inspecting every step or trusting every step. The
segmentation here is a deterministic grouping rule over the transcript
the caller supplies; the confidence here is an arithmetic mean of the
per-segment confidences the caller supplies; and the frame inspection
here is a request record for a human, never a model judgement. The
source tool's download flow, model calls, transcription invocation,
and document generation were deliberately not taken.

Inputs:

* ``video_path`` -- a local video file. It is probed with ffprobe for
  duration only; no frame is decoded except the budgeted check frames.
* ``segments`` -- the transcript, supplied by the caller (for example
  from ``audio.asr_transcribe`` upstream). Each segment has ``start``
  and ``end`` in seconds and ``text``; a per-segment ``confidence``
  between 0 and 1 is optional. The transcript may carry any language;
  a ``language`` tag is passed through untouched and never used to
  alter the grouping.
* ``rights`` -- a declaration of where the video came from and on what
  basis it may be processed and published. No declaration, no run.
  This module cannot verify a rights claim; it only refuses to work
  without one.
* ``transcript_reviewed`` -- whether a human has reviewed the
  transcript. When false (the default), every step carries
  ``transcript_unverified: true`` and no visual check may clear that
  flag; only a re-run with a reviewed transcript produces steps
  without it.

Grouping rule (a documented heuristic, not a measurement): a new step
starts when the silence gap between one segment's end and the next
segment's start reaches the gap threshold (default 2.0 s). Steps are
then split at segment boundaries when they exceed the maximum step
duration (default 60 s) and short steps are merged forward when they
fall below the minimum step duration (default 3 s), unless merging
would itself exceed the maximum. Every split or merge is recorded in
the step's ``flags``. A single over-long segment stays whole and is
flagged ``exceeds_max_duration`` rather than being cut mid-sentence.

Confidence rule: a step's confidence is the mean of its member
segments' confidences. A segment without a confidence counts as 0.5
and the step is flagged ``confidence_estimated``. Steps below the
confidence threshold (default 0.7) are flagged
``needs_visual_check``. The visual-check budget (default 4, hard cap
8) selects the lowest-confidence flagged steps first, ties broken by
earliest start, and extracts exactly one frame per selected step at
the step's midpoint. The frame is never judged here: the verification
request record holds the step id, the timestamp, the frame path, and
the step's subtitle text, with status ``awaiting_human_check``.

Titles are mechanical: a step's ``title_derived`` is the first
characters of its concatenated subtitle text, cut at a fixed length,
and is never presented as a written or model-chosen title.

Failure contract: a missing video, missing or empty rights, an empty
transcript, overlapping or non-increasing segment timestamps, a
timestamp beyond the probed duration, a confidence outside 0..1, a
budget outside 0..8, inconsistent duration limits, or an existing
output without an explicit overwrite all raise CapabilityError. No
frame is extracted for a step that was not selected, and no output
file is written when validation fails.
"""

from __future__ import annotations

import json
import math
import shutil
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

CAPABILITY_NAME = "video.step_segmentation"
_PREFIX = CAPABILITY_NAME + ": "

DEFAULT_GAP_THRESHOLD = 2.0
DEFAULT_MIN_STEP_DURATION = 3.0
DEFAULT_MAX_STEP_DURATION = 60.0
DEFAULT_CONFIDENCE_THRESHOLD = 0.7
DEFAULT_VISUAL_CHECK_BUDGET = 4
MAX_VISUAL_CHECK_BUDGET = 8
DEFAULT_TITLE_CHARS = 40
FALLBACK_CONFIDENCE = 0.5


def _fail(message: str) -> CapabilityError:
    return CapabilityError(_PREFIX + message)


def require_rights(rights: Any) -> dict[str, Any]:
    """Normalise a rights declaration, or refuse without one."""
    if not isinstance(rights, dict):
        raise _fail("rights must be an object with source and basis")
    source = rights.get("source")
    basis = rights.get("basis")
    if not isinstance(source, str) or not source.strip():
        raise _fail(
            "rights.source must be a non-empty string naming the video source"
        )
    if not isinstance(basis, str) or not basis.strip():
        raise _fail(
            "rights.basis must be a non-empty string stating the basis "
            "for processing and publishing this video"
        )
    publish = rights.get("publish", False)
    if not isinstance(publish, bool):
        raise _fail("rights.publish must be a boolean when supplied")
    return {"source": source.strip(), "basis": basis.strip(), "publish": publish}


def _tool_version(exe: str) -> str:
    """First line of ``<exe> -version``; empty string when it cannot run."""
    try:
        result = subprocess.run(
            [exe, "-version"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    first = (result.stdout or "").splitlines()
    return first[0].strip() if first else ""


def probe_duration(
    video_path: Path, *, ffprobe_exe: str = "ffprobe"
) -> float:
    """Return the video duration in seconds, probed with ffprobe."""
    if not video_path.is_file():
        raise _fail(f"video file not found: {video_path}")
    if shutil.which(ffprobe_exe) is None:
        raise _fail(f"ffprobe not found on PATH (looked for {ffprobe_exe!r})")
    result = subprocess.run(
        [
            ffprobe_exe,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise _fail(f"ffprobe failed for {video_path}: {result.stderr.strip()}")
    try:
        payload = json.loads(result.stdout or "{}")
        duration = float(payload["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _fail(f"ffprobe returned no usable duration for {video_path}") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise _fail(f"ffprobe returned an unusable duration for {video_path}")
    return duration


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_segments(segments: Any, duration_sec: float) -> list[dict[str, Any]]:
    """Validate and normalise the caller-supplied transcript segments."""
    if not isinstance(segments, list) or not segments:
        raise _fail("segments must be a non-empty list of transcript segments")
    normalised: list[dict[str, Any]] = []
    previous_end: float | None = None
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise _fail(f"segments[{index}] must be an object")
        start = segment.get("start")
        end = segment.get("end")
        text = segment.get("text")
        if not _is_number(start) or not _is_number(end):
            raise _fail(f"segments[{index}] needs numeric start and end seconds")
        start = float(start)
        end = float(end)
        if not math.isfinite(start) or not math.isfinite(end):
            raise _fail(f"segments[{index}] has a non-finite timestamp")
        if start < 0:
            raise _fail(f"segments[{index}] starts before zero")
        if end <= start:
            raise _fail(f"segments[{index}] must end after it starts")
        if end > duration_sec:
            raise _fail(
                f"segments[{index}] ends at {end}s, beyond the video "
                f"duration of {duration_sec}s"
            )
        if previous_end is not None and start < previous_end:
            raise _fail(
                f"segments[{index}] starts at {start}s, overlapping the "
                f"previous segment ending at {previous_end}s"
            )
        if not isinstance(text, str):
            raise _fail(f"segments[{index}] needs a text string")
        confidence = segment.get("confidence")
        if confidence is not None:
            if not _is_number(confidence):
                raise _fail(f"segments[{index}] confidence must be a number")
            confidence = float(confidence)
            if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
                raise _fail(f"segments[{index}] confidence must be within 0..1")
        normalised.append(
            {
                "start": start,
                "end": end,
                "text": text,
                "confidence": confidence,
            }
        )
        previous_end = end
    return normalised


def group_segments(
    segments: list[dict[str, Any]], *, gap_threshold: float
) -> list[list[dict[str, Any]]]:
    """Group consecutive segments into steps on silence gaps.

    A new step starts when the gap between the previous segment's end
    and the next segment's start reaches ``gap_threshold`` seconds.
    """
    groups: list[list[dict[str, Any]]] = [[segments[0]]]
    for segment in segments[1:]:
        gap = segment["start"] - groups[-1][-1]["end"]
        if gap >= gap_threshold:
            groups.append([segment])
        else:
            groups[-1].append(segment)
    return groups


def _group_duration(group: list[dict[str, Any]]) -> float:
    return group[-1]["end"] - group[0]["start"]


def enforce_durations(
    groups: list[list[dict[str, Any]]],
    *,
    min_step_duration: float,
    max_step_duration: float,
) -> tuple[list[list[dict[str, Any]]], list[list[str]]]:
    """Split over-long steps and merge under-short ones, at boundaries.

    Returns the adjusted groups plus one flag list per group. Splitting
    happens first, at segment boundaries only; a single segment longer
    than the maximum stays whole. Merging then folds a short group
    into the following group, or into the previous one when it is the
    last group, unless the merge would exceed the maximum duration.
    """
    split: list[list[dict[str, Any]]] = []
    split_flags: list[list[str]] = []
    for group in groups:
        if _group_duration(group) <= max_step_duration:
            split.append(group)
            split_flags.append([])
            continue
        chunks: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for segment in group:
            if current and _group_duration(current + [segment]) > max_step_duration:
                chunks.append(current)
                current = [segment]
            else:
                current.append(segment)
        if current:
            chunks.append(current)
        was_split = len(chunks) > 1
        for chunk in chunks:
            split.append(chunk)
            split_flags.append(["split_for_max_duration"] if was_split else [])
    merged: list[list[dict[str, Any]]] = []
    merged_flags: list[list[str]] = []
    index = 0
    while index < len(split):
        group = split[index]
        flags = list(split_flags[index])
        if _group_duration(group) < min_step_duration:
            if _group_duration(group) > max_step_duration:
                flags.append("exceeds_max_duration")
                merged.append(group)
                merged_flags.append(flags)
                index += 1
                continue
            neighbour = index + 1 if index + 1 < len(split) else index - 1
            if neighbour < 0:
                flags.append("below_min_duration")
                merged.append(group)
                merged_flags.append(flags)
                index += 1
                continue
            combined = (
                group + split[neighbour]
                if neighbour > index
                else split[neighbour] + group
            )
            if _group_duration(combined) <= max_step_duration:
                combined_flags = sorted(
                    set(split_flags[index])
                    | set(split_flags[neighbour])
                    | {"merged_for_min_duration"}
                )
                if neighbour > index:
                    merged.append(combined)
                    merged_flags.append(combined_flags)
                    index += 2
                else:
                    merged[-1] = combined
                    merged_flags[-1] = sorted(set(merged_flags[-1]) | set(combined_flags))
                    index += 1
                continue
            flags.append("below_min_duration")
        if _group_duration(group) > max_step_duration:
            flags.append("exceeds_max_duration")
        merged.append(group)
        merged_flags.append(sorted(set(flags)))
        index += 1
    return merged, merged_flags


def step_confidence(members: list[dict[str, Any]]) -> tuple[float, bool]:
    """Mean member confidence; missing values count as the fallback."""
    estimated = False
    values: list[float] = []
    for member in members:
        confidence = member.get("confidence")
        if confidence is None:
            estimated = True
            values.append(FALLBACK_CONFIDENCE)
        else:
            values.append(confidence)
    return sum(values) / len(values), estimated


def build_title(members: list[dict[str, Any]], *, max_chars: int) -> str:
    """Mechanical title: the first characters of the joined subtitle text."""
    joined = " ".join(member["text"].strip() for member in members).strip()
    joined = " ".join(joined.split())
    return joined[:max_chars].strip()


def select_visual_checks(
    steps: list[dict[str, Any]], *, confidence_threshold: float, budget: int
) -> list[int]:
    """Pick the lowest-confidence steps first, up to the budget.

    Only steps below ``confidence_threshold`` are eligible. Ties break
    by earliest start, so the selection is deterministic. Returns
    1-based step ids matching each step's ``id`` field.
    """
    if budget < 0 or budget > MAX_VISUAL_CHECK_BUDGET:
        raise _fail(
            f"visual_check_budget must be within 0..{MAX_VISUAL_CHECK_BUDGET}"
        )
    eligible = [
        (step["confidence"], step["start"], index)
        for index, step in enumerate(steps)
        if step["needs_visual_check"]
    ]
    eligible.sort()
    return [index + 1 for _, _, index in eligible[:budget]]


def extract_frame(
    video_path: Path,
    timestamp: float,
    out_path: Path,
    *,
    ffmpeg_exe: str = "ffmpeg",
    overwrite: bool = False,
) -> Path:
    """Extract one frame with the system ffmpeg; never silently overwrite."""
    if out_path.exists() and not overwrite:
        raise _fail(f"frame already exists, refusing to overwrite: {out_path}")
    if shutil.which(ffmpeg_exe) is None:
        raise _fail(f"ffmpeg not found on PATH (looked for {ffmpeg_exe!r})")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            ffmpeg_exe,
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(out_path),
            "-y",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0 or not out_path.is_file():
        raise _fail(
            f"ffmpeg frame extraction failed at {timestamp:.3f}s: "
            f"{result.stderr.strip()[-300:]}"
        )
    return out_path


def build_step_segmentation(
    video_path: str,
    segments: Any,
    rights: Any,
    out_dir: str | Path,
    *,
    transcript_reviewed: bool = False,
    language: str | None = None,
    gap_threshold: float = DEFAULT_GAP_THRESHOLD,
    min_step_duration: float = DEFAULT_MIN_STEP_DURATION,
    max_step_duration: float = DEFAULT_MAX_STEP_DURATION,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    visual_check_budget: int = DEFAULT_VISUAL_CHECK_BUDGET,
    title_chars: int = DEFAULT_TITLE_CHARS,
    overwrite: bool = False,
    output_name: str = "steps",
    ffmpeg_exe: str = "ffmpeg",
    ffprobe_exe: str = "ffprobe",
) -> dict[str, Any]:
    """Build the step list, check frames, and write steps + manifest JSON."""
    rights_decl = require_rights(rights)
    if not isinstance(video_path, str) or not video_path.strip():
        raise _fail("video_path must be a non-empty local file path")
    video = Path(video_path)
    if gap_threshold <= 0:
        raise _fail("gap_threshold must be greater than zero")
    if min_step_duration < 0:
        raise _fail("min_step_duration must not be negative")
    if max_step_duration <= 0:
        raise _fail("max_step_duration must be greater than zero")
    if max_step_duration < min_step_duration:
        raise _fail("max_step_duration must not be below min_step_duration")
    if not 0.0 <= confidence_threshold <= 1.0:
        raise _fail("confidence_threshold must be within 0..1")
    if title_chars <= 0:
        raise _fail("title_chars must be greater than zero")
    if not isinstance(transcript_reviewed, bool):
        raise _fail("transcript_reviewed must be a boolean")
    if language is not None and not isinstance(language, str):
        raise _fail("language must be a string tag when supplied")
    duration_sec = probe_duration(video, ffprobe_exe=ffprobe_exe)
    validated = validate_segments(segments, duration_sec)
    groups, group_flags = enforce_durations(
        group_segments(validated, gap_threshold=gap_threshold),
        min_step_duration=min_step_duration,
        max_step_duration=max_step_duration,
    )

    steps: list[dict[str, Any]] = []
    for step_id, (group, flags) in enumerate(zip(groups, group_flags), start=1):
        confidence, estimated = step_confidence(group)
        text = " ".join(" ".join(m["text"].strip() for m in group).split())
        step_flags = sorted(set(flags))
        if estimated:
            step_flags.append("confidence_estimated")
        if not text:
            step_flags.append("no_spoken_text")
        steps.append(
            {
                "id": step_id,
                "start": group[0]["start"],
                "end": group[-1]["end"],
                "key_timestamp": (group[0]["start"] + group[-1]["end"]) / 2.0,
                "title_derived": build_title(group, max_chars=title_chars),
                "text": text,
                "confidence": round(confidence, 4),
                "confidence_estimated": estimated,
                "needs_visual_check": confidence < confidence_threshold,
                "transcript_unverified": not transcript_reviewed,
                "flags": sorted(set(step_flags)),
                "visual_check": None,
            }
        )

    selected = select_visual_checks(
        steps,
        confidence_threshold=confidence_threshold,
        budget=visual_check_budget,
    )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    steps_path = out / f"{output_name}.json"
    manifest_path = out / f"{output_name}_manifest.json"
    if not overwrite and (steps_path.exists() or manifest_path.exists()):
        raise _fail(
            "output already exists, refusing to overwrite: "
            f"{steps_path} (pass overwrite=true to replace it)"
        )
    frames_dir = out / "frames"
    for step_id in selected:
        step = steps[step_id - 1]
        frame_path = frames_dir / f"check_step_{step['id']:02d}.jpg"
        extract_frame(
            video,
            step["key_timestamp"],
            frame_path,
            ffmpeg_exe=ffmpeg_exe,
            overwrite=overwrite,
        )
        step["visual_check"] = {
            "frame": str(frame_path),
            "timestamp": step["key_timestamp"],
            "subtitle_text": step["text"],
            "status": "awaiting_human_check",
            "transcript_unverified": not transcript_reviewed,
        }

    payload = {
        "capability": CAPABILITY_NAME,
        "video_path": str(video),
        "video_duration_s": duration_sec,
        "language": language,
        "transcript_reviewed": transcript_reviewed,
        "steps": steps,
    }
    steps_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest = {
        "capability": CAPABILITY_NAME,
        "video_path": str(video),
        "video_sha256": compute_sha256(video),
        "video_duration_s": duration_sec,
        "rights": rights_decl,
        "language": language,
        "transcript_reviewed": transcript_reviewed,
        "thresholds": {
            "gap_threshold_s": gap_threshold,
            "min_step_duration_s": min_step_duration,
            "max_step_duration_s": max_step_duration,
            "confidence_threshold": confidence_threshold,
            "visual_check_budget": visual_check_budget,
            "visual_check_hard_cap": MAX_VISUAL_CHECK_BUDGET,
            "title_chars": title_chars,
            "fallback_confidence": FALLBACK_CONFIDENCE,
        },
        "tool_versions": {
            "ffmpeg": _tool_version(ffmpeg_exe),
            "ffprobe": _tool_version(ffprobe_exe),
        },
        "steps_path": str(steps_path),
        "frames": [
            steps[step_id - 1]["visual_check"]["frame"] for step_id in selected
        ],
        "step_count": len(steps),
        "visual_check_count": len(selected),
        "visual_check_step_ids": selected,
        "flags_present": sorted({flag for step in steps for flag in step["flags"]}),
        "warnings": [
            "transcript_unverified: no step was cleared by a visual check"
            if not transcript_reviewed
            else "transcript_reviewed: caller-declared, not verified here"
        ],
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {
        "steps_path": steps_path,
        "manifest_path": manifest_path,
        "manifest": manifest,
        "steps": steps,
        "duration_s": duration_sec,
    }


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    """Capability entry point: the duration/aspect/seed are not used.

    The output is deterministic for a given video and transcript; the
    seed plays no part, and the probed video duration governs.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    result = build_step_segmentation(
        params.get("video_path"),
        params.get("segments"),
        params.get("rights"),
        out_dir,
        transcript_reviewed=params.get("transcript_reviewed", False),
        language=params.get("language"),
        gap_threshold=params.get("gap_threshold", DEFAULT_GAP_THRESHOLD),
        min_step_duration=params.get(
            "min_step_duration", DEFAULT_MIN_STEP_DURATION
        ),
        max_step_duration=params.get(
            "max_step_duration", DEFAULT_MAX_STEP_DURATION
        ),
        confidence_threshold=params.get(
            "confidence_threshold", DEFAULT_CONFIDENCE_THRESHOLD
        ),
        visual_check_budget=params.get(
            "visual_check_budget", DEFAULT_VISUAL_CHECK_BUDGET
        ),
        title_chars=params.get("title_chars", DEFAULT_TITLE_CHARS),
        overwrite=params.get("overwrite", False),
        output_name=params.get("output_name", "steps"),
        ffmpeg_exe=params.get("ffmpeg_exe", "ffmpeg"),
        ffprobe_exe=params.get("ffprobe_exe", "ffprobe"),
    )
    steps_path = result["steps_path"]
    return CapabilityResult(
        duration_s=result["duration_s"],
        sha256=compute_sha256(steps_path),
        qa={
            "report_json": str(steps_path),
            "manifest_json": str(result["manifest_path"]),
            "step_count": result["manifest"]["step_count"],
            "visual_check_count": result["manifest"]["visual_check_count"],
            "visual_check_step_ids": result["manifest"]["visual_check_step_ids"],
            "transcript_unverified": not params.get("transcript_reviewed", False),
            "warnings": result["manifest"]["warnings"],
        },
    )


def register_video_step_segmentation_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name=CAPABILITY_NAME,
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "video_path": {"type": "string"},
                    "segments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "start": {"type": "number"},
                                "end": {"type": "number"},
                                "text": {"type": "string"},
                                "confidence": {"type": "number"},
                            },
                            "required": ["start", "end", "text"],
                            "additionalProperties": False,
                        },
                        "minItems": 1,
                    },
                    "rights": {"type": "object"},
                    "transcript_reviewed": {"type": "boolean"},
                    "language": {"type": "string"},
                    "gap_threshold": {"type": "number", "exclusiveMinimum": 0},
                    "min_step_duration": {"type": "number", "minimum": 0},
                    "max_step_duration": {"type": "number", "exclusiveMinimum": 0},
                    "confidence_threshold": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "visual_check_budget": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": MAX_VISUAL_CHECK_BUDGET,
                    },
                    "title_chars": {"type": "integer", "exclusiveMinimum": 0},
                    "overwrite": {"type": "boolean"},
                    "output_name": {"type": "string"},
                    "ffmpeg_exe": {"type": "string"},
                    "ffprobe_exe": {"type": "string"},
                },
                "required": ["video_path", "segments", "rights"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Subtitle-driven step segmentation from a local video file "
                "and a caller-supplied transcript: deterministic grouping "
                "on silence gaps with min/max duration limits, per-step "
                "confidence as the mean of member confidences, and a "
                "capped lowest-first visual-check budget that extracts "
                "one frame per selected step as a human verification "
                "request. A rights declaration is required, the "
                "transcript is never transcribed here, and no frame is "
                "judged and no step text is rewritten. Local files only: "
                "no downloads, no transcription, no model calls, no network."
            ),
            line="edit",
        )
    )
    return [CAPABILITY_NAME]


register_video_step_segmentation_capabilities_once()
