"""P11 composition contract tests.

Two kinds of test live here and the distinction is the point:

* **Regression** — the contract behaves as specified.
* **Mutation** — a deliberately *wrong* implementation must fail. A test that only
  checks the happy path proves nothing about a fail-closed contract: the dangerous
  implementations are the ones that silently degrade, and only a test that feeds
  them invalid input can tell them apart from a correct one.

The mutation tests below are the P11 §9 cases, and each one asserts on the specific
error code so that a wrong-but-plausible failure cannot pass by accident.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hevi.openshorts.schemas import ReframingMode
from hevi.production.layout_plan import (
    CompositionError,
    CompositionSpec,
    LayoutParameters,
    LayoutRegion,
    compile_filter_graph,
    plan_layout,
    render_layout,
)
from hevi.production.p6.schema import SpeakerVisibility
from hevi.production.presenter import PresenterScale
from hevi.production.reframe import SubjectSample, SubjectTrack, TrackSource

MEDIA = Path("artifacts/real_video/20261005T160434Z/artifacts")
PRIMARY = MEDIA / "scene_broll_720p.mp4"
SECONDARY = MEDIA / "scene_interview_720p.mp4"
W, H = 1280, 720


def _track(n: int = 8) -> SubjectTrack:
    return SubjectTrack(
        samples=tuple(
            SubjectSample(t_s=float(i) * 2.0, cx=0.30 + 0.05 * i, cy=0.45,
                          radius=0.10, source=TrackSource.INJECTED_DETECTOR)
            for i in range(n)
        ),
        detector="p11-test", duration_s=float(n) * 2.0)


def _spec(mode: ReframingMode, scale=PresenterScale.MEDIUM,
          vis=SpeakerVisibility.FULL, **kw) -> CompositionSpec:
    params = LayoutParameters(aspect_ratio="16:9", output_width=W, output_height=H,
                              **kw)
    return CompositionSpec(presenter_scale=scale, speaker_visibility=vis,
                           layout_mode=mode, parameters=params, shot_id="t")


# ── Regression: the contract as specified ────────────────────────────────


def test_spec_records_the_three_canonical_owners() -> None:
    """Every plan states where its vocabulary came from."""
    d = _spec(ReframingMode.GENERAL).to_dict()
    owners = d["vocabulary_owners"]
    assert "presenter.py" in owners["presenter_scale"]
    assert "p6/schema.py" in owners["speaker_visibility"]
    assert "openshorts/schemas.py" in owners["layout_mode"]
    # No dimension was silently merged into another.
    assert d["presenter_scale"] == "MEDIUM"
    assert d["speaker_visibility"] == "FULL"
    assert d["layout_mode"] == "general"


def test_no_fourth_vocabulary_was_introduced() -> None:
    """The module must reuse the existing enums, not define new members.

    This is Gate A expressed as a test: if someone adds a local enum to sidestep a
    conflict, the import identities below stop matching.
    """
    import hevi.production.layout_plan as comp

    assert comp.PresenterScale is PresenterScale
    assert comp.SpeakerVisibility is SpeakerVisibility
    assert comp.ReframingMode is ReframingMode
    # Member sets are exactly the repository's, unchanged.
    assert {m.value for m in PresenterScale} == {"FULL", "MEDIUM", "PIP", "HIDDEN"}
    assert {m.value for m in SpeakerVisibility} == {
        "DOMINANT", "FULL", "MEDIUM", "PIP", "HIDDEN"}
    assert {m.value for m in ReframingMode} == {"track", "general", "split"}


def test_all_three_dimensions_are_preserved_independently() -> None:
    """Prominence, visibility and geometry vary without collapsing together."""
    seen = set()
    for scale in PresenterScale:
        for vis in SpeakerVisibility:
            mode = ReframingMode.GENERAL
            try:
                spec = CompositionSpec(
                    presenter_scale=scale, speaker_visibility=vis, layout_mode=mode,
                    parameters=LayoutParameters(aspect_ratio="16:9"))
            except CompositionError:
                continue  # a genuinely contradictory pair, validated separately
            d = spec.to_dict()
            seen.add((d["presenter_scale"], d["speaker_visibility"], d["layout_mode"]))
    # If the three had collapsed, this would be far below the product of the sets.
    assert len(seen) >= 12


def test_plan_uses_normalised_canvas_coordinates() -> None:
    plan = plan_layout(_spec(ReframingMode.SPLIT, split_ratio=0.4),
                       primary_source="a.mp4", secondary_source="b.mp4",
                       source_width=W, source_height=H)
    assert plan.to_dict()["coordinate_system"] == "normalised_canvas_0_1"
    left, right = plan.regions
    assert (left.x, left.width) == (0.0, pytest.approx(0.4))
    assert right.x == pytest.approx(0.4)
    assert left.width + right.width == pytest.approx(1.0)


def test_normalised_coordinates_become_pixels_exactly_once() -> None:
    r = LayoutRegion(source="a", role="subject", x=0.25, y=0.5,
               width=0.5, height=0.5)
    assert r.to_px(W, H) == (320, 360, 640, 360)


def test_plan_is_deterministic() -> None:
    spec = _spec(ReframingMode.TRACK, PresenterScale.FULL, SpeakerVisibility.DOMINANT)
    a = plan_layout(spec, primary_source="a.mp4", subject_track=_track(),
                    source_width=W, source_height=H)
    b = plan_layout(spec, primary_source="a.mp4", subject_track=_track(),
                    source_width=W, source_height=H)
    assert a.fingerprint() == b.fingerprint()


def test_track_plan_consumes_the_p10_reframe_plan() -> None:
    plan = plan_layout(_spec(ReframingMode.TRACK, PresenterScale.FULL,
                             SpeakerVisibility.DOMINANT),
                       primary_source="a.mp4", subject_track=_track(),
                       source_width=W, source_height=H)
    assert plan.reframe_plan is not None
    assert plan.to_dict()["requires_reframe_plan"] is True
    assert plan.to_dict()["reframe_plan_present"] is True


def test_general_plan_needs_no_subject_track() -> None:
    """GENERAL declares no subject, so requiring a track would be over-strict."""
    plan = plan_layout(_spec(ReframingMode.GENERAL), primary_source="a.mp4",
                       source_width=W, source_height=H)
    assert plan.reframe_plan is None
    assert plan.to_dict()["requires_reframe_plan"] is False


def test_render_is_native_and_produces_the_canvas() -> None:
    """One ffmpeg invocation, no Python frame loop."""
    out = Path("/tmp/opencode/p11/test_general.mp4")
    plan = plan_layout(_spec(ReframingMode.GENERAL), primary_source=str(PRIMARY),
                       source_width=W, source_height=H)
    graph = compile_filter_graph(plan)
    assert "crop=" in graph and "[out]" in graph
    render_layout(plan, primary=PRIMARY, out=out)
    probe = json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
         "stream=width,height", "-of", "json", str(out)],
        capture_output=True, text=True, check=True).stdout)
    s = probe["streams"][0]
    assert (s["width"], s["height"]) == (W, H)


# ── Mutation: wrong implementations must fail (§9.1–§9.4) ──────────────


def test_MUTATION_track_without_track_must_not_centre_crop() -> None:
    """§9.1: a silent centre crop is the failure mode this phase exists to kill."""
    plan_spec = _spec(ReframingMode.TRACK, PresenterScale.FULL,
                      SpeakerVisibility.DOMINANT)
    with pytest.raises(CompositionError) as exc:
        plan_layout(plan_spec, primary_source="a.mp4", subject_track=None,
                    source_width=W, source_height=H)
    assert "REFRAME_PLAN_REQUIRED_BUT_ABSENT" in str(exc.value)


def test_MUTATION_split_without_second_source_must_fail() -> None:
    """§9.2: one source cannot honestly be described as a split."""
    with pytest.raises(CompositionError) as exc:
        plan_layout(_spec(ReframingMode.SPLIT), primary_source="a.mp4",
                    secondary_source=None, source_width=W, source_height=H)
    assert "SPLIT_REQUIRES_SECOND_SOURCE" in str(exc.value)


def test_MUTATION_out_of_bounds_region_must_fail() -> None:
    """§9.3: a region reaching past the canvas would be an off-frame inset."""
    with pytest.raises(CompositionError) as exc:
        LayoutRegion(source="a", role="subject", x=0.8, y=0.0, width=0.5,
               height=1.0)
    assert "REGION_OUT_OF_BOUNDS_X" in str(exc.value)
    with pytest.raises(CompositionError) as exc:
        LayoutRegion(source="a", role="subject", x=0.0, y=-0.1, width=0.5,
               height=1.0)
    assert "REGION_NEGATIVE_ORIGIN" in str(exc.value)


@pytest.mark.parametrize("bad", ["fullscreen", "PIP", "SCREENCAST", "", "TRACK"])
def test_MUTATION_unknown_vocabulary_member_must_fail(bad: str) -> None:
    """§9.4: including the real-but-relocated `fullscreen` and capitalised `TRACK`.

    A case-insensitive lookup would silently accept `TRACK`; an implementation that
    aliased the explainer LayoutMode would accept `fullscreen`. Both are wrong.
    """
    with pytest.raises(CompositionError) as exc:
        CompositionSpec(presenter_scale=PresenterScale.MEDIUM,
                        speaker_visibility=SpeakerVisibility.FULL,
                        layout_mode=bad,  # type: ignore[arg-type]
                        parameters=LayoutParameters(aspect_ratio="16:9"))
    assert "UNKNOWN_LAYOUT_MODE" in str(exc.value)


def test_MUTATION_contradictory_dimensions_must_fail() -> None:
    """The three dimensions may not contradict each other."""
    with pytest.raises(CompositionError) as exc:
        _spec(ReframingMode.TRACK, PresenterScale.HIDDEN, SpeakerVisibility.HIDDEN)
    assert "TRACK_REQUIRES_VISIBLE_PRESENTER" in str(exc.value)

    with pytest.raises(CompositionError) as exc:
        _spec(ReframingMode.GENERAL, PresenterScale.FULL, SpeakerVisibility.HIDDEN)
    assert "HIDDEN_SPEAKER_WITH_VISIBLE_SCALE" in str(exc.value)

    with pytest.raises(CompositionError) as exc:
        _spec(ReframingMode.GENERAL, PresenterScale.FULL, SpeakerVisibility.PIP)
    assert "PIP_SPEAKER_CANNOT_BE_FULLSCALE" in str(exc.value)


def test_MUTATION_split_gap_consuming_split_ratio_must_fail() -> None:
    """A gap that swallows the left region would render an empty half."""
    with pytest.raises(CompositionError) as exc:
        _spec(ReframingMode.SPLIT, split_ratio=0.3, gap=0.4)
    assert "SPLIT_GAP_CONSUMES_SPLIT_RATIO" in str(exc.value)


@pytest.mark.parametrize("kw,code", [
    ({"split_ratio": 0.0}, "INVALID_SPLIT_RATIO"),
    ({"split_ratio": 1.0}, "INVALID_SPLIT_RATIO"),
    ({"inset_scale": 0.0}, "INVALID_INSET_SCALE"),
    ({"safe_margin": 0.9}, "INVALID_SAFE_MARGIN"),
    ({"anchor": "middle"}, "INVALID_ANCHOR"),
])
def test_MUTATION_invalid_parameters_must_fail(kw: dict, code: str) -> None:
    with pytest.raises(CompositionError) as exc:
        LayoutParameters(**kw)
    assert code in str(exc.value)


def test_MUTATION_unknown_source_geometry_must_not_be_guessed() -> None:
    """Guessing source dimensions would silently change the crop."""
    with pytest.raises(CompositionError) as exc:
        plan_layout(_spec(ReframingMode.GENERAL), primary_source="a.mp4")
    assert "SOURCE_DIMENSIONS_REQUIRED" in str(exc.value)


def test_MUTATION_semantic_lie_is_detected_by_the_plan_not_the_schema() -> None:
    """§9.5's core: a well-formed plan can still assert something untrue.

    Declaring `DOMINANT` while rendering a small inset is well-formed at every
    layer that only checks types. The plan records what was actually requested, and
    a verification step comparing geometry against the declared scale is what has
    to reject it — so this test pins the signal such a verifier would read.
    """
    spec = _spec(ReframingMode.GENERAL, PresenterScale.FULL,
                 SpeakerVisibility.DOMINANT)
    plan = plan_layout(spec, primary_source="a.mp4", source_width=W, source_height=H)
    # Schema-level checks all pass: nothing here is malformed.
    assert plan.to_dict()["presenter_scale"] == "FULL"
    assert plan.to_dict()["speaker_visibility"] == "DOMINANT"
    # But GENERAL fills the whole canvas, so the frame carries no scale evidence
    # and a verifier must not read FULL out of it.
    assert len(plan.regions) == 1
    assert plan.regions[0].width == 1.0 and plan.regions[0].height == 1.0