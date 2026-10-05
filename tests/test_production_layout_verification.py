"""P11 layout semantic verification tests.

The central case is :func:`test_MUTATION_split_declared_but_one_source_delivered`.
It renders a plan that declares ``split`` and then hands the verifier an artifact
built from a *single* source. Every field of the plan is well-typed, V0–V3 would
accept the file, and the declaration is still false. Only a pixel-level check can
catch it, which is why that check exists.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hevi.openshorts.schemas import ReframingMode
from hevi.production.layout_plan import (
    CompositionError,
    CompositionSpec,
    LayoutParameters,
    plan_layout,
    render_layout,
)
from hevi.production.layout_verification import (
    LayoutSemanticError,
    verify_layout_semantics,
)
from hevi.production.p6.schema import SpeakerVisibility
from hevi.production.presenter import PresenterScale
from hevi.production.reframe import SubjectSample, SubjectTrack, TrackSource

MEDIA = Path("artifacts/real_video/20261005T160434Z/artifacts")
PRIMARY = MEDIA / "scene_broll_720p.mp4"
SECONDARY = MEDIA / "scene_interview_720p.mp4"
W, H = 1280, 720
OUT = Path("/tmp/opencode/p11_verify")


def _track(n: int = 8) -> SubjectTrack:
    return SubjectTrack(
        samples=tuple(
            SubjectSample(t_s=float(i) * 2.0, cx=0.30 + 0.05 * i, cy=0.45,
                          radius=0.10, source=TrackSource.INJECTED_DETECTOR)
            for i in range(n)),
        detector="p11-verify", duration_s=float(n) * 2.0)


def _spec(mode: ReframingMode, scale=PresenterScale.MEDIUM,
          vis=SpeakerVisibility.FULL, **kw) -> CompositionSpec:
    return CompositionSpec(
        presenter_scale=scale, speaker_visibility=vis, layout_mode=mode,
        parameters=LayoutParameters(aspect_ratio="16:9", output_width=W,
                                   output_height=H, **kw),
        shot_id="verify")


def _render_general(path: Path, primary: Path = PRIMARY) -> Path:
    plan = plan_layout(_spec(ReframingMode.GENERAL), primary_source=str(primary),
                       source_width=W, source_height=H)
    return render_layout(plan, primary=primary, out=path)


# ── Regression: honest artifacts verify ──────────────────────────────────


def test_general_artifact_verifies() -> None:
    out = _render_general(OUT / "general.mp4")
    result = verify_layout_semantics(
        plan_layout(_spec(ReframingMode.GENERAL), primary_source=str(PRIMARY),
                    source_width=W, source_height=H),
        artifact=out, primary=PRIMARY)
    assert result.passed, result.to_dict()
    names = {c.name for c in result.checks}
    assert "delivered_geometry_matches_planned_crop" in names
    assert "frames_are_live_not_frozen" in names


def test_split_artifact_verifies_both_halves() -> None:
    plan = plan_layout(_spec(ReframingMode.SPLIT), primary_source=str(PRIMARY),
                       secondary_source=str(SECONDARY), source_width=W, source_height=H)
    out = render_layout(plan, primary=PRIMARY, secondary=SECONDARY,
                        out=OUT / "split.mp4")
    result = verify_layout_semantics(plan, artifact=out, primary=PRIMARY,
                                     secondary=SECONDARY)
    assert result.passed, result.to_dict()
    assert all("split_halves_match_named_sources" in c.name for c in result.checks)


def test_track_artifact_verifies() -> None:
    plan = plan_layout(_spec(ReframingMode.TRACK, PresenterScale.FULL,
                             SpeakerVisibility.DOMINANT),
                       primary_source=str(PRIMARY), subject_track=_track(),
                       source_width=W, source_height=H)
    out = render_layout(plan, primary=PRIMARY, out=OUT / "track.mp4")
    result = verify_layout_semantics(plan, artifact=out, primary=PRIMARY)
    assert result.passed, result.to_dict()
    assert "render_is_not_a_centre_crop" in {c.name for c in result.checks}


# ── Mutation: semantic lies must be caught ───────────────────────────────


def test_MUTATION_split_declared_but_one_source_delivered() -> None:
    """A plan that says split, rendered from one source, must fail.

    This is the lie V0–V3 cannot see: the file decodes, the aspect is right, the
    duration is right, the plan is well-typed. Only comparing each half against
    each source reveals that the right half is not the secondary.
    """
    plan = plan_layout(_spec(ReframingMode.SPLIT), primary_source=str(PRIMARY),
                       secondary_source=str(SECONDARY), source_width=W, source_height=H)
    # Deliver an artifact made from ONE source, padded to look split-ish.
    lie = OUT / "split_lie.mp4"
    lie.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(PRIMARY),
         "-i", str(PRIMARY),
         "-filter_complex",
         "[0:v]scale=640:360,setsar=1[l];[1:v]scale=640:360,setsar=1[r];"
         "[l][r]hstack=inputs=2[out]",
         "-map", "[out]", "-t", "8", "-c:v", "libx264", "-preset", "veryfast",
         "-pix_fmt", "yuv420p", str(lie)],
        check=True, capture_output=True)
    result = verify_layout_semantics(plan, artifact=lie, primary=PRIMARY,
                                     secondary=SECONDARY)
    assert not result.passed, (
        "a split plan delivered with both halves from one source must not verify")
    failed = [c for c in result.checks if not c.passed]
    assert failed, result.to_dict()
    # The evidence must show which half was wrong, not merely that something was.
    ev = failed[0].evidence
    assert ev["right_mad_to_secondary"] > ev["right_mad_to_primary"]


def test_MUTATION_frozen_frame_is_not_a_live_render() -> None:
    """A single still image stretched to the duration is not a delivered layout."""
    still = OUT / "still.png"
    still.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-ss", "2", "-i", str(PRIMARY), "-frames:v", "1", str(still)],
                   check=True, capture_output=True)
    frozen = OUT / "frozen.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-loop", "1", "-i", str(still), "-t", "8",
                    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt",
                    "yuv420p", str(frozen)],
                   check=True, capture_output=True)
    result = verify_layout_semantics(
        plan_layout(_spec(ReframingMode.GENERAL), primary_source=str(PRIMARY),
                    source_width=W, source_height=H),
        artifact=frozen, primary=PRIMARY)
    assert not result.passed
    assert "frames_are_live_not_frozen" in {c.name for c in result.checks}


def test_MUTATION_track_plan_claiming_containment_it_lacks() -> None:
    """A plan that warns the subject leaves the frame must not verify as contained.

    The verifier reads containment from the plan P10 produced, not from the
    spec's intent, so an unachievable claim surfaces as a failure.
    """
    loose = SubjectTrack(
        samples=tuple(
            # Wanders the full width with a large radius: always inside the frame,
            # but never containable by a tight crop.
            SubjectSample(t_s=float(i) * 2.0, cx=0.05 + 0.90 * i / 7.0, cy=0.5,
                          radius=0.30, source=TrackSource.INJECTED_DETECTOR)
            for i in range(8)),
        detector="loose", duration_s=16.0)
    plan = plan_layout(_spec(ReframingMode.TRACK, PresenterScale.FULL,
                             SpeakerVisibility.DOMINANT),
                       primary_source=str(PRIMARY), subject_track=loose,
                       source_width=W, source_height=H)
    assert not plan.reframe_plan.subject_contained()  # type: ignore[union-attr]
    assert any("SUBJECT_NOT_CONTAINED" in w for w in plan.warnings)
    out = render_layout(plan, primary=PRIMARY, out=OUT / "track_loose.mp4")
    result = verify_layout_semantics(plan, artifact=out, primary=PRIMARY)
    assert not result.passed
    assert "subject_contained_as_planned" in {c.name for c in result.checks}


# ── Fail-closed on unmeasurable checks ───────────────────────────────────


def test_missing_artifact_raises_rather_than_passing() -> None:
    plan = plan_layout(_spec(ReframingMode.GENERAL), primary_source=str(PRIMARY),
                       source_width=W, source_height=H)
    with pytest.raises(LayoutSemanticError) as exc:
        verify_layout_semantics(plan, artifact=OUT / "nope.mp4", primary=PRIMARY)
    assert "ARTIFACT_MISSING" in str(exc.value)


def test_split_verification_without_second_source_raises() -> None:
    """Not measurable is not a pass."""
    plan = plan_layout(_spec(ReframingMode.SPLIT), primary_source=str(PRIMARY),
                       secondary_source=str(SECONDARY), source_width=W, source_height=H)
    with pytest.raises(LayoutSemanticError) as exc:
        verify_layout_semantics(plan, artifact=OUT / "general.mp4",
                                primary=PRIMARY, secondary=None)
    assert "SPLIT_REQUIRES_SECOND_SOURCE_FOR_VERIFICATION" in str(exc.value)


def test_verification_refuses_a_plan_that_cannot_be_rendered() -> None:
    """Verification must not resurrect a plan the planner already refused."""
    with pytest.raises(CompositionError):
        plan_layout(_spec(ReframingMode.TRACK, PresenterScale.FULL,
                          SpeakerVisibility.DOMINANT),
                    primary_source=str(PRIMARY), subject_track=None,
                    source_width=W, source_height=H)