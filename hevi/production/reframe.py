"""Reframe Engine — subject track to executed crop trajectory.

    SubjectTrack -> ReframePlan -> ffmpeg filter -> reframed artifact -> verification

Three rules shape this module, and all three are load-bearing.

**1. Tracking supplies geometry, not creative authority.** The tracker answers
"where is the subject"; the ``ReframeIntent`` answers "how should the frame be
composed". A detector that is wrong produces a wrong crop, never a wrong
*decision*, because every :class:`SubjectSample` carries its own ``source`` and
the plan records it.

**2. No per-frame Python.** The spec's §4.1 requires native media operations
where quality is equivalent. The trajectory is sampled to a bounded number of
keyframes and emitted as an ffmpeg ``crop`` expression with ``eval=frame``, so
ffmpeg interpolates. Python decides the geometry once; ffmpeg owns the frames.

**3. Absent evidence is UNKNOWN, never a silent centre crop.** If no track can be
produced, planning raises. The previous behaviour in this repo was a hardcoded
``crop={width}:{height}`` for every mode
(``hevi/openshorts/clip_engine.py``), which silently framed the middle of the
image regardless of where anybody was.

No detector dependency is added. ``cv2``/mediapipe/insightface are not installed
and are not declared, so callers may *inject* a detector, and
:func:`saliency_track` provides a numpy-only fallback that is honest about being
a saliency hint rather than a face detection.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

#: A track longer than this is sampled down to this many keyframes before being
#: compiled. More anchors than this buys nothing: the trajectory is smoothed, and
#: an ffmpeg expression nested deeper becomes unreadable and slow to evaluate.
MAX_KEYFRAMES = 12


class ReframeError(RuntimeError):
    """Reframe could not be planned or executed."""


class TrackSource(StrEnum):
    """Where a subject sample came from. Recorded per sample, never assumed."""

    #: an injected detector (mediapipe, insightface, cv2 cascade, ...)
    INJECTED_DETECTOR = "injected_detector"
    #: numpy/PyAV temporal-contrast saliency. A hint, not a detection.
    SALIENCY = "saliency"
    #: stated by a human.
    HUMAN = "human"


class FollowMode(StrEnum):
    """How strictly the crop window follows the track."""

    #: the window centres on the subject, clamped inside the frame
    FOLLOW = "follow"
    #: the window is the largest centred crop of the target aspect; the subject
    #: is reported as inside-or-not but the geometry does not move
    STATIC = "static"
    #: like FOLLOW but only moves when the subject would otherwise leave the safe
    #: area, which produces fewer, calmer moves
    FOLLOW_SAFE = "follow_safe"


@dataclass(frozen=True)
class SubjectSample:
    """One observation of a subject, in normalised source coordinates.

    ``cx``/``cy`` are fractions of source width/height. ``radius`` is the
    subject's **half**-extent as a fraction of the *smaller* source dimension, so
    it is comparable across aspects. Sizing a crop from ``radius`` directly
    instead of ``2 * radius`` produced a window half the width of the subject it
    was meant to hold, and the containment check then failed on its own plan.
    """

    t_s: float
    cx: float
    cy: float
    radius: float = 0.25
    confidence: float = 1.0
    source: TrackSource = TrackSource.SALIENCY

    def to_dict(self) -> dict[str, Any]:
        return {
            "t_s": round(self.t_s, 3), "cx": round(self.cx, 4),
            "cy": round(self.cy, 4), "radius": round(self.radius, 4),
            "confidence": round(self.confidence, 4), "source": self.source.value,
        }


@dataclass(frozen=True)
class SubjectTrack:
    """A sequence of samples plus where they came from."""

    samples: tuple[SubjectSample, ...]
    #: free-text description of the detector, e.g. "mediapipe face, conf>=0.5"
    detector: str = ""
    duration_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.samples:
            raise ReframeError(
                "EMPTY_SUBJECT_TRACK:a track with no samples cannot produce a "
                "crop; this is not a licence to centre-crop"
            )
        for index, sample in enumerate(self.samples):
            if not 0.0 <= sample.cx <= 1.0 or not 0.0 <= sample.cy <= 1.0:
                raise ValueError(
                    f"subject sample {index} out of frame: "
                    f"cx={sample.cx} cy={sample.cy}"
                )

    @property
    def sources(self) -> tuple[TrackSource, ...]:
        return tuple(sorted({s.source for s in self.samples}, key=str))

    def at(self, t_s: float) -> SubjectSample:
        """Nearest sample. Deterministic tie-break: the earlier sample."""
        return min(self.samples, key=lambda s: (abs(s.t_s - t_s), s.t_s))

    def to_dict(self) -> dict[str, Any]:
        return {
            "detector": self.detector,
            "duration_s": round(self.duration_s, 3),
            "sample_count": len(self.samples),
            "sources": [s.value for s in self.sources],
            "samples": [s.to_dict() for s in self.samples],
        }


@dataclass(frozen=True)
class ReframeIntent:
    """The creative half of a reframe. Composition, not detection."""

    target_aspect: str = "16:9"
    #: how much of the smaller dimension the subject should occupy, 0..1
    tightness: float = 0.62
    follow: FollowMode = FollowMode.FOLLOW_SAFE
    #: fraction of the crop kept free on the side the subject faces
    lead_room: float = 0.08
    #: never zoom tighter than this, so a close-up cannot become a full frame
    min_tightness: float = 0.22

    def __post_init__(self) -> None:
        if not 0.0 < self.tightness <= 1.0:
            raise ValueError(f"tightness must be in (0,1]; got {self.tightness}")
        if not 0.0 <= self.lead_room < 0.5:
            raise ValueError(f"lead_room must be in [0,0.5); got {self.lead_room}")


@dataclass(frozen=True)
class CropWindow:
    """An absolute crop rectangle in source pixels."""

    t_s: float
    x: int
    y: int
    w: int
    h: int

    def to_dict(self) -> dict[str, Any]:
        return {"t_s": round(self.t_s, 3), "x": self.x, "y": self.y,
                "w": self.w, "h": self.h}


@dataclass(frozen=True)
class ReframePlan:
    """The whole reframe decision, reviewable before anything renders."""

    source_width: int
    source_height: int
    intent: ReframeIntent
    windows: tuple[CropWindow, ...]
    track: SubjectTrack
    keyframes: tuple[SubjectSample, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def target_width(self) -> int:
        return self.windows[0].w if self.windows else 0

    @property
    def target_height(self) -> int:
        return self.windows[0].h if self.windows else 0

    def subject_contained(self) -> bool:
        """Whether the subject stays inside every window.

        This is the property a reframe exists to deliver, so it is computed from
        the plan rather than assumed from the code path.
        """
        for window, sample in zip(self.windows, self.keyframes, strict=True):
            sx = sample.cx * self.source_width
            sy = sample.cy * self.source_height
            r = sample.radius * min(self.source_width, self.source_height)
            if not (window.x <= sx - r and sx + r <= window.x + window.w):
                return False
            if not (window.y <= sy - r and sy + r <= window.y + window.h):
                return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": {"width": self.source_width, "height": self.source_height},
            "target": {"width": self.target_width, "height": self.target_height,
                       "aspect": self.intent.target_aspect},
            "follow": self.intent.follow.value,
            "tightness": self.intent.tightness,
            "keyframe_count": len(self.keyframes),
            "window_count": len(self.windows),
            "subject_contained": self.subject_contained(),
            "track": self.track.to_dict(),
            "windows": [w.to_dict() for w in self.windows],
            "notes": list(self.notes),
        }


def parse_aspect(value: str) -> tuple[int, int]:
    """``"16:9"`` -> ``(16, 9)``. Accepts ``"1.91:1"`` and ``"2.39"``."""
    text = str(value).strip()
    if ":" not in text:
        raise ValueError(f"aspect must look like '16:9'; got {value!r}")
    left, _, right = text.partition(":")
    return int(float(left)), int(float(right))


def _largest_crop(source_w: int, source_h: int, aspect_w: int, aspect_h: int) -> tuple[int, int]:
    """The biggest ``aspect`` rectangle inside the source, without upscaling."""
    target = aspect_w / aspect_h
    src = source_w / source_h
    if src > target:
        # source is wider: height is the constraint
        h = source_h
        w = round(h * target)
    else:
        w = source_w
        h = round(w / target)
    return _even(min(w, source_w)), _even(min(h, source_h))


def _even(value: float) -> int:
    """Round down to an even integer.

    h264 with yuv420p rejects odd dimensions ("width not divisible by 2"), and
    that only surfaces when ffmpeg actually opens the encoder — a plan that
    rounds to 405px wide passes every geometric assertion and then fails the
    render.
    """
    return max(16, int(value) // 2 * 2)


def _clamp_window(x: float, y: float, w: int, h: int,
                  src_w: int, src_h: int) -> tuple[int, int, int, int]:
    x = max(0.0, min(x, src_w - w))
    y = max(0.0, min(y, src_h - h))
    return round(x), round(y), int(w), int(h)


def plan_reframe(
    track: SubjectTrack,
    intent: ReframeIntent,
    *,
    source_width: int,
    source_height: int,
    max_keyframes: int = MAX_KEYFRAMES,
) -> ReframePlan:
    """Turn a track plus an intent into a crop trajectory.

    Deterministic: same track and intent always give the same plan. The subject
    is kept out of the lead-room side so a subject looking off-frame has space to
    look into.
    """
    if source_width <= 0 or source_height <= 0:
        raise ValueError(f"source dimensions must be positive; got {source_width}x{source_height}")
    aspect_w, aspect_h = parse_aspect(intent.target_aspect)
    notes: list[str] = []

    base_w, base_h = _largest_crop(source_width, source_height, aspect_w, aspect_h)
    if base_w >= _even(source_width) and base_h >= _even(source_height):
        notes.append(
            "SOURCE_ALREADY_TARGET_ASPECT:the full frame already has the target "
            "aspect, so any crop here is a tightening rather than a conversion"
        )

    samples = _resample(track.samples, max_keyframes=max_keyframes)
    windows: list[CropWindow] = []
    previous: tuple[int, int, int, int] | None = None
    aspect = aspect_w / aspect_h

    for sample in samples:
        subject_px = max(4.0, 2.0 * sample.radius * min(source_width, source_height))
        # The subject's extent should span `tightness` of the crop's WIDTH, so the
        # crop width is subject_px / tightness. Treating that number as a scale
        # rather than a width is what produced a 133px crop out of a 405px box in
        # the first version of this function.
        want_w = subject_px / max(1e-6, intent.tightness)
        # Never tighter than the declared floor.
        want_w = max(max(16.0, intent.min_tightness * base_w), want_w)
        # The only size constraint is the largest box of the target aspect that
        # fits in the source. An earlier guard capped the crop at
        # min(W,H)/aspect, which for a landscape target threw away most of the
        # frame: a 16:9 crop from 1280x720 could never exceed 404px wide.
        if want_w > base_w or want_w / aspect > base_h:
            want_w, _ = float(base_w), 0.0
            # Deduped: the clamp fires once per keyframe, and a note repeated a
            # dozen times is noise in the evidence rather than information.
            clamp_note = (
                "CLAMPED_TO_LARGEST_CROP:cannot crop tighter than the target aspect allows"
            )
            if clamp_note not in notes:
                notes.append(clamp_note)
        w = min(_even(want_w), _even(source_width))
        h = min(_even(want_w / aspect), _even(source_height))
        if h > _even(source_height):
            h = _even(source_height)
            w = min(_even(h * aspect), _even(source_width))

        cx = sample.cx * source_width
        cy = sample.cy * source_height
        half_extent_x = min(sample.radius * source_width, w / 2.0)
        half_extent_y = min(sample.radius * source_height, h / 2.0)
        if intent.follow is FollowMode.STATIC:
            x = (source_width - w) / 2.0
            y = (source_height - h) / 2.0
        else:
            lead = intent.lead_room * w
            facing_right = cx <= source_width / 2
            offset = lead if facing_right else -lead
            x = cx - w / 2.0 + offset
            y = cy - h / 2.0
            if intent.follow is FollowMode.FOLLOW_SAFE and previous is not None:
                # Hold the previous window only while the subject's *whole extent*
                # still fits inside it. The safe margin is the subject's radius,
                # not a fixed fraction of the window: a margin smaller than the
                # subject lets the window sit still while the subject walks out of
                # frame, which is the exact defect FOLLOW_SAFE exists to prevent.
                px, py, pw, ph = previous
                if (px <= cx - half_extent_x and cx + half_extent_x <= px + pw
                        and py <= cy - half_extent_y and cy + half_extent_y <= py + ph):
                    x, y = float(px), float(py)
        window = _clamp_window(x, y, w, h, source_width, source_height)
        previous = window
        windows.append(CropWindow(t_s=sample.t_s, x=window[0], y=window[1],
                                  w=window[2], h=window[3]))

    return ReframePlan(
        source_width=source_width, source_height=source_height, intent=intent,
        windows=tuple(windows), track=track, keyframes=tuple(samples),
        notes=tuple(notes),
    )


def _resample(samples: Sequence[SubjectSample], *, max_keyframes: int) -> tuple[SubjectSample, ...]:
    """Evenly sample the track down to at most ``max_keyframes`` points."""
    ordered = tuple(sorted(samples, key=lambda s: s.t_s))
    if len(ordered) <= max_keyframes:
        return ordered
    step = (len(ordered) - 1) / (max_keyframes - 1)
    picked = [ordered[round(index * step)] for index in range(max_keyframes)]
    # The final sample must be the final sample, or the last second has no crop.
    if picked[-1] is not ordered[-1]:
        picked[-1] = ordered[-1]
    return tuple(picked)


def _axis_expr(axis: str, windows: Sequence[CropWindow]) -> str:
    """A piecewise-linear ffmpeg expression for one axis, built inside-out.

    Commas are escaped as ``\\,`` because the expression travels inside a filter
    graph where an unescaped comma would start a new filter. No surrounding
    quotes are emitted: the filter is passed as one argv element with no shell,
    so quotes would arrive literally and break the parse.

    Built from the last segment backwards, so segment k governs ``[t_k, t_k+1)``
    and anything past the final keyframe holds the final value.
    """
    values = [float(getattr(w, axis)) for w in windows]
    if len(values) == 1:
        return f"{values[0]:.4f}"
    expr = f"{values[-1]:.4f}"
    for position in range(len(windows) - 2, -1, -1):
        a_t = windows[position].t_s
        b_t = windows[position + 1].t_s
        a_v, b_v = values[position], values[position + 1]
        span = b_t - a_t
        segment = (
            f"{a_v:.4f}" if span <= 1e-9
            else f"({a_v:.4f}+({b_v:.4f}-{a_v:.4f})*(t-{a_t:.4f})/{span:.4f})"
        )
        expr = f"if(lt(t\\,{b_t:.4f})\\,{segment}\\,{expr})"
    return expr


def compile_reframe_filter(plan: ReframePlan) -> str:
    """Compile the plan into an ffmpeg ``crop`` filter.

    Window size is constant across the plan, and x/y are time-varying
    expressions. ffmpeg's ``crop`` evaluates x/y per frame on its own, so the
    trajectory runs natively rather than through a Python frame loop.

    ``crop`` has no ``eval`` option (its options are w/h/x/y/keep_aspect/exact);
    adding one makes ffmpeg abort with "Option not found".
    """
    windows = plan.windows
    if not windows:
        raise ReframeError("CANNOT_COMPILE_EMPTY_PLAN:no crop window to compile")
    w, h = windows[0].w, windows[0].h
    if any(item.w != w or item.h != h for item in windows):
        raise ReframeError(
            "CANNOT_COMPILE_VARYING_SIZE:ffmpeg crop size must be constant; "
            "this plan changes size between keyframes"
        )
    return (
        f"crop={w}:{h}:{_axis_expr('x', windows)}:{_axis_expr('y', windows)},"
        f"scale={w}:{h}:flags=lanczos,setsar=1"
    )


def _ffmpeg() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def execute_reframe(
    video: str | Path, plan: ReframePlan, out: str | Path, *, timeout_s: float = 1800.0
) -> Path:
    """Render the plan with native ffmpeg. No per-frame Python materialisation."""
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    source = Path(video)
    if target.resolve() == source.resolve():
        raise ReframeError(f"REFUSE_OVERWRITE_SOURCE:{target}")
    proc = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-vf", compile_reframe_filter(plan), "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "20", "-pix_fmt", "yuv420p", "-an", str(target)],
        capture_output=True, text=True, timeout=timeout_s, check=False,
    )
    if proc.returncode != 0 or not target.is_file():
        raise ReframeError(f"REFRAME_FAILED:{proc.stderr[-300:]}")
    return target


# ── Saliency fallback: no detector dependency ────────────────────────────


def saliency_track(
    video: str | Path,
    *,
    sample_count: int = 8,
    analysis_width: int = 160,
    min_subject_fraction: float = 0.004,
) -> SubjectTrack:
    """Estimate a subject position from temporal contrast. numpy + PyAV only.

    This is a **saliency hint**, not a face detection and not a tracker. The
    method: take the per-pixel median across sampled frames as a crude
    background, then find the brightest deviation region in each frame and use
    its centroid. It is deterministic and dependency-free, and every sample it
    produces is stamped ``TrackSource.SALIENCY`` so no downstream consumer can
    mistake it for a detection.

    Raises:
        ReframeError: if no frame yields a usable deviation, which means there
            is no evidence to reframe on and a centre crop would be a guess.
    """
    import numpy as np

    frames, times = _decode_gray(video, sample_count=sample_count,
                                 analysis_width=analysis_width)
    if not frames:
        raise ReframeError("SALENCY_NO_FRAMES:could not decode any frame")

    stack = np.stack(frames)
    background = np.median(stack, axis=0)
    height, width = background.shape
    samples: list[SubjectSample] = []

    for frame, t_s in zip(frames, times, strict=True):
        deviation = np.abs(frame - background)
        # Percentile threshold, not mean+k*sigma. In a locked-off shot with one
        # small moving subject the deviation map is near zero everywhere except
        # the subject, so mean+1.5*sigma lands above the subject's own peak and
        # the mask comes back empty. A high percentile isolates the top few
        # percent of pixels regardless of how much of the frame moved, which is
        # what works for both a pan and a static corridor.
        threshold = max(4.0, float(np.percentile(deviation, 96.0)))
        mask = deviation > threshold
        total = float(mask.sum())
        if total < min_subject_fraction * height * width:
            samples.append(SubjectSample(
                t_s=t_s, cx=float("nan"), cy=float("nan"),
                source=TrackSource.SALIENCY))
            continue
        ys, xs = np.nonzero(mask)
        weights = deviation[ys, xs]
        cx = float((xs * weights).sum() / weights.sum()) / max(1, width - 1)
        cy = float((ys * weights).sum() / weights.sum()) / max(1, height - 1)
        # Extent: the RMS spread of the salient mass, which is stable and needs
        # no connected-component labelling.
        spread = float(np.sqrt(weights.sum() / max(1.0, weights.mean())))
        radius = max(0.06, min(0.9, 2.0 * spread / max(height, width)))
        samples.append(SubjectSample(
            t_s=t_s, cx=cx, cy=cy, radius=radius,
            confidence=float(min(1.0, total / (0.08 * height * width))),
            source=TrackSource.SALIENCY))

    usable = [s for s in samples if not math.isnan(s.cx)]
    if not usable:
        raise ReframeError(
            "SALENCY_NO_SUBJECT:no frame showed temporal contrast, so there is "
            "no evidence for a subject; centring would be a guess"
        )
    if len(usable) < len(samples):
        samples = _fill_gaps(samples)
    return SubjectTrack(
        samples=tuple(samples),
        detector=f"temporal-contrast saliency (numpy/PyAV, {analysis_width}px)",
        duration_s=float(times[-1]) if times else 0.0,
    )


def _fill_gaps(samples: list[SubjectSample]) -> list[SubjectSample]:
    """Replace unusable samples with the nearest usable one, honestly stamped."""
    usable = [s for s in samples if not math.isnan(s.cx)]
    out: list[SubjectSample] = []
    for sample in samples:
        if math.isnan(sample.cx):
            nearest = min(usable, key=lambda s: abs(s.t_s - sample.t_s))
            out.append(SubjectSample(
                t_s=sample.t_s, cx=nearest.cx, cy=nearest.cy,
                radius=nearest.radius,
                # Interpolated, so it must not claim the neighbour's confidence.
                confidence=0.0, source=TrackSource.SALIENCY))
        else:
            out.append(sample)
    return out


def _decode_gray(
    video: str | Path, *, sample_count: int, analysis_width: int
) -> tuple[list[Any], list[float]]:
    """Decode evenly spaced frames as small grayscale arrays, via PyAV.

    This walks the stream **once, sequentially**, and keeps the frame nearest each
    target timestamp. Seeking per sample looks cheaper but is not: on a file
    produced by ``-c copy`` concat (which is how every HEVI multi-scene render is
    assembled) the index is sparse and ``seek`` + ``decode`` silently returns the
    same keyframe for every target — a 36s clip sampled at six points returned
    five identical frames and one from the far end. Sampling sequentially is
    robust to that and to edit lists generally.
    """
    import av
    import numpy as np
    from PIL import Image

    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        # container.duration is in AV_TIME_BASE (microseconds); stream.duration is
        # in the stream's own time_base units. Dividing stream.duration by 1e6
        # reads a 4s clip as 0.05s.
        duration = 0.0
        if container.duration:
            duration = float(container.duration) / 1_000_000.0
        elif stream.duration and stream.time_base:
            duration = float(stream.duration * stream.time_base)
        if duration <= 0:
            return [], []

        targets = [
            duration * (index + 0.5) / sample_count for index in range(sample_count)
        ]
        chosen: dict[int, Any] = {}
        # `frame.pts * time_base` is already seconds from zero; `stream.start_time`
        # is in time_base *units* (589, not 0.046s, for a 1/12800 stream), so
        # adding it to a seconds-valued timestamp inflated every sample past the
        # end of the clip and silently produced zero frames.
        for frame in container.decode(stream):
            if frame.pts is None or not stream.time_base:
                continue
            t_s = float(frame.pts * stream.time_base)
            index = _nearest_target(targets, t_s)
            if index is None or index in chosen:
                continue
            gray = frame.to_ndarray(format="gray")
            if gray.size == 0:
                continue
            height = max(2, round(gray.shape[0] * analysis_width / max(1, gray.shape[1])))
            chosen[index] = np.asarray(
                Image.fromarray(gray.astype("uint8")).resize(
                    (analysis_width, height), Image.Resampling.BILINEAR),
                dtype=np.float64,
            )
            if len(chosen) == len(targets):
                break

    frames = [chosen[index] for index in sorted(chosen)]
    times = [targets[index] for index in sorted(chosen)]
    return frames, times


def _nearest_target(targets: Sequence[float], t_s: float) -> int | None:
    """Index of the target closest to ``t_s``, or None once we are past them all."""
    if t_s > targets[-1] + (targets[1] - targets[0] if len(targets) > 1 else 1.0):
        return None
    best, best_delta = None, float("inf")
    for index, target in enumerate(targets):
        delta = abs(t_s - target)
        if delta < best_delta:
            best, best_delta = index, delta
    return best


DetectorFn = Callable[[str | Path], SubjectTrack]


def plan_from_detector(
    detector: DetectorFn, video: str | Path, intent: ReframeIntent,
    *, source_width: int, source_height: int,
) -> ReframePlan:
    """Convenience seam for callers holding a real detector."""
    track = detector(video)
    return plan_reframe(track, intent, source_width=source_width,
                        source_height=source_height)


__all__ = [
    "MAX_KEYFRAMES",
    "CropWindow",
    "FollowMode",
    "ReframeError",
    "ReframeIntent",
    "ReframePlan",
    "SubjectSample",
    "SubjectTrack",
    "TrackSource",
    "compile_reframe_filter",
    "execute_reframe",
    "parse_aspect",
    "plan_from_detector",
    "plan_reframe",
    "saliency_track",
]
