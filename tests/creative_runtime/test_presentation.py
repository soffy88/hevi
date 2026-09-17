"""W1 gates: one canonical Presentation Read Model, parity across readers."""

from __future__ import annotations

import inspect
from typing import Any

import pytest

import hevi.creative.layer4.presentation as pres
from hevi.creative.layer4 import (
    for_composition,
    for_download,
    for_jianying,
    for_preview,
    for_publish,
    for_subtitles,
)
from hevi.creative.layer4.presentation import (
    AudioMode,
    CandidateMedia,
    DurationPolicy,
    MediaSourceType,
    PresentationError,
    PresentationLedger,
    PresentationSelector,
    presentation_from_task,
    snapshot_from_manifest,
)
from hevi.production.artifacts import Artifact, ArtifactManifest


def _video(version: int = 2) -> CandidateMedia:
    return CandidateMedia(
        artifact_id="vid-1",
        version=version,
        path="/v/final.mp4",
        kind="video",
        dependency_revision="graph@7",
        provider_id="maas_lock",
    )


def _audio() -> CandidateMedia:
    return CandidateMedia(
        artifact_id="aud-1",
        version=1,
        path="/v/voice.mp3",
        kind="tts",
        dependency_revision="graph@7",
    )


def _subs() -> CandidateMedia:
    return CandidateMedia(
        artifact_id="sub-1",
        version=3,
        path="/v/subs.srt",
        kind="subtitle",
        dependency_revision="graph@7",
    )


def _select(**kw: Any):
    args: dict[str, Any] = {
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


def test_select_records_traceable_provenance() -> None:
    snap = _select()
    assert snap.video.artifact_id == "vid-1"
    assert snap.video.version == 2
    assert snap.audio is not None and snap.audio.artifact_id == "aud-1"
    assert snap.subtitle is not None and snap.subtitle.artifact_id == "sub-1"
    assert snap.video.currency_at_selection == "CURRENT"
    assert all(p.startswith(("manifest:", "dependency:", "source:")) for p in snap.video.provenance)
    assert snap.source_graph_revision == "rev-9"
    assert snap.presentation_version == 1


def test_preview_export_parity_across_all_readers() -> None:
    """PREVIEW_EXPORT_PARITY: six readers project identical selection."""

    snap = _select()
    views = [
        for_preview(snap),
        for_composition(snap),
        for_download(snap),
        for_subtitles(snap),
        for_jianying(snap),
        for_publish(snap),
    ]
    keys = (
        "video_artifact_id",
        "video_version",
        "video_path",
        "audio_artifact_id",
        "audio_version",
        "audio_mode",
        "subtitle_artifact_id",
        "subtitle_version",
        "effective_duration_ms",
        "actual_video_duration_ms",
        "actual_audio_duration_ms",
    )
    first = {k: views[0][k] for k in keys}
    for view in views[1:]:
        assert {k: view[k] for k in keys} == first


def test_presentation_single_source_gate() -> None:
    """PRESENTATION_SINGLE_SOURCE: readers are canonical and snapshot-bound."""

    for fn in (
        for_preview,
        for_composition,
        for_download,
        for_subtitles,
        for_jianying,
        for_publish,
    ):
        assert fn.__module__ == "hevi.creative.layer4.presentation"
        params = list(inspect.signature(fn).parameters)
        assert params[0] == "snapshot"
    assert pres.__name__.endswith("presentation")


def test_history_pin_selects_old_version() -> None:
    old = _video(version=1)
    snap = _select(video_candidates=(_video(version=2), old), pinned_video_id="vid-1")
    # pinned id matches both entries' artifact_id; first match wins deterministically
    assert snap.video.artifact_id == "vid-1"
    ledger = PresentationLedger()
    first = _select()
    ledger.commit_candidate(first, {"vid-1": True, "aud-1": True, "sub-1": True})
    revived = ledger.select_history(1)
    assert revived.history_source_version == 1
    assert revived.presentation_version == 2
    assert revived.video.artifact_id == "vid-1"


def test_manual_raw_video_has_no_generation_claims() -> None:
    manual = CandidateMedia(
        artifact_id="up-9",
        version=1,
        path="/v/phone.mp4",
        kind="video",
        source_type=MediaSourceType.MANUAL_RAW,
        dependency_revision="graph@7",
    )
    snap = _select(
        video_candidates=(manual,),
        dependency_revisions={},
        actual_durations_ms={"up-9": 3000, "aud-1": 2900, "sub-1": 3000},
    )
    assert snap.video.source_type is MediaSourceType.MANUAL_RAW
    assert snap.video.provenance[-1] == "source:manual_raw"
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="PRESENTATION_MANUAL_RAW_FORBIDDEN_PROVENANCE"):
        CandidateMedia(
            artifact_id="up-9",
            version=1,
            path="/v/phone.mp4",
            kind="video",
            source_type=MediaSourceType.MANUAL_RAW,
            dependency_revision="graph@7",
            provider_id="some-provider",
        )


def test_native_tts_silent_audio_modes() -> None:
    native = _select(audio_mode=AudioMode.NATIVE)
    assert native.audio_mode is AudioMode.NATIVE
    assert native.audio is not None
    silent = _select(audio_mode=AudioMode.SILENT, audio_candidates=())
    assert silent.audio is None
    assert silent.actual_audio_duration_ms == 0
    assert silent.effective_duration_ms == 5230
    with pytest.raises(PresentationError, match="PRESENTATION_AUDIO_MODE_NEEDS_CANDIDATES"):
        _select(audio_mode=AudioMode.TTS, audio_candidates=())


def test_duration_policies_are_explicit() -> None:
    snap = _select()
    assert snap.effective_duration_ms == 5230
    assert "video-led" in snap.duration_decision
    audio_led = _select(duration_policy=DurationPolicy.AUDIO_LED)
    assert audio_led.effective_duration_ms == 5100
    assert "audio-led" in audio_led.duration_decision
    trimmed = _select(duration_policy=DurationPolicy.TRIM_TO_SHORTEST)
    assert trimmed.effective_duration_ms == 5100
    assert "trim-to-shortest" in trimmed.duration_decision


def test_missing_actual_duration_never_falls_back_to_requested() -> None:
    params = set(inspect.signature(PresentationSelector.select).parameters)
    assert not params & {"requested_duration_ms", "planned_duration_ms", "estimated_duration_ms"}
    with pytest.raises(PresentationError, match="PRESENTATION_DURATION_UNKNOWN"):
        _select(actual_durations_ms={"aud-1": 5100, "sub-1": 5230})
    with pytest.raises(PresentationError, match="PRESENTATION_DURATION_UNKNOWN"):
        PresentationSelector().select(
            project_id="p1",
            production_run_id="r1",
            revision_id="rev-9",
            scope_id="s1",
            video_candidates=(_video(),),
            actual_durations_ms={},
            audio_mode=AudioMode.SILENT,
        )


def test_missing_subtitle_is_explicit_none() -> None:
    snap = _select(subtitle_candidates=())
    assert snap.subtitle is None
    assert for_subtitles(snap)["subtitle_artifact_id"] is None
    assert for_jianying(snap)["subtitle_artifact_id"] is None
    assert [t["track"] for t in for_jianying(snap)["tracks"]] == ["video", "audio"]


def test_stale_candidate_skipped_unless_explicitly_allowed() -> None:
    stale_video = CandidateMedia(
        artifact_id="vid-old",
        version=1,
        path="/v/old.mp4",
        kind="video",
        dependency_revision="graph@6",
    )
    with pytest.raises(PresentationError, match="PRESENTATION_NO_QUALIFIED_VIDEO_MEDIA"):
        _select(
            video_candidates=(stale_video,),
            actual_durations_ms={"vid-old": 5000, "aud-1": 5100, "sub-1": 5230},
        )
    snap = _select(
        video_candidates=(stale_video,),
        actual_durations_ms={"vid-old": 5000, "aud-1": 5100, "sub-1": 5230},
        allow_stale=True,
    )
    assert snap.video.currency_at_selection == "STALE"
    assert snap.video.artifact_id == "vid-old"


def test_ledger_commit_and_regeneration_failure_preserves_previous() -> None:
    ledger = PresentationLedger()
    assert ledger.current is None
    first = _select()
    ledger.commit_candidate(first, {"vid-1": True, "aud-1": True, "sub-1": True})
    assert ledger.current is not None and ledger.current.presentation_version == 1
    bad = _select()
    with pytest.raises(PresentationError, match="PRESENTATION_CANDIDATE_UNVERIFIED"):
        ledger.commit_candidate(bad, {"vid-1": False, "aud-1": True, "sub-1": True})
    assert ledger.current.video.artifact_id == "vid-1"
    assert ledger.rejections[0]["failed"] == ["vid-1"]
    assert ledger.rejections[0]["preserved_version"] == 1
    with pytest.raises(PresentationError, match="PRESENTATION_HISTORY_VERSION_UNKNOWN"):
        ledger.select_history(99)


def test_snapshot_from_manifest_bridge() -> None:
    manifest = ArtifactManifest(
        production_id="p1",
        revision_id="rev-9",
        artifacts=[
            Artifact(
                artifact_id="v-main",
                kind="video",
                path="/v/main.mp4",
                media_type="video/mp4",
                primary=True,
                logical_role="final_video",
            ),
            Artifact(
                artifact_id="a-tts",
                kind="tts",
                path="/v/tts.mp3",
                media_type="audio/mpeg",
                primary=True,
            ),
            Artifact(
                artifact_id="s-srt",
                kind="subtitle",
                path="/v/en.srt",
                media_type="text/srt",
                primary=True,
            ),
        ],
    )
    snap = snapshot_from_manifest(
        manifest,
        project_id="p1",
        production_run_id="r1",
        revision_id="rev-9",
        scope_id="s1",
        actual_durations_ms={"v-main": 6000, "a-tts": 5900, "s-srt": 6000},
        audio_mode=AudioMode.TTS,
    )
    assert snap.video.artifact_id == "v-main"
    assert snap.audio is not None and snap.audio.artifact_id == "a-tts"
    assert snap.subtitle is not None and snap.subtitle.artifact_id == "s-srt"
    assert snap.effective_duration_ms == 6000
    assert for_preview(snap)["video_artifact_id"] == for_jianying(snap)["video_artifact_id"]


def test_snapshot_from_manifest_detects_manual_raw() -> None:
    manifest = ArtifactManifest(
        artifacts=[
            Artifact(
                artifact_id="up-manual",
                kind="video",
                path="/v/phone.mp4",
                media_type="video/mp4",
                primary=True,
                logical_role="manual_upload",
            )
        ]
    )
    snap = snapshot_from_manifest(
        manifest,
        project_id="p1",
        production_run_id="r1",
        revision_id="rev-9",
        scope_id="s1",
        actual_durations_ms={"up-manual": 3000},
        audio_mode=AudioMode.SILENT,
    )
    assert snap.video.source_type is MediaSourceType.MANUAL_RAW


def test_presentation_from_task_bridge() -> None:
    assert presentation_from_task({"config_json": {}}, actual_durations_ms={}) is None
    snap = _select()
    task = {
        "id": "r1",
        "project_id": "p1",
        "config_json": {
            "revision_id": "rev-9",
            "scope_id": "s1",
            "presentation_snapshot": snap.model_dump(mode="json"),
        },
    }
    revived = presentation_from_task(task, actual_durations_ms={})
    assert revived is not None
    assert revived.video.artifact_id == "vid-1"
    assert revived.snapshot_id == snap.snapshot_id
    manifest_task = {
        "id": "r2",
        "project_id": "p1",
        "config_json": {
            "revision_id": "rev-9",
            "artifact_manifest": ArtifactManifest(
                artifacts=[
                    Artifact(
                        artifact_id="v2",
                        kind="video",
                        path="/v/2.mp4",
                        media_type="video/mp4",
                        primary=True,
                    )
                ]
            ).model_dump(mode="json"),
        },
    }
    built = presentation_from_task(manifest_task, actual_durations_ms={"v2": 4000})
    assert built is not None and built.video.artifact_id == "v2"


def test_jianying_clips_come_from_same_selection() -> None:
    from hevi.studio.jianying import clips_from_presentation

    snap = _select()
    view = for_jianying(snap)
    clips = clips_from_presentation(view)
    video_clips = [c for c in clips if c.track == "video"]
    audio_clips = [c for c in clips if c.track == "audio"]
    assert len(video_clips) == 1 and video_clips[0].path == "/v/final.mp4"
    assert video_clips[0].duration_s == pytest.approx(5.23)
    assert len(audio_clips) == 1 and audio_clips[0].path == "/v/voice.mp3"
    with pytest.raises(ValueError, match="JIANYING_VIEW_MUST_COME_FROM_PRESENTATION"):
        clips_from_presentation({"reader": "recut", "tracks": []})


def test_nle_jianying_accepts_presentation_payload(tmp_path: Any) -> None:
    from hevi.studio.ops import nle_jianying

    snap = _select()
    result = nle_jianying(
        {"presentation": for_jianying(snap), "output_dir": str(tmp_path / "draft")}
    )
    assert result["status"] == "ok"
    assert result["clips"] == 3
    assert result["duration_s"] == pytest.approx(5.23, abs=0.01)


def test_pinned_and_ambiguous_selection_refusals() -> None:
    with pytest.raises(PresentationError, match="PRESENTATION_PINNED_VIDEO_NOT_OFFERED"):
        _select(pinned_video_id="nope")
    dup = (_video(), _video())
    with pytest.raises(PresentationError, match="PRESENTATION_AMBIGUOUS_VIDEO_SELECTION"):
        _select(video_candidates=dup, dependency_revisions={})
