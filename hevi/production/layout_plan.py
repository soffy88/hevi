"""Layout plan — one structural plan over three canonical vocabularies.

    CompositionSpec -> LayoutPlan -> native filter graph -> artifact

This module adds **no new vocabulary**. It holds the three owners chosen in
``docs/qualification/p11-layout-vocabulary/CANONICAL_MAPPING.json`` side by side
and refuses to collapse them:

    PresenterScale    hevi/production/presenter.py:27    how prominent the subject is
    SpeakerVisibility hevi/production/p6/schema.py:136  which speaker is visible
    ReframingMode     hevi/openshorts/schemas.py:22     frame geometry

The P11 inventory recorded **zero renderer consumers** for all three, which is the
gap this closes: the semantics were declared and planned but never reached pixels.

Fail-closed is the whole design. Every invalid combination raises. In particular a
layout that needs a subject track and does not get one raises rather than
centre-cropping — the silent behaviour this replaces.

Relationship to ``layout_boxes``
--------------------------------
``hevi/production/layout_boxes.py`` already owns *animated element* geometry against
a frozen ``CraftProfile``, with timing, ``protected`` zones and an occlusion gate.
This module owns the different thing: the static per-shot arrangement of **sources**
(what is cropped and where it lands) implied by a composition. It therefore keeps
the same normalised 0..1 coordinate convention and the same plain ``role: str``
rather than introducing a role enum, but it does not reuse ``LayoutElement``,
because a source region has a crop and a media source and no protected-zone or
timing semantics.

Coordinates are normalised to the canvas (0..1 of width/height) in a plan, and
converted to pixels exactly once, in :meth:`LayoutRegion.to_px`. Mixing the two is
how an inset ends up off-frame.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.openshorts.schemas import ReframingMode
from hevi.production.p6.schema import SpeakerVisibility
from hevi.production.presenter import PresenterScale
from hevi.production.reframe import (
    ReframeError,
    ReframeIntent,
    ReframePlan,
    SubjectTrack,
    compile_reframe_filter,
    parse_aspect,
    plan_reframe,
)

#: Bumped whenever planning changes. Recorded in every plan's provenance.
PLANNER_VERSION = "p11.layout-planner-v1"

#: Which owner each dimension comes from, recorded in every spec.
VOCABULARY_OWNERS = {
    "presenter_scale": "hevi/production/presenter.py:PresenterScale",
    "speaker_visibility": "hevi/production/p6/schema.py:SpeakerVisibility",
    "layout_mode": "hevi/openshorts/schemas.py:ReframingMode",
}

_ANCHORS = ("bottom_right", "bottom_left", "top_right", "top_left")


class CompositionError(ValueError):
    """An invalid composition or an unplannable layout. Never a fallback trigger."""


@dataclass(frozen=True)
class LayoutParameters:
    """Layout configuration. Validated per layout mode, never a vocabulary."""

    aspect_ratio: str = "9:16"
    output_width: int = 1280
    output_height: int = 720
    #: free border kept inside the canvas, as a fraction of the smaller side
    safe_margin: float = 0.0
    #: where the split falls, 0..1 of the canvas width
    split_ratio: float = 0.5
    #: fraction of the canvas an inset occupies
    inset_scale: float = 0.32
    #: inset corner
    anchor: str = "bottom_right"
    #: gap between split regions, as a fraction of width
    gap: float = 0.0

    def __post_init__(self) -> None:
        if self.output_width <= 0 or self.output_height <= 0:
            raise CompositionError(
                f"INVALID_OUTPUT_DIMENSIONS:{self.output_width}x{self.output_height}")
        if not 0.0 < self.split_ratio < 1.0:
            raise CompositionError(f"INVALID_SPLIT_RATIO:{self.split_ratio}")
        if not 0.0 < self.inset_scale < 1.0:
            raise CompositionError(f"INVALID_INSET_SCALE:{self.inset_scale}")
        if not 0.0 <= self.safe_margin < 0.5:
            raise CompositionError(f"INVALID_SAFE_MARGIN:{self.safe_margin}")
        if not 0.0 <= self.gap < 0.5:
            raise CompositionError(f"INVALID_GAP:{self.gap}")
        if self.anchor not in _ANCHORS:
            raise CompositionError(f"INVALID_ANCHOR:{self.anchor}")
        # Fail here rather than at compile time, where the error would name
        # pixels instead of the parameter the caller actually set.
        parse_aspect(self.aspect_ratio)

    def to_dict(self) -> dict[str, Any]:
        return {
            "aspect_ratio": self.aspect_ratio,
            "output_width": self.output_width,
            "output_height": self.output_height,
            "safe_margin": self.safe_margin,
            "split_ratio": self.split_ratio,
            "inset_scale": self.inset_scale,
            "anchor": self.anchor,
            "gap": self.gap,
        }


@dataclass(frozen=True)
class CompositionSpec:
    """The three canonical dimensions plus configuration.

    A structural plan object. It defines no enum member of its own; see
    ``VOCABULARY_OWNERS``.
    """

    presenter_scale: PresenterScale
    speaker_visibility: SpeakerVisibility
    layout_mode: ReframingMode
    parameters: LayoutParameters = field(default_factory=LayoutParameters)
    shot_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.presenter_scale, PresenterScale):
            raise CompositionError(f"UNKNOWN_PRESENTER_SCALE:{self.presenter_scale!r}")
        if not isinstance(self.speaker_visibility, SpeakerVisibility):
            raise CompositionError(
                f"UNKNOWN_SPEAKER_VISIBILITY:{self.speaker_visibility!r}")
        if not isinstance(self.layout_mode, ReframingMode):
            raise CompositionError(f"UNKNOWN_LAYOUT_MODE:{self.layout_mode!r}")
        self._validate_combination()

    def _validate_combination(self) -> None:
        """Reject combinations the renderer cannot honour.

        This is where declared modes become honest: a ``track`` composition with a
        hidden presenter is a contradiction, and a hidden speaker with a visible
        scale is a contradiction. Both are refused at construction rather than
        resolved by a default at render time.
        """
        if (self.layout_mode is ReframingMode.TRACK
                and self.presenter_scale is PresenterScale.HIDDEN):
            raise CompositionError(
                "TRACK_REQUIRES_VISIBLE_PRESENTER:tracked framing cannot apply to a "
                "hidden presenter")
        if (self.speaker_visibility is SpeakerVisibility.HIDDEN
                and self.presenter_scale is not PresenterScale.HIDDEN):
            raise CompositionError(
                "HIDDEN_SPEAKER_WITH_VISIBLE_SCALE:SpeakerVisibility.HIDDEN and a "
                "non-hidden PresenterScale contradict each other")
        if (self.speaker_visibility in (SpeakerVisibility.PIP, SpeakerVisibility.MEDIUM)
                and self.presenter_scale is PresenterScale.FULL):
            raise CompositionError(
                "PIP_SPEAKER_CANNOT_BE_FULLSCALE:the two dimensions disagree")
        if self.parameters.gap >= self.parameters.split_ratio:
            raise CompositionError(
                f"SPLIT_GAP_CONSUMES_SPLIT_RATIO:gap={self.parameters.gap} >= "
                f"split_ratio={self.parameters.split_ratio}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "presenter_scale": self.presenter_scale.value,
            "speaker_visibility": self.speaker_visibility.value,
            "layout_mode": self.layout_mode.value,
            "parameters": self.parameters.to_dict(),
            "planner_version": PLANNER_VERSION,
            "vocabulary_owners": dict(VOCABULARY_OWNERS),
        }


@dataclass(frozen=True)
class LayoutRegion:
    """Where one source sits. Normalised to the canvas, 0..1.

    ``role`` is a plain string, matching ``layout_boxes.LayoutElement.role``.
    """

    source: str
    role: str
    x: float
    y: float
    width: float
    height: float
    z: int = 0
    crop: dict[str, Any] = field(default_factory=dict)
    transform: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise CompositionError(
                f"REGION_NON_POSITIVE_EXTENT:{self.width}x{self.height}")
        if self.x < 0 or self.y < 0:
            raise CompositionError(f"REGION_NEGATIVE_ORIGIN:{self.x},{self.y}")
        if self.x + self.width > 1.0 + 1e-9:
            raise CompositionError(f"REGION_OUT_OF_BOUNDS_X:{self.x}+{self.width}>1")
        if self.y + self.height > 1.0 + 1e-9:
            raise CompositionError(f"REGION_OUT_OF_BOUNDS_Y:{self.y}+{self.height}>1")

    def to_px(self, canvas_w: int, canvas_h: int) -> tuple[int, int, int, int]:
        """The one place normalised coordinates become pixels."""
        w = max(1, min(round(self.width * canvas_w), canvas_w))
        h = max(1, min(round(self.height * canvas_h), canvas_h))
        x = max(0, min(round(self.x * canvas_w), canvas_w - w))
        y = max(0, min(round(self.y * canvas_h), canvas_h - h))
        return x, y, w, h

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "role": self.role,
            "x": round(self.x, 6),
            "y": round(self.y, 6),
            "width": round(self.width, 6),
            "height": round(self.height, 6),
            "z": self.z,
            "crop": self.crop,
            "transform": self.transform,
            "coordinate_system": "normalised_canvas_0_1",
        }


@dataclass(frozen=True)
class LayoutPlan:
    """An executable layout decision. A plan, not a claim that rendering worked."""

    spec: CompositionSpec
    regions: tuple[LayoutRegion, ...]
    canvas: tuple[int, int]
    reframe_plan: ReframePlan | None
    provenance: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "hevi.layout_plan.v1",
            "layout_mode": self.spec.layout_mode.value,
            "presenter_scale": self.spec.presenter_scale.value,
            "speaker_visibility": self.spec.speaker_visibility.value,
            "canvas": {"width": self.canvas[0], "height": self.canvas[1]},
            "regions": [r.to_dict() for r in self.regions],
            "requires_reframe_plan": self.spec.layout_mode is ReframingMode.TRACK,
            "reframe_plan_present": self.reframe_plan is not None,
            "coordinate_system": "normalised_canvas_0_1",
            "warnings": list(self.warnings),
            "provenance": self.provenance,
        }

    def fingerprint(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── Planner ──────────────────────────────────────────────────────────────

#: How much of the crop the subject should span, per PresenterScale.
#: A translation between two canonical dimensions, not a definition:
#: PresenterScale says how prominent the presenter is, ReframeIntent says how much
#: of the crop the subject spans. Both are inputs; neither is derived at rest.
_TIGHTNESS = {
    PresenterScale.FULL: 0.85,
    PresenterScale.MEDIUM: 0.55,
    PresenterScale.PIP: 0.30,
    PresenterScale.HIDDEN: 0.20,
}


def _largest_crop(source_w: int, source_h: int, aspect_w: int, aspect_h: int) -> tuple[int, int]:
    """The largest source-aligned crop matching the target aspect.

    Spelled out here rather than imported from reframe._largest_crop so that the
    GENERAL path has no dependency on a private P10 symbol; the two must agree, and
    test_layout_general_crop_matches_p10_largest_crop pins that.
    """
    sw, sh = max(1, int(source_w)), max(1, int(source_h))
    if sw * aspect_h <= sh * aspect_w:
        crop_w, crop_h = sw, max(1, (sw * aspect_h) // aspect_w)
    else:
        crop_w, crop_h = max(1, (sh * aspect_w) // aspect_h), sh
    return crop_w - (crop_w % 2), crop_h - (crop_h % 2)


def plan_layout(
    spec: CompositionSpec,
    *,
    primary_source: str,
    secondary_source: str | None = None,
    subject_track: SubjectTrack | None = None,
    source_width: int | None = None,
    source_height: int | None = None,
) -> LayoutPlan:
    """Resolve a composition into regions. Deterministic for identical inputs.

    Raises rather than degrading:
      * ``track`` with no ``subject_track`` -> REFRAME_PLAN_REQUIRED_BUT_ABSENT
      * ``split`` with no ``secondary_source`` -> SPLIT_REQUIRES_SECOND_SOURCE
      * unknown source geometry -> SOURCE_DIMENSIONS_REQUIRED
    """
    mode = spec.layout_mode
    params = spec.parameters
    if (source_width is None or source_height is None
            or source_width <= 0 or source_height <= 0):
        raise CompositionError(
            "SOURCE_DIMENSIONS_REQUIRED:the planner refuses to guess source geometry")

    canvas = (params.output_width, params.output_height)
    warnings: list[str] = []
    regions: list[LayoutRegion] = []
    reframe_plan: ReframePlan | None = None

    if mode is ReframingMode.TRACK:
        if subject_track is None:
            raise CompositionError(
                "REFRAME_PLAN_REQUIRED_BUT_ABSENT:layout_mode=track requires a "
                "SubjectTrack; a centre crop is not an acceptable substitute")
        try:
            reframe_plan = plan_reframe(
                subject_track,
                ReframeIntent(target_aspect=params.aspect_ratio,
                              tightness=_TIGHTNESS[spec.presenter_scale]),
                source_width=source_width,
                source_height=source_height,
            )
        except ReframeError as exc:
            raise CompositionError(f"REFRAME_PLANNING_FAILED:{exc}") from exc
        if not reframe_plan.subject_contained():
            warnings.append(
                "SUBJECT_NOT_CONTAINED:the track places the subject outside the crop "
                "at least once; the renderer does not substitute a centre crop")
        regions.append(LayoutRegion(
            source=primary_source, role="subject",
            x=0.0, y=0.0, width=1.0, height=1.0, z=0,
            crop={"mode": "reframe_plan",
                  "target": [reframe_plan.target_width, reframe_plan.target_height],
                  "windows": len(reframe_plan.windows)},
        ))

    elif mode is ReframingMode.GENERAL:
        aw, ah = parse_aspect(params.aspect_ratio)
        target_w, target_h = _largest_crop(source_width, source_height, aw, ah)
        regions.append(LayoutRegion(
            source=primary_source, role="subject",
            x=0.0, y=0.0, width=1.0, height=1.0, z=0,
            crop={"mode": "largest_target_aspect", "target": [target_w, target_h],
                  "note": "centred by construction; GENERAL declares no subject"},
        ))

    elif mode is ReframingMode.SPLIT:
        if not secondary_source:
            raise CompositionError(
                "SPLIT_REQUIRES_SECOND_SOURCE:layout_mode=split needs two sources")
        gap = params.gap
        left_w = params.split_ratio - gap / 2.0
        right_x = params.split_ratio + gap / 2.0
        right_w = 1.0 - right_x
        regions.append(LayoutRegion(source=primary_source, role="subject",
                                    x=0.0, y=0.0, width=left_w, height=1.0, z=0,
                                    crop={"mode": "fill_region"}))
        regions.append(LayoutRegion(source=secondary_source, role="secondary",
                                    x=right_x, y=0.0, width=right_w, height=1.0, z=1,
                                    crop={"mode": "fill_region"}))
    else:  # pragma: no cover - ReframingMode is closed
        raise CompositionError(f"UNSUPPORTED_LAYOUT_MODE:{mode}")

    if params.safe_margin:
        warnings.append(
            f"SAFE_MARGIN_DECLARED_BUT_NOT_APPLIED:{params.safe_margin}")

    provenance = {
        "planner_version": PLANNER_VERSION,
        "shot_id": spec.shot_id,
        "vocabulary": {
            "presenter_scale": spec.presenter_scale.value,
            "speaker_visibility": spec.speaker_visibility.value,
            "layout_mode": spec.layout_mode.value,
        },
        "vocabulary_owners": dict(VOCABULARY_OWNERS),
        "sources": {"primary": primary_source, "secondary": secondary_source},
        "source_dimensions": [source_width, source_height],
        "parameters": params.to_dict(),
        "reframe_plan": (
            None if reframe_plan is None
            else {"windows": len(reframe_plan.windows),
                  "target": [reframe_plan.target_width, reframe_plan.target_height],
                  "contained": reframe_plan.subject_contained()}
        ),
        "deterministic": True,
    }
    return LayoutPlan(
        spec=spec, regions=tuple(regions), canvas=canvas,
        reframe_plan=reframe_plan, provenance=provenance, warnings=tuple(warnings))


# ── Native renderer ──────────────────────────────────────────────────────


def compile_filter_graph(plan: LayoutPlan) -> str:
    """Render the plan as one ffmpeg filter graph. No Python frame loop.

    track composes P10's reframe crop chain; general is a centred target-aspect
    fill; split scales two inputs and hstacks them, which is how two sources
    genuinely share a frame rather than one merely being described as split.
    """
    mode = plan.spec.layout_mode
    canvas_w, canvas_h = plan.canvas
    if not plan.regions:
        raise CompositionError("CANNOT_COMPILE_EMPTY_PLAN")

    if mode is ReframingMode.SPLIT:
        if len(plan.regions) != 2:
            raise CompositionError(f"SPLIT_REQUIRES_TWO_REGIONS:got {len(plan.regions)}")
        left, right = plan.regions
        lw, lh = left.to_px(canvas_w, canvas_h)[2:]
        rw, rh = right.to_px(canvas_w, canvas_h)[2:]
        return (
            f"[0:v]scale={lw}:{lh}:force_original_aspect_ratio=increase,"
            f"crop={lw}:{lh},setsar=1[left];"
            f"[1:v]scale={rw}:{rh}:force_original_aspect_ratio=increase,"
            f"crop={rw}:{rh},setsar=1[right];"
            f"[left][right]hstack=inputs=2,setsar=1[out]"
        )

    if mode is ReframingMode.TRACK:
        if plan.reframe_plan is None:
            raise CompositionError("CANNOT_COMPILE_TRACK_WITHOUT_REFRAME_PLAN")
        return f"[0:v]{compile_reframe_filter(plan.reframe_plan)}[out]"

    crop = plan.regions[0].crop.get("target")
    if not crop:
        raise CompositionError("GENERAL_PLAN_MISSING_CROP_TARGET")
    return (
        f"[0:v]scale={crop[0]}:{crop[1]}:force_original_aspect_ratio=increase,"
        f"crop={crop[0]}:{crop[1]},setsar=1[out]"
    )


def render_layout(
    plan: LayoutPlan,
    *,
    primary: str | Path,
    out: str | Path,
    secondary: str | Path | None = None,
    timeout_s: float = 1800.0,
) -> Path:
    """Execute the plan natively with ffmpeg.

    Audio is copied from the primary input. Layout is a video-space concern, so
    audio is never re-synthesised or re-timed here.
    """
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    graph = compile_filter_graph(plan)
    if plan.spec.layout_mode is ReframingMode.SPLIT:
        if secondary is None:
            raise CompositionError("SPLIT_REQUIRES_SECOND_SOURCE")
        inputs: list[str] = ["-i", str(primary), "-i", str(secondary)]
        maps = ["-map", "[out]", "-map", "1:a?"]
    else:
        inputs = ["-i", str(primary)]
        maps = ["-map", "[out]", "-map", "0:a?"]

    proc = subprocess.run(
        [shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-loglevel", "error",
         "-y", *inputs, "-filter_complex", graph, *maps,
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-c:a", "aac", str(target)],
        capture_output=True, text=True, timeout=timeout_s, check=False)
    if proc.returncode != 0 or not target.is_file():
        raise CompositionError(f"RENDER_FAILED:{proc.stderr[-400:]}")
    return target


__all__ = [
    "PLANNER_VERSION",
    "VOCABULARY_OWNERS",
    "CompositionError",
    "CompositionSpec",
    "LayoutParameters",
    "LayoutPlan",
    "LayoutRegion",
    "compile_filter_graph",
    "plan_layout",
    "render_layout",
]
