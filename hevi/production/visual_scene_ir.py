"""P0.5 — the renderer-independent declarative scene.

Why a scene IR exists at all
----------------------------
`hevi/renderers/html_gsap.py` builds HTML from a `RenderPlan` that carries a title, a
caption, a background and a handful of knobs. That is fine for what it renders and it
cannot express a scene graph.

The alternative -- letting each renderer interpret a `VisualIntent` directly -- is
what §19 forbids. It makes every renderer a second semantic compiler: the same intent
produces different output per renderer, and a defect can be fixed in one renderer and
still ship in another. The IR sits in front so scene *semantics* are decided once.

AnswerHTML's contribution, taken honestly
-----------------------------------------
§20 asks for its component DSL, deterministic layout and `marked` + `@dagrejs/dagre`
content graph. What is absorbed here is the *shape* -- typed components over content,
layout resolved by the compiler rather than the renderer -- not the runtime. `flow`,
`sequence`, `tree`, `timeline`, `table`, `callout` and `kv` are component kinds
(§16), and layout is a declared `LayoutSpec` the renderer must honour rather than
recompute.

Determinism is the invariant
----------------------------
    same scene + same time_ms + same renderer version + same assets
    + same environment  ==  same frame

``content_hash`` excludes `metadata`, because metadata is provenance -- who authored
the scene, which intent produced it -- and must not change the identity of the frames
it describes. Including it would make every annotation invalidate the render cache.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

#: §17. All temporal values are integer milliseconds, matching ``TimelineIR``.
#: Floats here would reintroduce exactly the drift the timeline migration removed.
_MS_PER_SECOND = 1000


class VisualElementType(StrEnum):
    """§16. The minimum component set."""

    TEXT = "TEXT"
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    SHAPE = "SHAPE"
    SVG = "SVG"
    GROUP = "GROUP"
    AUDIO_MARKER = "AUDIO_MARKER"
    # §20 AnswerHTML components, as typed kinds over content. These are compiler
    # inputs, not a second renderer: the HTML/Gsap adapter compiles them to elements.
    FLOW = "FLOW"
    SEQUENCE = "SEQUENCE"
    TREE = "TREE"
    TIMELINE = "TIMELINE"
    TABLE = "TABLE"
    CALLOUT = "CALLOUT"
    KV = "KV"


class LayoutMode(StrEnum):
    """§20's deterministic layout, declared rather than recomputed.

    The renderer is told how to arrange content. It does not get to decide, because
    two renderers deciding differently is precisely the divergence this IR prevents.
    """

    ABSOLUTE = "ABSOLUTE"
    #: CSS flow, resolved deterministically by the adapter.
    FLOW = "FLOW"
    #: Layered graph layout (the dagre-style approach AnswerHTML uses).
    GRAPH = "GRAPH"
    STACK = "STACK"


class BackgroundSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str = "solid"
    color: str = "#000000"
    asset_ref_id: str | None = None

    @field_validator("color")
    @classmethod
    def _hex_colour(cls, value: str) -> str:
        # Adapters interpolate colour into CSS/SVG; validating the shape here keeps a
        # typo from becoming an unstyled frame rather than a build error.
        if not value.startswith("#") or len(value) not in (4, 7, 9):
            raise ValueError(f"BACKGROUND_BAD_COLOUR:{value!r}; expected #rgb/#rrggbb")
        return value


class TransformSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    translate_x: float = 0.0
    translate_y: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0
    rotate_deg: float = 0.0
    origin_x: float = 0.5
    origin_y: float = 0.5

    @model_validator(mode="after")
    def _non_degenerate(self) -> Self:
        if self.scale_x == 0.0 or self.scale_y == 0.0:
            raise ValueError("TRANSFORM_ZERO_SCALE: a zero scale is not renderable")
        return self


class VisualElement(BaseModel):
    """One positioned thing in the scene."""

    model_config = ConfigDict(frozen=True)

    element_id: str
    element_type: VisualElementType

    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    z_index: int = 0
    opacity: float = 1.0
    visible: bool = True

    transform: TransformSpec = Field(default_factory=TransformSpec)
    content: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("element_id")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("VISUAL_ELEMENT_WITHOUT_ID")
        return value

    @field_validator("opacity")
    @classmethod
    def _opacity_in_range(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"VISUAL_ELEMENT_BAD_OPACITY:{value}")
        return value

    @model_validator(mode="after")
    def _typed_content_present(self) -> Self:
        """A non-GROUP element must carry content.

        An IMAGE with no source or a TEXT with no text is not a scene that renders to
        something wrong -- it is a scene that renders to a blank frame and passes
        validation. Rejecting it here turns that into a build error.
        """
        if self.element_type is VisualElementType.GROUP:
            return self
        if not self.content:
            raise ValueError(
                f"VISUAL_ELEMENT_WITHOUT_CONTENT:{self.element_id}:{self.element_type.value}"
            )
        if self.element_type is VisualElementType.TEXT and not str(
            self.content.get("text", "")
        ).strip():
            raise ValueError(f"VISUAL_ELEMENT_EMPTY_TEXT:{self.element_id}")
        if self.element_type in (
            VisualElementType.IMAGE,
            VisualElementType.VIDEO,
        ) and not (self.content.get("asset_ref_id") or self.content.get("uri")):
            raise ValueError(f"VISUAL_ELEMENT_MEDIA_WITHOUT_SOURCE:{self.element_id}")
        return self


class Keyframe(BaseModel):
    model_config = ConfigDict(frozen=True)

    time_ms: int
    value: float

    @field_validator("time_ms")
    @classmethod
    def _non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("KEYFRAME_NEGATIVE_TIME")
        return value


class AnimationSpec(BaseModel):
    """§17. A property animated over a time range, in integer milliseconds."""

    model_config = ConfigDict(frozen=True)

    animation_id: str
    element_id: str

    property: str
    keyframes: tuple[Keyframe, ...]
    easing: str = "linear"
    start_ms: int = 0
    end_ms: int = 0

    @field_validator("animation_id", "element_id", "property")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("ANIMATION_EMPTY_REQUIRED_FIELD")
        return value

    @model_validator(mode="after")
    def _keyframes_are_ordered_and_in_range(self) -> Self:
        if len(self.keyframes) < 2:
            raise ValueError(
                f"ANIMATION_NEEDS_TWO_KEYFRAMES:{self.animation_id}; a single keyframe "
                "is a static value and should be set on the element"
            )
        if self.end_ms <= self.start_ms:
            raise ValueError(f"ANIMATION_EMPTY_RANGE:{self.animation_id}")
        times = [k.time_ms for k in self.keyframes]
        if times != sorted(times):
            raise ValueError(f"ANIMATION_KEYFRAMES_UNORDERED:{self.animation_id}")
        for t in times:
            if not self.start_ms <= t <= self.end_ms:
                raise ValueError(
                    f"ANIMATION_KEYFRAME_OUT_OF_RANGE:{self.animation_id}:{t}"
                )
        return self

    def value_at(self, time_ms: int) -> float:
        """The interpolated value at ``time_ms``.

        ``easing`` is honoured only for ``linear`` and the two common eases; an unknown
        easing degrades to linear rather than raising, because an easing typo must not
        abort a render that is otherwise well-formed.
        """
        clamped = min(max(time_ms, self.start_ms), self.end_ms)
        first, last = self.keyframes[0], self.keyframes[-1]
        span = last.time_ms - first.time_ms
        if span <= 0:
            return first.value
        raw = (clamped - first.time_ms) / span
        eased = _apply_easing(raw, self.easing)
        return first.value + (last.value - first.value) * eased


_EASINGS: dict[str, Callable[[float], float]] = {
    "linear": lambda t: t,
    "ease_in": lambda t: t * t,
    "ease_out": lambda t: 1 - (1 - t) ** 2,
    "ease_in_out": lambda t: 2 * t * t if t < 0.5 else 1 - ((-2 * t + 2) ** 2) / 2,
}


def _apply_easing(t: float, easing: str) -> float:
    fn: Callable[[float], float] = _EASINGS.get(easing, _EASINGS["linear"])
    return fn(t)


class TransitionSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    transition_id: str
    kind: str
    duration_ms: int = 0
    from_element_id: str | None = None
    to_element_id: str | None = None

    @field_validator("transition_id", "kind")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("TRANSITION_EMPTY_REQUIRED_FIELD")
        return value

    @field_validator("duration_ms")
    @classmethod
    def _non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("TRANSITION_NEGATIVE_DURATION")
        return value


class VisualSceneIR(BaseModel):
    """§15. A renderer-independent declarative scene.

    ``metadata`` is deliberately excluded from ``content_hash``: it records provenance
    (authoring intent, which director beat produced this) and must not change the
    identity of the frames it describes.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: str = "1.0"

    scene_id: str
    width: int
    height: int
    duration_ms: int

    background: BackgroundSpec = Field(default_factory=BackgroundSpec)
    layout_mode: LayoutMode = LayoutMode.ABSOLUTE

    elements: tuple[VisualElement, ...] = ()
    animations: tuple[AnimationSpec, ...] = ()
    transitions: tuple[TransitionSpec, ...] = ()
    asset_refs: tuple[str, ...] = ()

    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("scene_id")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("VISUAL_SCENE_WITHOUT_ID")
        return value

    @field_validator("width", "height")
    @classmethod
    def _positive_dimensions(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("VISUAL_SCENE_NON_POSITIVE_DIMENSION")
        return value

    @field_validator("duration_ms")
    @classmethod
    def _non_negative_duration(cls, value: int) -> int:
        if value < 0:
            raise ValueError("VISUAL_SCENE_NEGATIVE_DURATION")
        return value

    @model_validator(mode="after")
    def _references_resolve(self) -> Self:
        element_ids = [e.element_id for e in self.elements]
        if len(set(element_ids)) != len(element_ids):
            raise ValueError(f"VISUAL_SCENE_DUPLICATE_ELEMENT_ID:{self.scene_id}")
        known = set(element_ids)
        for animation in self.animations:
            if animation.element_id not in known:
                raise ValueError(
                    f"VISUAL_SCENE_ANIMATION_ORPHAN:{animation.animation_id}:"
                    f"{animation.element_id}"
                )
        for transition in self.transitions:
            for ref in (transition.from_element_id, transition.to_element_id):
                if ref is not None and ref not in known:
                    raise ValueError(
                        f"VISUAL_SCENE_TRANSITION_ORPHAN:{transition.transition_id}:{ref}"
                    )
        if self.duration_ms and any(
            a.end_ms > self.duration_ms for a in self.animations
        ):
            raise ValueError(
                f"VISUAL_SCENE_ANIMATION_EXCEEDS_DURATION:{self.scene_id}; an animation "
                "ending after the scene does not render"
            )
        return self

    def element(self, element_id: str) -> VisualElement | None:
        return next((e for e in self.elements if e.element_id == element_id), None)

    def animations_for(self, element_id: str) -> tuple[AnimationSpec, ...]:
        return tuple(a for a in self.animations if a.element_id == element_id)

    def state_at(self, time_ms: int) -> dict[str, float]:
        """Animated property values at ``time_ms`` (V3).

        Every animation for the scene is evaluated, so the result is the complete
        animation state rather than one property's. Renderers need the whole state to
        compose a frame; giving them one property invites them to re-derive the rest.
        """
        return {a.property: a.value_at(time_ms) for a in self.animations}

    def content_hash(self) -> str:
        """Deterministic identity of the scene's semantics (V1)."""
        payload = {
            "animations": [
                {
                    "animation_id": a.animation_id,
                    "easing": a.easing,
                    "element_id": a.element_id,
                    "end_ms": a.end_ms,
                    "keyframes": [[k.time_ms, k.value] for k in a.keyframes],
                    "property": a.property,
                    "start_ms": a.start_ms,
                }
                for a in self.animations
            ],
            "background": self.background.model_dump(mode="json"),
            "dimensions": [self.width, self.height],
            "duration_ms": self.duration_ms,
            "elements": [
                {
                    "content": e.content,
                    "element_id": e.element_id,
                    "element_type": e.element_type.value,
                    "geometry": [e.x, e.y, e.width, e.height],
                    "opacity": e.opacity,
                    "transform": e.transform.model_dump(),
                    "visible": e.visible,
                    "z_index": e.z_index,
                }
                for e in self.elements
            ],
            "layout_mode": self.layout_mode.value,
            "scene_id": self.scene_id,
            "schema_version": self.schema_version,
            "transitions": [
                {
                    "duration_ms": t.duration_ms,
                    "from_element_id": t.from_element_id,
                    "kind": t.kind,
                    "to_element_id": t.to_element_id,
                    "transition_id": t.transition_id,
                }
                for t in self.transitions
            ],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()

    def frame_identity(self, time_ms: int) -> str:
        """V2: the identity of the frame at ``time_ms``.

        Scene hash plus the animation state at that instant. Two scenes that differ only
        outside the animated range still differ in scene hash, which is correct -- they
        are different scenes and must not share a cache entry.
        """
        payload = {
            "scene": self.content_hash(),
            "time_ms": time_ms,
            "state": {k: round(v, 9) for k, v in sorted(self.state_at(time_ms).items())},
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()


class FrameArtifact(BaseModel):
    """One rendered frame.

    ``frame_index`` rather than only a timestamp: a renderer may be driven at a
    variable rate, and a receipt that recorded only time could not distinguish two
    frames from the same millisecond.
    """

    model_config = ConfigDict(frozen=True)

    frame_index: int
    time_ms: int
    uri: str
    content_hash: str = ""
    width: int = 0
    height: int = 0

    @field_validator("frame_index", "time_ms")
    @classmethod
    def _non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("FRAME_NEGATIVE_INDEX_OR_TIME")
        return value


class RenderArtifact(BaseModel):
    """A finished render: frames plus the encoded result."""

    model_config = ConfigDict(frozen=True)

    uri: str
    content_hash: str
    duration_ms: int
    width: int
    height: int
    frame_count: int
    renderer: str
    renderer_version: str
    scene_hash: str = ""

    @field_validator("frame_count")
    @classmethod
    def _positive_frames(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("RENDER_ARTIFACT_NO_FRAMES")
        return value


class RenderTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    uri: str
    container: str = "mp4"
    video_codec: str = "h264"
    audio_codec: str | None = "aac"
    fps_numerator: int = 30
    fps_denominator: int = 1

    @field_validator("fps_numerator", "fps_denominator")
    @classmethod
    def _positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("RENDER_TARGET_NON_POSITIVE_FPS")
        return value


__all__ = [
    "AnimationSpec",
    "BackgroundSpec",
    "FrameArtifact",
    "Keyframe",
    "LayoutMode",
    "RenderArtifact",
    "RenderTarget",
    "TransformSpec",
    "TransitionSpec",
    "VisualElement",
    "VisualElementType",
    "VisualSceneIR",
]
