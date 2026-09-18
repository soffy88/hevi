"""W8 gates: editable export pinned to the presentation snapshot."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hevi.creative.layer4.editable_delivery import (
    EditableError,
    TrackKind,
    Transition,
    TransitionKind,
    assert_snapshot_parity,
    build_timeline,
    editable_doc_roundtrip,
    reorder_clips,
    set_transition,
    to_editable_doc,
    trim_clip,
)
from hevi.creative.layer4.presentation import (
    AudioMode,
    MediaSourceType,
    PresentationLedger,
    PresentationSelector,
)
from tests.creative_runtime.test_presentation import _audio, _subs, _video


def _snapshot(**kw):
    args: dict = {
        "project_id": "p1",
        "production_run_id": "r1",
        "revision_id": "rev-9",
        "scope_id": "s1",
        "video_candidates": (_video(),),
        "actual_durations_ms": {"vid-1": 5230, "aud-1": 5100, "sub-1": 5230},
        "audio_mode": AudioMode.TTS,
        "audio_candidates": (_audio(),),
        "subtitle_candidates": (_subs(),),
        "dependency_revisions": {"graph": "7"},
    }
    args.update(kw)
    return PresentationSelector().select(**args)


def _cues():
    return (
        {"start_ms": 0, "end_ms": 2000, "text": "开场"},
        {"start_ms": 2000, "end_ms": 5230, "text": "继续"},
        {"start_ms": 9000, "end_ms": 9500, "text": "越界丢弃"},
    )


def test_editable_export_from_snapshot() -> None:
    """EDITABLE_EXPORT: ordering/trim/audio/subs/transitions/versions editable."""

    timeline = build_timeline(_snapshot(), subtitle_cues=_cues())
    assert timeline.presentation_version == 1
    assert timeline.selection_currency == "current"
    assert timeline.effective_duration_ms == 5230
    assert timeline.source_unproven is False
    kinds = [clip.track for clip in timeline.clips]
    assert kinds == [TrackKind.VIDEO, TrackKind.AUDIO, TrackKind.TEXT, TrackKind.TEXT]
    assert timeline.clips[2].text == "开场"
    reordered = reorder_clips(timeline, ("a-main", "v-main", "s-000", "s-001"))
    assert next(c.clip_id for c in reordered.clips) == "a-main"
    assert reordered.edit_revision == 2
    assert reordered.presentation_snapshot_id == timeline.presentation_snapshot_id
    trimmed = trim_clip(reordered, "s-000", source_in_ms=100, duration_ms=1500)
    assert trimmed.edit_revision == 3
    assert next(c for c in trimmed.clips if c.clip_id == "s-000").duration_ms == 1500


def test_presentation_export_parity() -> None:
    """PRESENTATION_EXPORT_PARITY: overrides disagreeing with snapshot refuse."""

    snapshot = _snapshot()
    timeline = build_timeline(snapshot)
    assert assert_snapshot_parity(timeline, snapshot) is timeline
    other = _snapshot()
    with pytest.raises(EditableError, match="EDITABLE_SELECTION_MISMATCH"):
        assert_snapshot_parity(timeline, other)
    forged = timeline.model_copy(
        update={
            "clips": tuple(
                c.model_copy(update={"source_path": "/v/other.mp4"})
                if c.track is TrackKind.VIDEO
                else c
                for c in timeline.clips
            )
        }
    )
    with pytest.raises(EditableError, match="EDITABLE_SELECTION_MISMATCH"):
        assert_snapshot_parity(forged, snapshot)


def test_stale_export_explicit() -> None:
    """STALE_EXPORT: stale selections export when explicitly chosen."""

    stale_video = _video()
    snapshot = PresentationSelector().select(
        project_id="p1",
        production_run_id="r1",
        revision_id="rev-9",
        scope_id="s1",
        video_candidates=(stale_video,),
        actual_durations_ms={"vid-1": 5230},
        audio_mode=AudioMode.SILENT,
        dependency_revisions={"graph": "8"},
        allow_stale=True,
    )
    assert snapshot.video.currency_at_selection == "STALE"
    timeline = build_timeline(snapshot)
    assert timeline.selection_currency == "stale"
    assert assert_snapshot_parity(timeline, snapshot) is timeline


def test_history_export() -> None:
    """HISTORY_EXPORT: historical selections re-export as new timeline versions."""

    ledger = PresentationLedger()
    first = _snapshot()
    ledger.commit_candidate(first, {"vid-1": True, "aud-1": True, "sub-1": True})
    revived = ledger.select_history(1)
    timeline = build_timeline(revived)
    assert timeline.history_source_version == 1
    assert timeline.presentation_version == 2


def test_transition_editability() -> None:
    """TRANSITION_EDITABILITY: transitions editable, duration pinned."""

    timeline = build_timeline(_snapshot())
    assert timeline.clips[0].transition_in.kind is TransitionKind.CUT
    edited = set_transition(
        timeline,
        "v-main",
        transition_in=Transition(kind=TransitionKind.DISSOLVE, duration_ms=400),
        transition_out=Transition(kind=TransitionKind.FADE, duration_ms=300),
    )
    video = next(c for c in edited.clips if c.track is TrackKind.VIDEO)
    assert video.transition_in.kind is TransitionKind.DISSOLVE
    assert video.transition_out.duration_ms == 300
    assert edited.effective_duration_ms == 5230
    assert edited.edit_revision == 2
    with pytest.raises(ValidationError, match="EDITABLE_CUT_HAS_NO_DURATION"):
        Transition(kind=TransitionKind.CUT, duration_ms=100)
    with pytest.raises(ValidationError, match="EDITABLE_TRANSITION_NEEDS_DURATION"):
        Transition(kind=TransitionKind.DISSOLVE, duration_ms=0)


def test_video_trim_breaking_cover_refuses() -> None:
    timeline = build_timeline(_snapshot())
    with pytest.raises(EditableError, match="EDITABLE_VIDEO_MUST_COVER_EFFECTIVE_DURATION"):
        trim_clip(timeline, "v-main", source_in_ms=0, duration_ms=1000)
    with pytest.raises(EditableError, match="EDITABLE_REORDER_MUST_COVER_ALL_CLIPS"):
        reorder_clips(timeline, ("v-main",))


def test_manual_raw_editable_without_generation_claims() -> None:
    from hevi.creative.layer4.presentation import CandidateMedia

    manual = CandidateMedia(
        artifact_id="up-9",
        version=1,
        path="/v/phone.mp4",
        kind="video",
        source_type=MediaSourceType.MANUAL_RAW,
        dependency_revision="graph@7",
    )
    snapshot = _snapshot(
        video_candidates=(manual,),
        dependency_revisions={},
        actual_durations_ms={"up-9": 3000, "aud-1": 2900, "sub-1": 3000},
    )
    timeline = build_timeline(snapshot)
    assert timeline.source_unproven is True
    assert timeline.effective_duration_ms == 3000
    assert assert_snapshot_parity(timeline, snapshot) is timeline


def test_editable_doc_roundtrip() -> None:
    timeline = build_timeline(_snapshot(), subtitle_cues=_cues())
    revived = editable_doc_roundtrip(to_editable_doc(timeline))
    assert revived == timeline
    assert revived.clips[0].source_path == "/v/final.mp4"


def test_jianying_sidecar_transitions(tmp_path) -> None:
    from hevi.creative.layer4.presentation import for_jianying
    from hevi.studio.ops import nle_jianying

    snapshot = _snapshot()
    timeline = build_timeline(snapshot)
    edited = set_transition(
        timeline, "v-main", transition_out=Transition(kind=TransitionKind.FADE, duration_ms=300)
    )
    transitions = [
        {
            "clip_id": clip.clip_id,
            "in": clip.transition_in.model_dump(),
            "out": clip.transition_out.model_dump(),
        }
        for clip in edited.clips
    ]
    result = nle_jianying(
        {
            "presentation": for_jianying(snapshot),
            "transitions": transitions,
            "output_dir": str(tmp_path / "draft"),
        }
    )
    assert result["status"] == "ok"
    assert result["transitions_sidecar"].endswith("transitions.json")
