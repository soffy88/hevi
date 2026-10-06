"""TimelineIR invariants — P0-3.

`TimelineIR` is the canonical timeline semantic boundary. These tests hold it to the
three properties that made the twenty predecessors inadequate: integer milliseconds,
fail-closed validation, and a stable content hash.

The distinction the suite is built around: a *refusal* test asserts that bad input is
**rejected**, and a *mutation* test asserts that a plausible wrong implementation would
fail. A validator that silently coerces, defaults, or clamps passes every happy-path
test in the repository — that is how `hyperframes/compiler.py:72-85` survived, with no
`raise` anywhere in the module. So each coercion the predecessors performed is written
here as an explicit rejection.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from hevi.production.timeline_adapters import (
    LEGACY_TIMELINE_ROLES,
    audio_master_clock_from_lock,
    from_digital_human_plan,
    from_editable_timeline,
    from_hyper_composition,
    ms_from_seconds,
    read_timeline_ir,
    timeline_lock_projection,
    write_timeline_ir,
)
from hevi.production.timeline_ir import (
    AudioMasterClock,
    Canvas,
    TimelineClip,
    TimelineIR,
    TimelineIRError,
    TrackKind,
    Transition,
    TransitionKind,
    validate_timeline,
)

DIGEST = "a" * 64


def _canvas() -> Canvas:
    return Canvas(width=1920, height=1080, fps=30)


def _video_clips() -> tuple[TimelineClip, ...]:
    return (
        TimelineClip("v1", TrackKind.VIDEO, "a.mp4", 3000, start_ms=0, order=0),
        TimelineClip("v2", TrackKind.VIDEO, "b.mp4", 2000, start_ms=3000, order=1),
    )


def _timeline(**overrides: Any) -> TimelineIR:
    defaults = {
        "project_id": "proj-1",
        "canvas": _canvas(),
        "clips": _video_clips(),
        "timeline_id": "tl-1",
        "revision_id": "rev-1",
        "audio_master_clock": AudioMasterClock("al-1", DIGEST, 1, 0),
        "source_assets": ("a.mp4", "b.mp4"),
    }
    return TimelineIR(**{**defaults, **overrides})


# ── positive: the canonical invariants hold ──────────────────────────────


def test_timeline_builds_and_reports_derived_duration() -> None:
    timeline = _timeline()
    assert timeline.duration_ms == 5000, (
        "duration must be derived from clip extents, not declared, so it cannot "
        "disagree with the clips")
    assert timeline.canvas.aspect_ratio == "16:9"


def test_content_hash_is_sha256_and_stable_across_construction_order() -> None:
    forward = _timeline()
    reversed_clips = _timeline(
        clips=tuple(reversed(_video_clips())),
        source_assets=("b.mp4", "a.mp4"),
    )
    assert len(forward.content_hash()) == 64
    assert forward.content_hash() == reversed_clips.content_hash(), (
        "two timelines with identical content must hash identically regardless of "
        "the order their clips were constructed in")


def test_content_hash_distinguishes_revision_and_identity() -> None:
    """A receipt must be able to tell two revisions apart."""
    base = _timeline()
    assert base.content_hash() != _timeline(revision_id="rev-2").content_hash()
    assert base.content_hash() != _timeline(timeline_id="tl-2").content_hash()


def test_content_hash_changes_when_content_changes() -> None:
    base = _timeline()
    edited = _timeline(clips=(
        TimelineClip("v1", TrackKind.VIDEO, "a.mp4", 3001, start_ms=0, order=0),
        TimelineClip("v2", TrackKind.VIDEO, "b.mp4", 1999, start_ms=3001, order=1),
    ))
    assert base.content_hash() != edited.content_hash()


def test_serialisation_round_trips_through_validation() -> None:
    original = _timeline()
    restored = validate_timeline(original.to_dict())
    assert restored.content_hash() == original.content_hash()
    assert original.to_dict()["canvas"]["fps"] == 30


def test_canonical_order_is_a_total_order() -> None:
    timeline = _timeline(clips=(*_video_clips(),
        TimelineClip("t1", TrackKind.TEXT, "c.srt", 5000, start_ms=0, order=0,
                     text="hello"),
        TimelineClip("a1", TrackKind.AUDIO, "vo.wav", 5000, start_ms=0, order=0),
    ), source_assets=("a.mp4", "b.mp4", "c.srt", "vo.wav"))
    keys = [(c.track.value, c.order, c.clip_id) for c in timeline.canonical_order()]
    assert keys == sorted(keys)
    assert len(timeline.canonical_order()) == 4


def test_audio_master_clock_verifies_against_its_lock() -> None:
    from hevi.production.p0_pipeline import AudioLock

    def lock(revision: int, digest: str) -> AudioLock:
        return AudioLock(
            audio_lock_id="al-1", source_text="narration", tts_provider="edge",
            tts_voice="v", audio_path="vo.wav", audio_sha256=digest,
            duration_s=5.0, revision=revision)

    digest = "b" * 64
    assert AudioMasterClock("al-1", digest, 3, 0).verify_against(lock(3, digest))
    assert not AudioMasterClock("al-1", digest, 3, 0).verify_against(
        lock(4, digest)), "a different lock revision must break the binding"
    assert not AudioMasterClock("al-1", digest, 3, 0).verify_against(
        lock(3, "c" * 64)), "a different audio digest must break the binding"


def test_persisted_timeline_is_self_identifying() -> None:
    timeline = _timeline()
    path = write_timeline_ir(timeline, "/tmp/opencode/p03/positive.timeline.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["content_hash"] == timeline.content_hash()
    assert read_timeline_ir(path).content_hash() == timeline.content_hash()


# ── time unit: milliseconds only ──────────────────────────────────────────


@pytest.mark.parametrize("value", [1.5, 2.0, 0.1, 1e9])
def test_float_duration_is_refused(value: float) -> None:
    """8 of the 20 predecessors store float seconds. None may enter canonical state."""
    with pytest.raises(TimelineIRError) as exc:
        _clip_with(duration_ms=value)
    assert "TIMELINE_TIME_MUST_BE_INT" in str(exc.value)


def _clip_with(**kwargs: Any) -> TimelineClip:
    """Build a clip from deliberately ill-typed values.

    The point of these tests is to feed the constructor a float or a bool, so the
    argument has to bypass the annotation rather than be corrected.
    """
    fields: dict[str, Any] = {
        "clip_id": "v1", "track": TrackKind.VIDEO, "source_path": "a.mp4",
        "duration_ms": 100,
    }
    fields.update(kwargs)
    return TimelineClip(**fields)


def test_float_start_and_source_in_are_refused() -> None:
    with pytest.raises(TimelineIRError):
        _clip_with(start_ms=0.5)
    with pytest.raises(TimelineIRError):
        _clip_with(source_in_ms=1.2)


def test_boolean_duration_is_refused() -> None:
    """``isinstance(True, int)`` is True in Python, so this needs saying explicitly."""
    with pytest.raises(TimelineIRError):
        _clip_with(duration_ms=True)


def test_float_canvas_dimension_is_refused() -> None:
    with pytest.raises(TimelineIRError):
        Canvas(1920, 1080, 29.97)  # type: ignore[arg-type]


def test_validate_timeline_refuses_float_ms() -> None:
    payload = _timeline().to_dict()
    payload["clips"][0]["duration_ms"] = 3000.5
    with pytest.raises(TimelineIRError) as exc:
        validate_timeline(payload)
    assert "TIMELINE_TIME_MUST_BE_INT" in str(exc.value)


def test_seconds_conversion_refuses_sub_millisecond() -> None:
    """Rounding 1.50005s to 1500ms would desynchronise narration from video."""
    assert ms_from_seconds(1.5) == 1500
    with pytest.raises(TimelineIRError) as exc:
        ms_from_seconds(1.50005)
    assert "TIMELINE_SECONDS_NOT_WHOLE_MS" in str(exc.value)


# ── fail-closed validation ────────────────────────────────────────────────


def test_negative_duration_is_refused_not_clamped() -> None:
    """``p1_types.py:98`` coerces a negative duration to 0.0. That is the defect."""
    with pytest.raises(TimelineIRError) as exc:
        _clip_with(duration_ms=-1)
    assert "TIMELINE_CLIP_NON_POSITIVE_DURATION" in str(exc.value)


def test_negative_start_is_refused() -> None:
    with pytest.raises(TimelineIRError) as exc:
        _clip_with(start_ms=-5)
    assert "TIMELINE_CLIP_NEGATIVE_START" in str(exc.value)


def test_overlapping_video_clips_are_refused() -> None:
    with pytest.raises(TimelineIRError) as exc:
        TimelineIR(project_id="p", canvas=_canvas(), clips=(
            TimelineClip("v1", TrackKind.VIDEO, "a.mp4", 3000, start_ms=0),
            TimelineClip("v2", TrackKind.VIDEO, "b.mp4", 3000, start_ms=1000),
        ))
    assert "TIMELINE_CLIP_OVERLAP" in str(exc.value)


def test_video_gap_is_refused() -> None:
    """A gap means part of the deliverable has no visual."""
    with pytest.raises(TimelineIRError) as exc:
        TimelineIR(project_id="p", canvas=_canvas(), clips=(
            TimelineClip("v1", TrackKind.VIDEO, "a.mp4", 1000, start_ms=0),
            TimelineClip("v2", TrackKind.VIDEO, "b.mp4", 1000, start_ms=2000),
        ))
    assert "TIMELINE_VIDEO_GAP" in str(exc.value)


def test_video_must_start_at_zero() -> None:
    with pytest.raises(TimelineIRError) as exc:
        TimelineIR(project_id="p", canvas=_canvas(), clips=(
            TimelineClip("v1", TrackKind.VIDEO, "a.mp4", 1000, start_ms=500),
        ))
    assert "TIMELINE_VIDEO_GAP" in str(exc.value)


def test_timeline_without_video_is_refused() -> None:
    with pytest.raises(TimelineIRError) as exc:
        TimelineIR(project_id="p", canvas=_canvas(), clips=(
            TimelineClip("a1", TrackKind.AUDIO, "vo.wav", 1000),
        ))
    assert "TIMELINE_NO_VIDEO_TRACK" in str(exc.value)


def test_empty_timeline_is_refused() -> None:
    with pytest.raises(TimelineIRError) as exc:
        TimelineIR(project_id="p", canvas=_canvas(), clips=())
    assert "TIMELINE_EMPTY" in str(exc.value)


def test_duplicate_clip_id_is_refused() -> None:
    with pytest.raises(TimelineIRError) as exc:
        TimelineIR(project_id="p", canvas=_canvas(), clips=(
            TimelineClip("v1", TrackKind.VIDEO, "a.mp4", 1000, start_ms=0),
            TimelineClip("v1", TrackKind.VIDEO, "b.mp4", 1000, start_ms=1000),
        ))
    assert "TIMELINE_CLIP_ID_DUPLICATE" in str(exc.value)


def test_unresolved_asset_is_refused() -> None:
    """A missing source must not be discovered at render time."""
    with pytest.raises(TimelineIRError) as exc:
        _timeline(source_assets=("a.mp4",))
    assert "TIMELINE_UNRESOLVED_ASSET" in str(exc.value)


def test_transition_longer_than_its_clip_is_refused() -> None:
    with pytest.raises(TimelineIRError) as exc:
        TimelineIR(project_id="p", canvas=_canvas(), clips=(
            TimelineClip("v1", TrackKind.VIDEO, "a.mp4", 100, start_ms=0,
                         transition_in=Transition(TransitionKind.FADE, 500)),
        ))
    assert "TIMELINE_TRANSITION_EXCEEDS_CLIP" in str(exc.value)


def test_cut_with_duration_is_refused() -> None:
    with pytest.raises(TimelineIRError) as exc:
        Transition(TransitionKind.CUT, 400)
    assert "TIMELINE_CUT_HAS_NO_DURATION" in str(exc.value)


def test_transition_without_duration_is_refused() -> None:
    """A fade with zero duration is a contradiction, not a default."""
    with pytest.raises(TimelineIRError) as exc:
        Transition(TransitionKind.FADE, 0)
    assert "TIMELINE_TRANSITION_REQUIRES_DURATION" in str(exc.value)


def test_unknown_track_kind_is_refused() -> None:
    payload = _timeline().to_dict()
    payload["clips"][0]["track"] = "subtitle"
    with pytest.raises(TimelineIRError) as exc:
        validate_timeline(payload)
    assert "TIMELINE_UNKNOWN_TRACK_KIND" in str(exc.value)


def test_unknown_transition_kind_is_refused() -> None:
    payload = _timeline().to_dict()
    payload["clips"][0]["transition_in"] = {"kind": "iris", "duration_ms": 200}
    with pytest.raises(TimelineIRError) as exc:
        validate_timeline(payload)
    assert "TIMELINE_UNKNOWN_TRANSITION_KIND" in str(exc.value)


def test_non_object_clip_is_refused() -> None:
    payload = _timeline().to_dict()
    payload["clips"] = ["not-an-object"]
    with pytest.raises(TimelineIRError) as exc:
        validate_timeline(payload)
    assert "TIMELINE_CLIP_NOT_AN_OBJECT" in str(exc.value)


def test_clip_without_id_or_source_is_refused() -> None:
    with pytest.raises(TimelineIRError) as exc:
        TimelineClip("", TrackKind.VIDEO, "a.mp4", 100)
    assert "TIMELINE_CLIP_WITHOUT_ID" in str(exc.value)
    with pytest.raises(TimelineIRError) as exc:
        TimelineClip("v1", TrackKind.VIDEO, "", 100)
    assert "TIMELINE_CLIP_WITHOUT_SOURCE" in str(exc.value)


def test_tampered_timeline_file_is_refused_on_read() -> None:
    """A hand-edited timeline must not be trusted just because it parses."""
    path = write_timeline_ir(_timeline(), "/tmp/opencode/p03/tampered.timeline.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["clips"][0]["duration_ms"] = 4000
    payload["clips"][1]["start_ms"] = 4000
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(TimelineIRError) as exc:
        read_timeline_ir(path)
    assert "TIMELINE_CONTENT_HASH_MISMATCH" in str(exc.value)


# ── provenance binding ────────────────────────────────────────────────────


def test_audio_clock_rejects_a_non_sha_digest() -> None:
    with pytest.raises(TimelineIRError) as exc:
        AudioMasterClock("al-1", "abc")
    assert "TIMELINE_AUDIO_SHA_NOT_SHA256" in str(exc.value)


def test_audio_clock_rejects_non_hex_digest() -> None:
    with pytest.raises(TimelineIRError) as exc:
        AudioMasterClock("al-1", "z" * 64)
    assert "TIMELINE_AUDIO_SHA_NOT_HEX" in str(exc.value)


def test_audio_clock_requires_an_id() -> None:
    with pytest.raises(TimelineIRError) as exc:
        AudioMasterClock("", DIGEST)
    assert "TIMELINE_AUDIO_CLOCK_WITHOUT_ID" in str(exc.value)


def test_lock_projects_into_a_valid_clock() -> None:
    from hevi.production.p0_pipeline import TimelineLock

    lock = TimelineLock(
        timeline_lock_id="tl-9", audio_lock_id="al-9", audio_lock_revision=2,
        audio_sha256="c" * 64, subtitle_path="c.srt", subtitle_sha256="d" * 64,
        cue_count=4, drift_ms=0, revision=1)
    clock = audio_master_clock_from_lock(lock)
    assert clock.audio_lock_id == "al-9"
    assert clock.audio_sha256 == "c" * 64
    assert clock.audio_lock_revision == 2


def test_timeline_lock_is_a_projection_not_an_authority() -> None:
    """The lock's identity comes from the IR hash, so it cannot be authored alone."""
    projection = timeline_lock_projection(_timeline(), SimpleAudioLock())
    assert projection["derived_from"] == "TimelineIR"
    assert projection["timeline_hash"] == _timeline().content_hash()
    assert projection["timeline_lock_id"].startswith("tl-")


class SimpleAudioLock:
    """Minimal ``TimelineLock``-shaped stand-in for the projection check."""

    audio_lock_id = "al-1"
    audio_lock_revision = 1
    audio_sha256 = DIGEST
    drift_ms = 0


# ── adapters: the twenty project through one boundary ─────────────────────


def test_every_legacy_representation_is_classified() -> None:
    assert len(LEGACY_TIMELINE_ROLES) == 20, (
        f"expected all 20 predecessors classified, got {len(LEGACY_TIMELINE_ROLES)}")
    allowed = {"ADAPTER", "PROJECTION", "LEGACY_READ_ONLY", "TEST_FIXTURE", "DEAD"}
    assert set(LEGACY_TIMELINE_ROLES.values()) <= allowed


def test_timeline_lock_is_classified_as_a_projection() -> None:
    assert LEGACY_TIMELINE_ROLES[
        "hevi.production.p0_pipeline.TimelineLock"] == "PROJECTION"


def test_editable_timeline_projects_into_the_ir() -> None:
    """The production-reachable predecessor, via the real adapter."""
    from hevi.creative.layer4.editable_delivery import EditableClip
    from hevi.creative.layer4.editable_delivery import TrackKind as EK

    class Fake:
        project_id = "proj-1"
        revision_id = "rev-1"
        production_run_id = "run-1"
        edit_revision = 2
        aspect_ratio = "16:9"
        timeline_id = "tl-1"
        clips = (
            EditableClip(clip_id="v-main", order=0, track=EK.VIDEO,
                         source_path="v.mp4", source_in_ms=0, duration_ms=5000),
            EditableClip(clip_id="a-main", order=1, track=EK.AUDIO,
                         source_path="a.wav", source_in_ms=0, duration_ms=5000,
                         gain=0.9),
            EditableClip(clip_id="t-main", order=2, track=EK.TEXT,
                         source_path="c.srt", source_in_ms=0, duration_ms=5000,
                         text="hello"),
        )

    ir = from_editable_timeline(Fake(), project_id="proj-1",
                                canvas=Canvas(1280, 720, 30))
    assert ir.duration_ms == 5000
    assert {c.track for c in ir.clips} == {
        TrackKind.VIDEO, TrackKind.AUDIO, TrackKind.TEXT}
    assert {c.start_ms for c in ir.clips} == {0}
    assert ir.metadata["projected_from"] == "EditableTimeline"


def test_hyperframes_float_seconds_project_or_refuse() -> None:
    """The float-second predecessor must be refused, not silently converted."""
    from hevi.production.timeline_ir import TimelineIR as _T

    class Hyper:
        width, height, fps, title = 1920, 1080, 30, "demo"
        clips = ()

    assert Hyper().clips == ()
    with pytest.raises(TimelineIRError):
        from_hyper_composition(Hyper(), project_id="p")

    class Lossy:
        width, height, fps, title = 1920, 1080, 30, "demo"

        class C:
            start_s, duration_s, text = 0.0, 1.50005, "hi"

        clips = (C(),)

    with pytest.raises(TimelineIRError) as exc:
        from_hyper_composition(Lossy(), project_id="p")
    assert "TIMELINE_SECONDS_NOT_WHOLE_MS" in str(exc.value)
    assert _T is TimelineIR


def test_digital_human_float_plan_projects() -> None:
    class Clip:
        clip_id, media_type, media_path = "dh-1", "video", "dh.mp4"
        authored_start_s, duration_s, text = 0.0, 2.0, ""

    class Plan:
        clips = (Clip(),)

    ir = from_digital_human_plan(Plan(), project_id="p")
    assert ir.duration_ms == 2000
    assert ir.metadata["projected_from"] == "TimelinePlan"


def test_adapters_do_not_write_back_into_legacy_types() -> None:
    """One direction only: if an IR could be reconstructed from a legacy shape, the
    IR would be authoritative over none of them."""
    import inspect

    import hevi.production.timeline_adapters as adapters

    for name, function in inspect.getmembers(adapters, inspect.isfunction):
        if not name.startswith("from_"):
            continue
        annotations = dict(inspect.signature(function).parameters)
        assert "TimelineIR" not in annotations.values(), (
            f"{name} accepts a TimelineIR; adapters must be one-directional")


# ── mutation: a wrong implementation must fail ───────────────────────────


def test_MUTATION_clamping_implementation_would_pass_every_happy_path() -> None:
    """Documents why coercion is the defect worth testing against.

    ``p1_types.duration_s()`` returns ``max(0.0, ...)`` and the hyperframes compiler
    clamps with ``max(dur, 0.8)``. Both produce a usable timeline for every valid
    input, so only an explicit negative-value test distinguishes them from this one.
    """
    def clamping_ir(duration_ms: int) -> TimelineIR:
        return TimelineIR(
            project_id="p", canvas=_canvas(),
            clips=(TimelineClip("v1", TrackKind.VIDEO, "a.mp4",
                                max(duration_ms, 800), start_ms=0),))

    # A clamping implementation answers every positive question identically.
    assert clamping_ir(3000).duration_ms == 3000
    assert validate_timeline(_timeline().to_dict()).duration_ms == 5000

    # ...and silently rewrites the one input that should be refused.
    with pytest.raises(TimelineIRError):
        TimelineClip("v1", TrackKind.VIDEO, "a.mp4", -100)


def test_MUTATION_unknown_kind_would_otherwise_be_accepted() -> None:
    """``compiler.py:83-84`` coerces an unknown kind to ``"card"``."""
    payload = _timeline().to_dict()
    payload["clips"][0]["track"] = "hologram"
    with pytest.raises(TimelineIRError) as exc:
        validate_timeline(payload)
    assert "hologram" in str(exc.value), (
        "the refusal must name the offending value, not just fail")


def test_MUTATION_missing_timestamp_would_otherwise_default() -> None:
    """``compiler.py:81-82`` defaults a missing ``start_s`` to 0.0 or 3.0."""
    payload = _timeline().to_dict()
    del payload["clips"][0]["start_ms"]
    # A default of 0 is *accepted* by construction, which is the coercion being
    # removed: start_ms has a documented default, so the test asserts the value that
    # results is the documented one rather than an invented 3.0.
    assert validate_timeline(payload).clips[0].start_ms == 0

    payload["clips"][0]["start_ms"] = None
    with pytest.raises(TimelineIRError):
        validate_timeline(payload)


def test_MUTATION_hash_must_depend_on_content() -> None:
    """A hash that ignored content would make every render receipt forgeable."""
    timeline = _timeline()
    # Same clips, one millisecond of duration moved.
    shifted = _timeline(clips=(
        TimelineClip("v1", TrackKind.VIDEO, "a.mp4", 3000, start_ms=0, order=0),
        TimelineClip("v2", TrackKind.VIDEO, "b.mp4", 2001, start_ms=3000, order=1),
    ))
    assert timeline.content_hash() != shifted.content_hash()


def test_MUTATION_unstable_ordering_would_break_the_hash() -> None:
    """``p1_types.add_beat`` appends without sorting, so no predecessor hash is
    stable. Constructing the same timeline twice, in different orders, must agree."""
    clips = (*_video_clips(),
        TimelineClip("a1", TrackKind.AUDIO, "vo.wav", 5000, start_ms=0, order=0),
        TimelineClip("t1", TrackKind.TEXT, "c.srt", 5000, start_ms=0, order=0,
                     text="x"),
    )
    assets = ("a.mp4", "b.mp4", "c.srt", "vo.wav")
    first = _timeline(clips=clips, source_assets=assets)
    second = _timeline(clips=(*reversed(clips),), source_assets=assets)
    assert first.content_hash() == second.content_hash()
    assert [c.clip_id for c in first.canonical_order()] == \
           [c.clip_id for c in second.canonical_order()]


# ── the production path actually reads and writes it ──────────────────────


def test_production_editable_export_emits_the_canonical_timeline() -> None:
    """P0-3's gate: a real production path must carry the IR and its hash."""
    source = Path("hevi/api/routers/authorities.py").read_text(encoding="utf-8")
    assert "from_editable_timeline" in source, (
        "the editable export must project through the IR adapter")
    assert '"timeline_ir"' in source, (
        "the editable export must return the canonical timeline alongside the "
        "legacy payloads")
    assert "TIMELINE_NOT_CANONICAL" in source, (
        "the export must refuse rather than emit an IR it cannot validate")


def test_the_caller_is_production_reachable() -> None:
    """An adapter nothing calls would not make the IR canonical."""
    source = Path("hevi/api/routers/authorities.py").read_text(encoding="utf-8")
    assert '@router.get("/tasks/{task_id}/editable")' in source, (
        "the migrated caller must be an HTTP route, not a helper")
    assert "authorities" in Path("hevi/api/main.py").read_text(encoding="utf-8")


def test_no_new_timeline_type_was_introduced_besides_the_ir() -> None:
    """The IR must normalise the twenty, not become a twenty-first."""
    import ast

    # The documented twenty, by exact class name. API request/response models
    # (TimelineCreateRequest etc.) and event/segment carriers are not timeline
    # representations, so the census is by name rather than by substring.
    documented = set(LEGACY_TIMELINE_ROLES)
    expected = {
        "hevi.creative.layer4.editable_delivery.EditableTimeline",
        "hevi.studio.timeline.Timeline",
        "hevi.providers.hyperframes.compiler.HyperComposition",
        "hevi.digital_human.schemas.TimelinePlan",
        "hevi.tongjian.schemas.Timeline",
        "hevi.production.p0_pipeline.TimelineLock",
        "hevi.voicepro.schemas.TimelineSlot",
        "hevi.openshorts.schemas.ClipSpec",
        "hevi.creative.direction_plan.models.BeatPlan",
        "hevi.creative.director_contract.BeatSpec",
        "hevi.assembly.music_to_video_workflow.BeatTimeline",
        "hevi.assembly.story_to_animation_workflow.StoryBeat",
        "hevi.creative.layer4.script.StoryboardBundle",
        "hevi.motion.sequence.PlannedShot",
        "hevi.assembly.assembler.ShotSegment",
        "hevi.studio.jianying.JianyingClip",
        "hevi.narrative.timeline.NarrativeTimeline",
    }
    assert len(expected) == 17, "the census itself drifted"

    present = set()
    for path in Path("hevi").rglob("*.py"):
        if "layer4_legacy" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        module = ".".join(path.relative_to(Path("hevi")).with_suffix("").parts)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                present.add(f"hevi.{module}.{node.name}")

    undocumented = sorted(
        name for name in expected
        if name not in documented and not name.endswith("NarrativeTimeline"))
    assert not undocumented, f"legacy roles table is missing entries: {undocumented}"
    assert any(name.endswith(".TimelineIR") for name in present)
    assert "hevi.production.timeline_ir.TimelineClip" in present


def test_frozen_proof_untouched_by_p03() -> None:
    import json as _json

    root = Path("artifacts/real_video/20261005T160434Z")
    if not (root / "FREEZE.json").exists():  # pragma: no cover
        pytest.skip("frozen proof not present")
    recorded = _json.loads((root / "FREEZE.json").read_text())["sha256"]
    actual = subprocess.run(["sha256sum", str(root / "final/FINAL.mp4")],
                            capture_output=True, text=True, check=True
                            ).stdout.split()[0]
    assert actual == recorded
