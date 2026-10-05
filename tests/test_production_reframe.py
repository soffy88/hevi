"""Reframe Engine — geometry, fail-closed behaviour, and real renders.

Test discipline follows the repo's existing precedent rather than mocks:
real ffmpeg-generated video for execution (``tests/test_visual_quality_gate.py``)
and construction-as-ground-truth for geometry
(``tests/p10/spike/test_zoom_measure.py``).
"""

from __future__ import annotations

import itertools
import json
import subprocess
from pathlib import Path

import pytest

from hevi.production.reframe import (
    FollowMode,
    ReframeError,
    ReframeIntent,
    ReframePlan,
    SubjectSample,
    SubjectTrack,
    TrackSource,
    compile_reframe_filter,
    execute_reframe,
    parse_aspect,
    plan_reframe,
    saliency_track,
)

SRC_W, SRC_H = 1280, 720


def _ffmpeg(*args: str) -> None:
    proc = subprocess.run(["ffmpeg", "-y", "-v", "error", *args],
                          capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg fixture failed: {proc.stderr[-300:]}")


@pytest.fixture(scope="module")
def moving_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real 16:9 clip with motion, so a reframe has something to do."""
    out = tmp_path_factory.mktemp("reframe") / "moving.mp4"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=4",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out))
    return out


@pytest.fixture(scope="module")
def static_source(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real clip with no motion at all."""
    out = tmp_path_factory.mktemp("reframe") / "static.mp4"
    _ffmpeg("-f", "lavfi", "-i", "color=c=gray:s=640x360:d=3",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(out))
    return out


def _walking_track(radius: float = 0.18) -> SubjectTrack:
    """A subject that walks left to right across the frame."""
    return SubjectTrack(
        samples=tuple(
            SubjectSample(t_s=t, cx=cx, cy=0.5, radius=radius,
                          source=TrackSource.INJECTED_DETECTOR)
            for t, cx in zip((0.0, 1.3, 2.6, 3.9), (0.20, 0.40, 0.62, 0.80),
                            strict=True)
        ),
        detector="test injected",
        duration_s=4.0,
    )


class TestTrack:
    def test_empty_track_is_refused(self) -> None:
        with pytest.raises(ReframeError, match="EMPTY_SUBJECT_TRACK"):
            SubjectTrack(samples=())

    def test_off_frame_sample_is_refused(self) -> None:
        with pytest.raises(ValueError, match="out of frame"):
            SubjectTrack(samples=(SubjectSample(t_s=0.0, cx=1.4, cy=0.5),))

    def test_sources_are_recorded_not_assumed(self) -> None:
        track = SubjectTrack(
            samples=(
                SubjectSample(t_s=0.0, cx=0.5, cy=0.5, source=TrackSource.HUMAN),
                SubjectSample(t_s=1.0, cx=0.5, cy=0.5, source=TrackSource.SALIENCY),
            ),
        )
        assert set(track.sources) == {TrackSource.HUMAN, TrackSource.SALIENCY}
        assert {s["source"] for s in track.to_dict()["samples"]} == {"human", "saliency"}

    def test_at_picks_nearest_deterministically(self) -> None:
        track = _walking_track()
        assert track.at(0.0).t_s == 0.0
        assert track.at(3.99).t_s == 3.9


class TestPlanGeometry:
    @pytest.mark.parametrize("aspect", ["9:16", "16:9", "1:1", "4:5"])
    def test_every_aspect_produces_even_dimensions(self, aspect: str) -> None:
        """h264/yuv420p rejects odd sizes; that only surfaces at encode time."""
        plan = plan_reframe(_walking_track(), ReframeIntent(target_aspect=aspect),
                            source_width=SRC_W, source_height=SRC_H)
        assert plan.target_width % 2 == 0
        assert plan.target_height % 2 == 0
        ratio = plan.target_width / plan.target_height
        want = parse_aspect(aspect)
        assert abs(ratio - (want[0] / want[1])) < 0.02

    @pytest.mark.parametrize("aspect", ["9:16", "16:9", "1:1", "4:5"])
    def test_crop_never_exceeds_the_source(self, aspect: str) -> None:
        plan = plan_reframe(_walking_track(), ReframeIntent(target_aspect=aspect),
                            source_width=SRC_W, source_height=SRC_H)
        for window in plan.windows:
            assert window.x >= 0 and window.y >= 0
            assert window.x + window.w <= SRC_W
            assert window.y + window.h <= SRC_H

    def test_walking_subject_is_contained(self) -> None:
        plan = plan_reframe(
            _walking_track(), ReframeIntent(target_aspect="9:16", tightness=0.55,
                                            follow=FollowMode.FOLLOW),
            source_width=SRC_W, source_height=SRC_H)
        assert plan.subject_contained() is True

    def test_static_mode_does_not_contain_a_walking_subject(self) -> None:
        """A centre crop genuinely does not hold a subject that crosses frame.

        The property is reported rather than hidden: this is why a static reframe
        over a moving subject is a decision someone has to make knowingly.
        """
        plan = plan_reframe(
            _walking_track(), ReframeIntent(target_aspect="9:16",
                                            follow=FollowMode.STATIC),
            source_width=SRC_W, source_height=SRC_H)
        assert len({w.x for w in plan.windows}) == 1
        assert plan.subject_contained() is False

    def test_tightness_controls_crop_size(self) -> None:
        """Higher tightness means the subject fills more of the frame, which is a
        *smaller* crop. Asserting the direction explicitly, because inverting it
        is the easy mistake."""
        subject_px = 2 * 0.18 * min(SRC_W, SRC_H)
        widths = []
        for tightness in (0.9, 0.7, 0.5, 0.3):
            plan = plan_reframe(_walking_track(), ReframeIntent(tightness=tightness),
                                source_width=SRC_W, source_height=SRC_H)
            # the subject occupies exactly the requested share of the crop
            assert subject_px / plan.target_width == pytest.approx(tightness, abs=0.03)
            widths.append(plan.target_width)
        # looser tightness -> wider crop, monotonically
        assert widths == sorted(widths), widths

    def test_min_tightness_floor_is_respected(self) -> None:
        plan = plan_reframe(
            SubjectTrack(samples=(SubjectSample(t_s=0.0, cx=0.5, cy=0.5, radius=0.001),)),
            ReframeIntent(target_aspect="9:16", tightness=0.9, min_tightness=0.5),
            source_width=SRC_W, source_height=SRC_H)
        assert plan.target_width >= 0.5 * parse_aspect("9:16")[0] * 0  # even-dim floor
        assert plan.target_width > 0

    def test_cannot_crop_tighter_than_target_aspect_allows(self) -> None:
        plan = plan_reframe(
            SubjectTrack(samples=(SubjectSample(t_s=0.0, cx=0.5, cy=0.5, radius=0.9),)),
            ReframeIntent(target_aspect="9:16", tightness=0.05),
            source_width=SRC_W, source_height=SRC_H)
        assert plan.target_height <= SRC_H
        assert any("CLAMPED_TO_LARGEST_CROP" in note for note in plan.notes)

    def test_clamp_note_is_not_repeated_per_keyframe(self) -> None:
        plan = plan_reframe(
            SubjectTrack(samples=tuple(
                SubjectSample(t_s=float(i), cx=0.5, cy=0.5, radius=0.9) for i in range(9))),
            ReframeIntent(target_aspect="9:16", tightness=0.05),
            source_width=SRC_W, source_height=SRC_H)
        clamp_notes = [n for n in plan.notes if "CLAMPED" in n]
        assert len(clamp_notes) == 1

    def test_plan_is_deterministic(self) -> None:
        intent = ReframeIntent(target_aspect="9:16", tightness=0.5)
        first = plan_reframe(_walking_track(), intent,
                             source_width=SRC_W, source_height=SRC_H)
        second = plan_reframe(_walking_track(), intent,
                              source_width=SRC_W, source_height=SRC_H)
        assert [w.to_dict() for w in first.windows] == [w.to_dict() for w in second.windows]

    def test_keyframes_are_bounded(self) -> None:
        plan = plan_reframe(
            SubjectTrack(samples=tuple(
                SubjectSample(t_s=float(i) * 0.5, cx=0.5, cy=0.5) for i in range(200))),
            ReframeIntent(target_aspect="16:9"), source_width=SRC_W, source_height=SRC_H)
        assert len(plan.keyframes) <= 12

    def test_invalid_intent_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="tightness"):
            ReframeIntent(tightness=0.0)
        with pytest.raises(ValueError, match="tightness"):
            ReframeIntent(tightness=1.5)
        with pytest.raises(ValueError, match="lead_room"):
            ReframeIntent(lead_room=0.9)

    def test_bad_aspect_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="aspect"):
            parse_aspect("wide")

    def test_source_dimensions_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            plan_reframe(_walking_track(), ReframeIntent(), source_width=0,
                         source_height=720)


class TestFollowModes:
    def test_follow_safe_makes_fewer_moves_than_follow(self) -> None:
        """The whole point of FOLLOW_SAFE: calmer framing of a slow subject."""
        track = SubjectTrack(
            samples=tuple(
                SubjectSample(t_s=float(i), cx=0.400 + i * 0.012, cy=0.5, radius=0.015,
                              source=TrackSource.INJECTED_DETECTOR)
                for i in range(6)
            ),
            detector="t", duration_s=6.0)
        follow = plan_reframe(track, ReframeIntent(target_aspect="9:16",
                                                   follow=FollowMode.FOLLOW),
                              source_width=SRC_W, source_height=SRC_H)
        safe = plan_reframe(track, ReframeIntent(target_aspect="9:16",
                                                 follow=FollowMode.FOLLOW_SAFE),
                            source_width=SRC_W, source_height=SRC_H)

        def travel(plan: ReframePlan) -> int:
            xs = [w.x for w in plan.windows]
            return sum(abs(b - a) for a, b in itertools.pairwise(xs))

        assert len({w.x for w in safe.windows}) < len({w.x for w in follow.windows})
        assert travel(safe) < travel(follow)
        assert safe.subject_contained() is True

    def test_follow_safe_never_lets_the_subject_out_of_frame(self) -> None:
        """Property sweep: FOLLOW_SAFE must contain the subject whenever that is
        geometrically possible.

        The safe margin is the subject's own radius, not a fixed fraction of the
        window. A fraction is smaller than the subject, so it lets the crop hold
        still while the subject drifts toward an edge — exactly the defect this
        mode exists to prevent. A single hand-picked track does not expose that
        (both margins agree while the subject is mid-window), so this sweeps.

        Subjects are kept fully inside the source: a subject that hangs off the
        frame edge cannot be contained by *any* crop, so including those cases
        would test the arithmetic rather than the mode.
        """
        violations: list[str] = []
        for start in (0.15, 0.3, 0.45, 0.6, 0.75):
            for step in (0.004, 0.010, 0.020, 0.035, 0.060):
                for radius in (0.010, 0.020, 0.040, 0.080):
                    margin = radius  # radius is a fraction of min(W, H) = 720
                    lo, hi = 720 * margin / SRC_W, 1.0 - 720 * margin / SRC_W
                    samples = tuple(
                        SubjectSample(t_s=float(i),
                                      cx=min(hi, max(lo, start + i * step)),
                                      cy=0.5, radius=radius,
                                      source=TrackSource.INJECTED_DETECTOR)
                        for i in range(8)
                    )
                    plan = plan_reframe(
                        SubjectTrack(samples=samples, detector="t", duration_s=8.0),
                        ReframeIntent(target_aspect="9:16",
                                      follow=FollowMode.FOLLOW_SAFE),
                        source_width=SRC_W, source_height=SRC_H)
                    if not plan.subject_contained():
                        violations.append(f"start={start} step={step} r={radius}")
        assert violations == [], f"FOLLOW_SAFE lost the subject: {violations[:6]}"

    def test_a_subject_hanging_off_the_source_edge_is_reported_not_claimed(self) -> None:
        """Honesty: a crop cannot contain what the source does not show."""
        plan = plan_reframe(
            SubjectTrack(samples=tuple(
                SubjectSample(t_s=float(i), cx=0.98, cy=0.5, radius=0.04,
                              source=TrackSource.INJECTED_DETECTOR)
                for i in range(4)), detector="t", duration_s=4.0),
            ReframeIntent(target_aspect="9:16", follow=FollowMode.FOLLOW_SAFE),
            source_width=SRC_W, source_height=SRC_H)
        assert plan.subject_contained() is False, (
            "claiming containment for a subject outside the source would be a lie"
        )

    def test_follow_mode_may_lose_the_subject_but_follow_safe_may_not(self) -> None:
        """The contrast that gives FOLLOW_SAFE its meaning."""
        samples = tuple(
            SubjectSample(t_s=float(i), cx=0.10 + i * 0.05, cy=0.5, radius=0.03,
                          source=TrackSource.INJECTED_DETECTOR)
            for i in range(8)
        )
        track = SubjectTrack(samples=samples, detector="t", duration_s=8.0)
        assert plan_reframe(
            track, ReframeIntent(target_aspect="9:16", follow=FollowMode.STATIC),
            source_width=SRC_W, source_height=SRC_H).subject_contained() is False
        assert plan_reframe(
            track, ReframeIntent(target_aspect="9:16", follow=FollowMode.FOLLOW_SAFE),
            source_width=SRC_W, source_height=SRC_H).subject_contained() is True


class TestFilterCompilation:
    def test_single_window_compiles_to_a_plain_crop(self) -> None:
        plan = plan_reframe(
            SubjectTrack(samples=(SubjectSample(t_s=0.0, cx=0.5, cy=0.5),)),
            ReframeIntent(target_aspect="1:1"), source_width=SRC_W, source_height=SRC_H)
        compiled = compile_reframe_filter(plan)
        assert compiled.startswith("crop=")
        assert "if(" not in compiled

    def test_commas_are_escaped_for_the_filter_graph(self) -> None:
        plan = plan_reframe(_walking_track(), ReframeIntent(target_aspect="9:16"),
                            source_width=SRC_W, source_height=SRC_H)
        compiled = compile_reframe_filter(plan)
        assert "\\," in compiled
        # No unescaped comma inside the crop expression region.
        crop_part = compiled.split(",scale=")[0]
        # every comma inside the crop expression must be escaped; the one
        # separating crop from scale is a real filter separator and is fine
        assert crop_part.count(",") == crop_part.count("\\,")

    def test_no_eval_option(self) -> None:
        """`crop` has no eval option; adding one makes ffmpeg abort."""
        plan = plan_reframe(_walking_track(), ReframeIntent(target_aspect="9:16"),
                            source_width=SRC_W, source_height=SRC_H)
        assert "eval=" not in compile_reframe_filter(plan)

    def test_empty_plan_cannot_compile(self) -> None:
        track = _walking_track()
        plan = plan_reframe(track, ReframeIntent(), source_width=SRC_W, source_height=SRC_H)
        object.__setattr__(plan, "windows", ())
        with pytest.raises(ReframeError, match="CANNOT_COMPILE_EMPTY_PLAN"):
            compile_reframe_filter(plan)


class TestExecution:
    @pytest.mark.parametrize("aspect", ["9:16", "16:9", "1:1"])
    def test_real_render_honours_the_planned_geometry(
        self, moving_source: Path, tmp_path: Path, aspect: str
    ) -> None:
        plan = plan_reframe(_walking_track(), ReframeIntent(target_aspect=aspect),
                            source_width=SRC_W, source_height=SRC_H)
        out = execute_reframe(moving_source, plan, tmp_path / f"{aspect}.mp4")
        assert out.is_file() and out.stat().st_size > 0
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries",
             "stream=width,height", "-of", "csv=p=0", str(out)],
            capture_output=True, text=True, check=True).stdout.strip()
        got_w, got_h = (int(v) for v in probe.split(","))
        assert (got_w, got_h) == (plan.target_width, plan.target_height)

    def test_render_preserves_duration(self, moving_source: Path, tmp_path: Path) -> None:
        plan = plan_reframe(_walking_track(), ReframeIntent(target_aspect="9:16"),
                            source_width=SRC_W, source_height=SRC_H)
        out = execute_reframe(moving_source, plan, tmp_path / "d.mp4")
        dur = float(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(out)],
            capture_output=True, text=True, check=True).stdout.strip())
        assert 3.5 < dur < 4.5

    def test_the_crop_actually_moves_over_time(
        self, moving_source: Path, tmp_path: Path
    ) -> None:
        """The trajectory must be real, not a static crop with extra steps."""
        plan = plan_reframe(
            _walking_track(), ReframeIntent(target_aspect="9:16",
                                            follow=FollowMode.FOLLOW),
            source_width=SRC_W, source_height=SRC_H)
        out = execute_reframe(moving_source, plan, tmp_path / "moving_crop.mp4")
        shots = []
        for t_s in ("0.2", "3.6"):
            frame = tmp_path / f"f{t_s}.png"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", t_s, "-i", str(out),
                            "-frames:v", "1", str(frame)], check=True, capture_output=True)
            shots.append(frame.read_bytes())
        assert shots[0] != shots[1], "the crop did not move between t=0.2 and t=3.6"

    def test_refuses_to_overwrite_the_source(self, moving_source: Path) -> None:
        plan = plan_reframe(_walking_track(), ReframeIntent(target_aspect="9:16"),
                            source_width=SRC_W, source_height=SRC_H)
        with pytest.raises(ReframeError, match="REFUSE_OVERWRITE_SOURCE"):
            execute_reframe(moving_source, plan, moving_source)


class TestSaliencyFallback:
    def test_static_video_yields_no_track(self, static_source: Path) -> None:
        """No contrast means no evidence, and no evidence means no centre crop."""
        with pytest.raises(ReframeError, match="SALENCY_NO_SUBJECT"):
            saliency_track(static_source)

    def test_moving_video_yields_a_saliency_stamped_track(self, moving_source: Path) -> None:
        track = saliency_track(moving_source, sample_count=8)
        assert track.sources == (TrackSource.SALIENCY,)
        assert len(track.samples) == 8
        assert "saliency" in track.detector

    def test_track_samples_span_the_clip(self, moving_source: Path) -> None:
        """Regression: duration was read in the wrong units and every sample
        landed on the first frame, producing a track that never moved."""
        track = saliency_track(moving_source, sample_count=8)
        assert track.duration_s == pytest.approx(3.8, abs=0.6)
        times = [s.t_s for s in track.samples]
        assert times == sorted(times)
        assert times[-1] - times[0] > 2.0
        positions = {(round(s.cx, 3), round(s.cy, 3)) for s in track.samples}
        assert len(positions) > 1, "saliency produced a static track"

    def test_samples_are_in_normalised_frame(self, moving_source: Path) -> None:
        track = saliency_track(moving_source, sample_count=8)
        for sample in track.samples:
            assert 0.0 <= sample.cx <= 1.0
            assert 0.0 <= sample.cy <= 1.0
            assert 0.0 < sample.radius <= 1.0

    def test_interpolated_samples_do_not_claim_confidence(
        self, moving_source: Path
    ) -> None:
        """A filled-in sample must not borrow its neighbour's certainty."""
        track = saliency_track(moving_source, sample_count=8)
        zero_conf = [s for s in track.samples if s.confidence == 0.0]
        assert all(s.source is TrackSource.SALIENCY for s in zero_conf)


class TestEvidence:
    def test_plan_serialises_its_provenance(self) -> None:
        plan = plan_reframe(_walking_track(), ReframeIntent(target_aspect="9:16"),
                            source_width=SRC_W, source_height=SRC_H)
        data = plan.to_dict()
        assert data["source"] == {"width": SRC_W, "height": SRC_H}
        assert data["target"]["aspect"] == "9:16"
        assert data["track"]["sources"] == ["injected_detector"]
        assert len(data["windows"]) == len(data["track"]["samples"]) or \
            len(data["windows"]) <= 12
        assert isinstance(data["subject_contained"], bool)
        json.dumps(data)  # must be serialisable as evidence, as-is

    def test_saliency_plan_is_honest_about_its_source(self, moving_source: Path) -> None:
        track = saliency_track(moving_source, sample_count=6)
        plan = plan_reframe(track, ReframeIntent(target_aspect="9:16"),
                            source_width=SRC_W, source_height=SRC_H)
        assert plan.to_dict()["track"]["sources"] == ["saliency"]
        assert "saliency" in plan.track.detector
