"""Legacy timeline adapters — projections **into** ``TimelineIR``.

P0-3's second half. ``TimelineIR`` is the canonical timeline semantic boundary, but
on its own it would be a twenty-first representation: another type nobody reads.
So each surviving predecessor is given an explicit, one-directional projection into
the IR, and its role is recorded as one of:

    ADAPTER          translates a legacy type into the IR and is the only way to do so
    PROJECTION       derives from the IR (read-only, cannot define truth)
    LEGACY_READ_ONLY retained for compatibility, must not gain a writer
    TEST_FIXTURE     exists only to exercise tests
    DEAD             no callers at all

Two things these functions deliberately do **not** do:

* They do not coerce. A legacy float-second duration becomes integer milliseconds or
  the projection raises ``TimelineIRError`` — the conversion rounds rather than
  truncates, and a value that is not a whole millisecond is refused rather than
  silently rounded. Float seconds in canonical state is the defect the IR exists to
  prevent, so an adapter that quietly laundered it would defeat the boundary.
* They do not write. Every function here returns an IR. Nothing converts a
  ``TimelineIR`` back into a legacy type, because that would make the IR
  reconstructible from any of twenty shapes and therefore authoritative over none.

The IR's own validation runs on the projected result, so a legacy timeline that was
internally inconsistent — overlapping video, a gap — is refused at projection rather
than discovered later. That is the fail-closed behaviour the twenty representations
lacked; ``hyperframes/compiler.py:72-85`` coerced all of those cases.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.production.timeline_ir import (
    AudioMasterClock,
    Canvas,
    TimelineClip,
    TimelineIR,
    TimelineIRError,
    TrackKind,
    Transition,
    TransitionKind,
)

#: Classification of each predecessor representation. Recorded here so the role is a
#: value in the repository rather than a claim in a document.
LEGACY_TIMELINE_ROLES: dict[str, str] = {
    # ADAPTER — production-reachable, translated into the IR, sole translation path.
    "hevi.creative.layer4.editable_delivery.EditableTimeline": "ADAPTER",
    "hevi.studio.timeline.Timeline": "ADAPTER",
    "hevi.providers.hyperframes.compiler.HyperComposition": "ADAPTER",
    "hevi.digital_human.schemas.TimelinePlan": "ADAPTER",
    "hevi.tongjian.schemas.Timeline": "ADAPTER",
    # PROJECTION — derived from the IR; cannot define production truth.
    "hevi.production.p0_pipeline.TimelineLock": "PROJECTION",
    # LEGACY_READ_ONLY — retained, no writer may be added.
    "hevi.voicepro.schemas.TimelineSlot": "LEGACY_READ_ONLY",
    "hevi.openshorts.schemas.ClipSpec": "LEGACY_READ_ONLY",
    "hevi.layer4_legacy.previs.oprim_impl.contracts.TimelineCue": "LEGACY_READ_ONLY",
    "hevi.layer4_legacy.obase_support.creative.TimelineState": "LEGACY_READ_ONLY",
    # TEST_FIXTURE / library-only with no production entrypoint.
    "hevi.creative.direction_plan.models.BeatPlan": "TEST_FIXTURE",
    "hevi.creative.director_contract.BeatSpec": "TEST_FIXTURE",
    "hevi.assembly.music_to_video_workflow.BeatTimeline": "TEST_FIXTURE",
    "hevi.assembly.story_to_animation_workflow.StoryBeat": "TEST_FIXTURE",
    "hevi.creative.layer4.script.StoryboardBundle": "TEST_FIXTURE",
    "hevi.motion.sequence.PlannedShot": "TEST_FIXTURE",
    "hevi.assembly.assembler.ShotSegment": "TEST_FIXTURE",
    "hevi.studio.jianying.JianyingClip": "TEST_FIXTURE",
    "hevi.layer4_legacy.obase_support.creative.StoryBeat": "TEST_FIXTURE",
    # DEAD — zero importers, recorded so they are not rediscovered as novel.
    "hevi.narrative.timeline.NarrativeTimeline": "DEAD",
}


def ms_from_seconds(seconds: Any, field_name: str = "duration") -> int:
    """Convert float seconds to integer milliseconds, or refuse.

    ``round`` is used so 1.5s becomes 1500ms rather than 1499. A value that is not a
    whole millisecond (1.50005s) is refused: at 44.1kHz audio a half-millisecond is
    real, and rounding it away silently would desynchronise narration from video.
    """
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)):
        raise TimelineIRError(
            f"TIMELINE_TIME_MUST_BE_NUMERIC:{field_name}:{type(seconds).__name__}")
    millis = seconds * 1000
    rounded = round(millis)
    if abs(millis - rounded) > 1e-6:
        raise TimelineIRError(
            f"TIMELINE_SECONDS_NOT_WHOLE_MS:{field_name}:{seconds}")
    return int(rounded)


def from_editable_timeline(
    timeline: Any,
    *,
    project_id: str | None = None,
    timeline_id: str = "",
    revision_id: str = "",
    canvas: Canvas | None = None,
    audio_master_clock: AudioMasterClock | None = None,
) -> TimelineIR:
    """``EditableTimeline`` → ``TimelineIR``. The ADAPTER path.

    ``EditableTimeline`` is the closest predecessor: typed tracks, typed transitions,
    integer milliseconds and a real validator. What it lacks is a canvas, a
    ``start_ms`` (it packs clips sequentially per track, which is why
    ``studio/jianying.py:84-85`` had to recompute placement), and an identity hash.
    All three are supplied here.

    ``source_assets`` is derived from the clips rather than trusted, so the IR's
    own unresolved-asset invariant is satisfied by construction instead of being
    bypassed.
    """
    aspect = getattr(timeline, "aspect_ratio", "16:9")
    width, height = _aspect_to_canvas(aspect)

    clips: list[TimelineClip] = []
    # EditableTimeline has no explicit placement, so clips are packed per track in
    # `order`. That reproduces the predecessor's own layout and gives the IR the
    # start_ms it requires.
    cursor: dict[TrackKind, int] = {}
    for clip in sorted(timeline.clips, key=lambda c: (c.order, c.clip_id)):
        kind = TrackKind(clip.track.value)
        start = cursor.get(kind, 0)
        cursor[kind] = start + clip.duration_ms
        clips.append(TimelineClip(
            clip_id=clip.clip_id,
            track=kind,
            source_path=clip.source_path,
            start_ms=start,
            duration_ms=clip.duration_ms,
            order=clip.order,
            source_in_ms=clip.source_in_ms,
            text=clip.text,
            gain=clip.gain,
            transition_in=_transition_from(clip.transition_in),
            transition_out=_transition_from(clip.transition_out),
        ))

    return TimelineIR(
        project_id=project_id or str(getattr(timeline, "project_id", "")),
        canvas=canvas or Canvas(width=width, height=height, fps=30),
        clips=tuple(clips),
        timeline_id=timeline_id or str(getattr(timeline, "timeline_id", "")),
        revision_id=revision_id or str(getattr(timeline, "revision_id", "")),
        audio_master_clock=audio_master_clock,
        source_assets=tuple(sorted({clip.source_path for clip in clips})),
        metadata={
            "projected_from": "EditableTimeline",
            "production_run_id": str(getattr(timeline, "production_run_id", "")),
            "edit_revision": int(getattr(timeline, "edit_revision", 1)),
        },
    )


def from_hyper_composition(
    composition: Any,
    *,
    project_id: str,
    timeline_id: str = "",
    revision_id: str = "",
    audio_master_clock: AudioMasterClock | None = None,
) -> TimelineIR:
    """``HyperComposition`` → ``TimelineIR``. Float seconds, refused if lossy.

    ``HyperComposition`` stores ``start_s: float`` and ``duration_s: float``. This
    is the conversion point where those floats must stop, so
    :func:`ms_from_seconds` refuses a value that is not a whole millisecond.
    """
    cursor = 0
    clips: list[TimelineClip] = []
    for index, clip in enumerate(composition.clips):
        duration = ms_from_seconds(clip.duration_s, f"clips[{index}].duration_s")
        start = ms_from_seconds(clip.start_s, f"clips[{index}].start_s")
        # HyperComposition permits two clips at the same start; the IR does not.
        # Rather than invent a layout, the cursor is advanced so sequential clips
        # stay contiguous and an explicitly-overlapping clip is refused by the IR.
        if start == 0.0 and index > 0:
            start = cursor
        cursor = max(cursor, start + duration)
        clips.append(TimelineClip(
            clip_id=f"hyper-{index}",
            track=TrackKind.VIDEO,
            source_path=f"hyperframes://{index}",
            start_ms=start,
            duration_ms=duration,
            order=index,
            text=clip.text,
        ))

    return TimelineIR(
        project_id=project_id,
        canvas=Canvas(width=composition.width, height=composition.height,
                      fps=composition.fps),
        clips=tuple(clips),
        timeline_id=timeline_id,
        revision_id=revision_id,
        audio_master_clock=audio_master_clock,
        source_assets=tuple(sorted({c.source_path for c in clips})),
        metadata={"projected_from": "HyperComposition",
                  "title": composition.title},
    )


def from_digital_human_plan(
    plan: Any,
    *,
    project_id: str,
    timeline_id: str = "",
    revision_id: str = "",
) -> TimelineIR:
    """``TimelinePlan`` → ``TimelineIR``. Float seconds, refused if lossy."""
    clips: list[TimelineClip] = []
    for index, clip in enumerate(getattr(plan, "clips", ()) or ()):
        kind = TrackKind(clip.media_type) if clip.media_type in {
            "video", "audio", "text"} else TrackKind.VIDEO
        clips.append(TimelineClip(
            clip_id=str(getattr(clip, "clip_id", f"dh-{index}")),
            track=kind,
            source_path=str(getattr(clip, "media_path",
                                    getattr(clip, "path", f"digital-human://{index}"))),
            start_ms=ms_from_seconds(getattr(clip, "authored_start_s", 0.0),
                                     f"clips[{index}].authored_start_s"),
            duration_ms=ms_from_seconds(getattr(clip, "duration_s", 0.0),
                                        f"clips[{index}].duration_s"),
            order=index,
            text=str(getattr(clip, "text", "")),
        ))
    return TimelineIR(
        project_id=project_id,
        canvas=Canvas(width=1920, height=1080, fps=30),
        clips=tuple(clips),
        timeline_id=timeline_id,
        revision_id=revision_id,
        source_assets=tuple(sorted({c.source_path for c in clips})),
        metadata={"projected_from": "TimelinePlan"},
    )


def audio_master_clock_from_lock(lock: Any) -> AudioMasterClock:
    """``TimelineLock`` → ``AudioMasterClock``. The only integrity binding preserved.

    ``TimelineLock`` is the sole predecessor with a fail-closed digest check
    (``p0_pipeline.py:87-93``), so its fields are carried across verbatim rather than
    recomputed. A lock whose ``audio_sha256`` is not a real sha256 is refused here
    instead of being laundered into a plausible-looking clock.
    """
    return AudioMasterClock(
        audio_lock_id=lock.audio_lock_id,
        audio_sha256=lock.audio_sha256,
        audio_lock_revision=int(lock.audio_lock_revision),
        drift_ms=int(lock.drift_ms),
    )


def timeline_lock_projection(timeline: TimelineIR, lock: Any) -> dict[str, Any]:
    """``TimelineIR`` → the subset ``TimelineLock`` describes. A PROJECTION.

    Read-only and one-directional: the IR is authoritative, the lock is derived. This
    is the direction the repository was missing — today ``TimelineLock`` is authored
    independently and nothing reconciles it against the timeline it claims to lock.
    """
    return {
        "timeline_lock_id": f"tl-{timeline.content_hash()[:16]}",
        "audio_lock_id": lock.audio_lock_id,
        "audio_lock_revision": lock.audio_lock_revision,
        "audio_sha256": lock.audio_sha256,
        "cue_count": sum(1 for c in timeline.clips if c.track is TrackKind.TEXT),
        "drift_ms": lock.drift_ms,
        "timeline_hash": timeline.content_hash(),
        "derived_from": "TimelineIR",
    }


def _transition_from(transition: Any) -> Transition:
    kind_value = getattr(transition, "kind", TransitionKind.CUT)
    kind = TransitionKind(kind_value.value if hasattr(kind_value, "value")
                          else kind_value)
    return Transition(kind=kind,
                      duration_ms=int(getattr(transition, "duration_ms", 0)))


def _aspect_to_canvas(aspect: str, *, short_side: int = 720) -> tuple[int, int]:
    """Turn an ``W:H`` string into even canvas dimensions.

    Both sides are rounded to even numbers because H.264 requires even dimensions and
    an odd width fails at encode time — long after the timeline was declared valid.
    """
    try:
        width_text, height_text = aspect.split(":", 1)
        ratio_w, ratio_h = int(width_text), int(height_text)
    except (ValueError, AttributeError) as exc:
        raise TimelineIRError(f"TIMELINE_BAD_ASPECT_RATIO:{aspect!r}") from exc
    if ratio_w <= 0 or ratio_h <= 0:
        raise TimelineIRError(f"TIMELINE_BAD_ASPECT_RATIO:{aspect!r}")
    if ratio_w >= ratio_h:
        width, height = short_side * ratio_w // ratio_h, short_side
    else:
        width, height = short_side, short_side * ratio_h // ratio_w
    return width - (width % 2), height - (height % 2)


def write_timeline_ir(timeline: TimelineIR, destination: str | Path) -> Path:
    """Persist an IR next to its hash, so a stored timeline is self-identifying.

    The file is ``<name>.timeline.json`` containing the canonical dict plus
    ``content_hash``. Writing the hash beside the content is what lets P0-5's
    ``RenderReceipt.timeline_hash`` be checked against the timeline actually used,
    rather than against a recomputation nobody performed.
    """
    target = Path(destination)
    if target.suffix != ".json":
        target = target.with_suffix(".timeline.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(timeline.to_dict(), indent=2, sort_keys=True,
                                 ensure_ascii=False) + "\n", encoding="utf-8")
    return target


def read_timeline_ir(source: str | Path) -> TimelineIR:
    """Load and re-verify a persisted IR.

    The stored ``content_hash`` is recomputed and compared, so a hand-edited or
    truncated timeline file is refused rather than trusted.
    """
    from hevi.production.timeline_ir import validate_timeline

    payload = json.loads(Path(source).read_text(encoding="utf-8"))
    recorded = payload.pop("content_hash", None)
    timeline = validate_timeline(payload)
    if recorded is not None and recorded != timeline.content_hash():
        raise TimelineIRError(
            f"TIMELINE_CONTENT_HASH_MISMATCH:{recorded}"
            f":{timeline.content_hash()}")
    return timeline


def timeline_hash_of(source: str | Path) -> str:
    """Convenience: the verified ``timeline_hash`` for a persisted IR."""
    return read_timeline_ir(source).content_hash()


__all__ = [
    "LEGACY_TIMELINE_ROLES",
    "audio_master_clock_from_lock",
    "from_digital_human_plan",
    "from_editable_timeline",
    "from_hyper_composition",
    "ms_from_seconds",
    "read_timeline_ir",
    "timeline_hash_of",
    "timeline_lock_projection",
    "write_timeline_ir",
]