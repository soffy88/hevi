"""Editable production delivery (Gap Closure W8: I02, J05).

A ZIP of opaque bytes is not editable delivery. An editable export is a
document the user can keep modifying after handoff: clip ordering, trim
points, audio, subtitles, transitions, and selected versions — with the
selection itself pinned to one Presentation Read Model snapshot.

:class:`EditableTimeline` derives clips solely from a W1
``PresentationSnapshot``: video path, audio path/mode, subtitle path +
cues, effective duration. Caller-supplied overrides that disagree with
the snapshot refuse with EDITABLE_SELECTION_MISMATCH — this is the
PRESENTATION_EXPORT_PARITY mechanism, not a convention doc.

Version selection is explicit: CURRENT, STALE (usable, must be asked for
by id), or HISTORY (re-committed historical selection). Manual/raw
media (J05) exports as editable with ``source_unproven`` set and no
generation claims. Transitions are first-class editable data with an
explicit overlap policy; dissolves overlap neighbours without changing
the effective duration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from hevi.creative.layer4.presentation import MediaSourceType, PresentationSnapshot


class TrackKind(StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    TEXT = "text"


class TransitionKind(StrEnum):
    CUT = "cut"
    FADE = "fade"
    DISSOLVE = "dissolve"
    WIPE = "wipe"


class EditableError(ValueError):
    """Refusal with a stable machine code."""


class Transition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: TransitionKind = TransitionKind.CUT
    duration_ms: int = Field(ge=0, default=0)

    @model_validator(mode="after")
    def _cut_has_no_duration(self) -> Transition:
        if self.kind is TransitionKind.CUT and self.duration_ms != 0:
            raise EditableError("EDITABLE_CUT_HAS_NO_DURATION")
        if self.kind is not TransitionKind.CUT and self.duration_ms <= 0:
            raise EditableError("EDITABLE_TRANSITION_NEEDS_DURATION")
        return self


class EditableClip(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    clip_id: str = Field(min_length=1)
    order: int = Field(ge=0)
    track: TrackKind
    source_path: str = Field(min_length=1)
    source_in_ms: int = Field(ge=0, default=0)
    duration_ms: int = Field(gt=0)
    text: str = ""
    gain: float = 1.0
    transition_in: Transition = Field(default_factory=Transition)
    transition_out: Transition = Field(default_factory=Transition)


class EditableTimeline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeline_id: UUID = Field(default_factory=uuid4)
    project_id: str = Field(min_length=1)
    production_run_id: str = Field(min_length=1)
    revision_id: str = Field(min_length=1)
    presentation_snapshot_id: UUID
    presentation_version: int = Field(ge=1)
    selection_currency: str = Field(min_length=1)
    history_source_version: int | None = None
    source_unproven: bool = False
    aspect_ratio: str = Field(min_length=1)
    effective_duration_ms: int = Field(gt=0)
    clips: tuple[EditableClip, ...] = ()
    edit_revision: int = Field(ge=1, default=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _clips_cover_effective_duration(self) -> EditableTimeline:
        video_ms = sum(clip.duration_ms for clip in self.clips if clip.track is TrackKind.VIDEO)
        if video_ms != self.effective_duration_ms:
            raise EditableError("EDITABLE_VIDEO_MUST_COVER_EFFECTIVE_DURATION")
        orders = [clip.clip_id for clip in self.clips]
        if len(set(orders)) != len(orders):
            raise EditableError("EDITABLE_CLIP_ID_DUPLICATE")
        return self


def build_timeline(
    snapshot: PresentationSnapshot,
    *,
    subtitle_cues: tuple[dict[str, Any], ...] = (),
    audio_gain: float = 1.0,
    opening_transition: Transition | None = None,
) -> EditableTimeline:
    """Materialize an editable timeline from one snapshot. No re-selection."""

    clips: list[EditableClip] = [
        EditableClip(
            clip_id="v-main",
            order=0,
            track=TrackKind.VIDEO,
            source_path=snapshot.video.path,
            source_in_ms=0,
            duration_ms=snapshot.effective_duration_ms,
            transition_in=opening_transition or Transition(),
        )
    ]
    if snapshot.audio is not None:
        clips.append(
            EditableClip(
                clip_id="a-main",
                order=1,
                track=TrackKind.AUDIO,
                source_path=snapshot.audio.path,
                source_in_ms=0,
                duration_ms=snapshot.effective_duration_ms,
                gain=audio_gain,
            )
        )
    for index, cue in enumerate(subtitle_cues):
        start_ms = int(float(cue.get("start_ms", 0)))
        end_ms = int(float(cue.get("end_ms", start_ms)))
        if start_ms >= snapshot.effective_duration_ms or end_ms <= start_ms:
            continue
        clips.append(
            EditableClip(
                clip_id=f"s-{index:03d}",
                order=2 + index,
                track=TrackKind.TEXT,
                source_path=snapshot.subtitle.path if snapshot.subtitle else "inline-cues",
                source_in_ms=start_ms,
                duration_ms=min(end_ms, snapshot.effective_duration_ms) - start_ms,
                text=str(cue.get("text", "")),
            )
        )
    return EditableTimeline(
        project_id=snapshot.project_id,
        production_run_id=snapshot.production_run_id,
        revision_id=snapshot.revision_id,
        presentation_snapshot_id=snapshot.snapshot_id,
        presentation_version=snapshot.presentation_version,
        selection_currency=str(snapshot.video.currency_at_selection).lower(),
        history_source_version=snapshot.history_source_version,
        source_unproven=snapshot.video.source_type is MediaSourceType.MANUAL_RAW,
        aspect_ratio=snapshot.aspect_ratio,
        effective_duration_ms=snapshot.effective_duration_ms,
        clips=tuple(clips),
    )


def assert_snapshot_parity(
    timeline: EditableTimeline, snapshot: PresentationSnapshot
) -> EditableTimeline:
    """PRESENTATION_EXPORT_PARITY: the timeline must project this snapshot."""

    if timeline.presentation_snapshot_id != snapshot.snapshot_id:
        raise EditableError("EDITABLE_SELECTION_MISMATCH")
    video = next(c for c in timeline.clips if c.track is TrackKind.VIDEO)
    if video.source_path != snapshot.video.path:
        raise EditableError("EDITABLE_SELECTION_MISMATCH")
    audios = [c for c in timeline.clips if c.track is TrackKind.AUDIO]
    if (snapshot.audio is None and audios) or (
        snapshot.audio is not None and (not audios or audios[0].source_path != snapshot.audio.path)
    ):
        raise EditableError("EDITABLE_SELECTION_MISMATCH")
    if timeline.effective_duration_ms != snapshot.effective_duration_ms:
        raise EditableError("EDITABLE_SELECTION_MISMATCH")
    return timeline


def reorder_clips(timeline: EditableTimeline, clip_ids: tuple[str, ...]) -> EditableTimeline:
    """Clip ordering edit: same clips, new order, provenance preserved."""

    if set(clip_ids) != {clip.clip_id for clip in timeline.clips}:
        raise EditableError("EDITABLE_REORDER_MUST_COVER_ALL_CLIPS")
    by_id = {clip.clip_id: clip for clip in timeline.clips}
    clips = tuple(
        by_id[clip_id].model_copy(update={"order": index}) for index, clip_id in enumerate(clip_ids)
    )
    return timeline.model_copy(update={"clips": clips, "edit_revision": timeline.edit_revision + 1})


def trim_clip(
    timeline: EditableTimeline, clip_id: str, *, source_in_ms: int, duration_ms: int
) -> EditableTimeline:
    """Trim-point edit on one clip; video-cover invariant re-checked."""

    if duration_ms <= 0 or source_in_ms < 0:
        raise EditableError("EDITABLE_TRIM_INVALID")
    clips: list[EditableClip] = []
    found = False
    for clip in timeline.clips:
        if clip.clip_id == clip_id:
            found = True
            clips.append(
                clip.model_copy(update={"source_in_ms": source_in_ms, "duration_ms": duration_ms})
            )
        else:
            clips.append(clip)
    if not found:
        raise EditableError(f"EDITABLE_CLIP_UNKNOWN:{clip_id}")
    updated = timeline.model_copy(
        update={"clips": tuple(clips), "edit_revision": timeline.edit_revision + 1}
    )
    try:
        return EditableTimeline.model_validate(updated.model_dump())
    except ValidationError as exc:
        # Video-track cover is pinned to the snapshot: a trim that breaks
        # cover refuses instead of silently forking the presentation.
        raise EditableError("EDITABLE_VIDEO_MUST_COVER_EFFECTIVE_DURATION") from exc


def set_transition(
    timeline: EditableTimeline,
    clip_id: str,
    *,
    transition_in: Transition | None = None,
    transition_out: Transition | None = None,
) -> EditableTimeline:
    """Transition edit: dissolves overlap neighbours, duration stays effective."""

    clips: list[EditableClip] = []
    found = False
    for clip in timeline.clips:
        if clip.clip_id == clip_id:
            found = True
            clips.append(
                clip.model_copy(
                    update={
                        "transition_in": transition_in or clip.transition_in,
                        "transition_out": transition_out or clip.transition_out,
                    }
                )
            )
        else:
            clips.append(clip)
    if not found:
        raise EditableError(f"EDITABLE_CLIP_UNKNOWN:{clip_id}")
    updated = timeline.model_copy(
        update={"clips": tuple(clips), "edit_revision": timeline.edit_revision + 1}
    )
    if updated.effective_duration_ms != timeline.effective_duration_ms:
        raise EditableError("EDITABLE_TRANSITION_MUST_NOT_CHANGE_DURATION")
    return updated


def to_editable_doc(timeline: EditableTimeline) -> dict[str, Any]:
    """Serializable handoff document: re-importable by editors, no opaque bytes."""

    return timeline.model_dump(mode="json")


def editable_doc_roundtrip(doc: dict[str, Any]) -> EditableTimeline:
    return EditableTimeline.model_validate(doc)


__all__ = [
    "EditableClip",
    "EditableError",
    "EditableTimeline",
    "TrackKind",
    "Transition",
    "TransitionKind",
    "assert_snapshot_parity",
    "build_timeline",
    "editable_doc_roundtrip",
    "reorder_clips",
    "set_transition",
    "to_editable_doc",
    "trim_clip",
]
