"""P0.6 — VisualSceneIR → HTML/Gsap.

The seam this file enforces
---------------------------
§19 draws one forbidden edge:

    VisualIntent → direct HTML          # forbidden

The allowed path is:

    VisualSceneIR → HtmlGsapAdapter → RenderPlan → HtmlGsapRenderer → browser → frames

Why the adapter compiles *into* ``RenderPlan`` rather than rewriting the renderer
----------------------------------------------------------------------------------------
`hevi/renderers/html_gsap.py` is the canonical HTML/Gsap authority and §0.1 forbids a
second one. Rewriting it to consume a scene graph would replace that authority and
risk the existing P5.2 acceptance path, which §48 requires to keep passing.

So this is a compiler, not a renderer. It lowers a `VisualSceneIR` to the
`RenderPlan` the renderer already understands, and it is the *only* new place scene
semantics are decided. A renderer that took a `VisualIntent` directly would be
re-deriving layout per backend, which is the divergence the IR exists to prevent.

Why unsupported components raise
--------------------------------
§49 V6. An element type with no mapping must fail here, loudly. Silently dropping it
produces a scene that constructs, passes validation, renders, and is missing content --
the failure surfaces three modules downstream with a symptom pointing nowhere near the
cause. The adapter is where a component's fate is decided, so a component with no fate
is an error here and not a blank frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hevi.production.visual_scene_ir import (
    VisualElement,
    VisualElementType,
    VisualSceneIR,
)
from hevi.renderers.base import RenderPlan

#: Element types this adapter knows how to lower. Anything else raises.
#:
#: AUDIO_MARKER and GROUP are intentionally absent from the *positional* set: a group
#: has no geometry of its own and an audio marker is not drawn. Both are still accepted
#: by the scene IR, and both are reported here rather than silently dropped, because a
#: caller that composed a group and saw it vanish would have no way to tell a bug from
#: intent.
_SUPPORTED_POSITIONAL = frozenset(
    {
        VisualElementType.TEXT,
        VisualElementType.IMAGE,
        VisualElementType.VIDEO,
        VisualElementType.SHAPE,
        VisualElementType.SVG,
    }
)

_SUPPORTED_STRUCTURAL = frozenset(
    {
        VisualElementType.GROUP,
        VisualElementType.AUDIO_MARKER,
        VisualElementType.FLOW,
        VisualElementType.SEQUENCE,
        VisualElementType.TREE,
        VisualElementType.TIMELINE,
        VisualElementType.TABLE,
        VisualElementType.CALLOUT,
        VisualElementType.KV,
    }
)

#: AnswerHTML's component kinds (§20) flatten into a text element: their layout is
#: resolved here, deterministically, before the renderer sees them. The renderer never
#: gets to decide how a table is arranged.
_CONTENT_COMPONENTS = {
    VisualElementType.FLOW,
    VisualElementType.SEQUENCE,
    VisualElementType.TREE,
    VisualElementType.TIMELINE,
    VisualElementType.TABLE,
    VisualElementType.CALLOUT,
    VisualElementType.KV,
}


class UnsupportedSceneComponent(ValueError):
    """An element type this adapter cannot lower (§49 V6)."""


@dataclass(frozen=True)
class CompiledScene:
    """The lowered scene: a ``RenderPlan`` plus the facts the receipt will need.

    ``scene_hash`` and the animation state travel alongside the plan because the render
    receipt (§12) must record them, and re-deriving them from the plan after the fact
    would let them drift from what was actually rendered.
    """

    plan: RenderPlan
    scene_hash: str
    animation_state_ms: tuple[int, ...]
    lowered_elements: tuple[str, ...]
    unlowered_elements: tuple[str, ...]


def _flatten_content(element: VisualElement) -> str:
    """Render a structured component to plain text.

    Deterministic by construction: keys are visited in sorted order so two runs over
    equal content produce equal text, which is what keeps the scene hash stable.
    """
    content = element.content
    if element.element_type is VisualElementType.TABLE:
        rows = content.get("rows", [])
        return "\n".join(
            " | ".join(str(cell) for cell in row) if isinstance(row, (list, tuple))
            else str(row)
            for row in rows
        )
    if element.element_type is VisualElementType.KV:
        pairs = content.get("pairs", {})
        if isinstance(pairs, dict):
            return "\n".join(f"{k}: {pairs[k]}" for k in sorted(pairs))
        return "\n".join(str(p) for p in pairs)
    if element.element_type in (
        VisualElementType.FLOW,
        VisualElementType.SEQUENCE,
        VisualElementType.TIMELINE,
    ):
        items = content.get("items", [])
        return "\n".join(str(item) for item in items)
    if element.element_type is VisualElementType.TREE:
        nodes = content.get("nodes", [])
        return "\n".join(str(node.get("label", node)) for node in nodes)
    if element.element_type is VisualElementType.CALLOUT:
        return f"{content.get('title', '')}\n{content.get('body', '')}".strip()
    return str(content.get("text", ""))


def compile_scene(
    scene: VisualSceneIR,
    *,
    shot_id: str = "",
    audio_lock_id: str = "",
    semantic_intent: str = "",
) -> CompiledScene:
    """Lower a scene into a ``RenderPlan``.

    This is the only place scene semantics are interpreted. The renderer receives a
    plan and does layout-free rendering; it does not read the scene graph.
    """
    unsupported = [
        element.element_id
        for element in scene.elements
        if element.element_type
        not in (_SUPPORTED_POSITIONAL | _SUPPORTED_STRUCTURAL)
    ]
    if unsupported:
        raise UnsupportedSceneComponent(
            f"UNSUPPORTED_SCENE_COMPONENT:{sorted(unsupported)}"
        )

    lowered: list[str] = []
    unlowered: list[str] = []
    captions: list[str] = []

    for element in scene.elements:
        if element.element_type in _CONTENT_COMPONENTS:
            captions.append(_flatten_content(element))
            lowered.append(element.element_id)
        elif element.element_type in _SUPPORTED_POSITIONAL:
            captions.append(_primary_text(element))
            lowered.append(element.element_id)
        else:
            # GROUP / AUDIO_MARKER carry no drawable content of their own. Reported, not
            # dropped silently -- see the module docstring.
            unlowered.append(element.element_id)

    animation_times = _animation_sample_times(scene)

    plan = RenderPlan(
        shot_id=shot_id or scene.scene_id,
        duration_s=scene.duration_ms / 1000.0,
        motion_purposes=[a.animation_id for a in scene.animations],
        asset_refs=list(scene.asset_refs),
        caption_text="\n".join(c for c in captions if c),
        audio_lock_id=audio_lock_id,
        required_evidence=["scene_hash", "timeline_hash"],
        semantic_intent=semantic_intent,
        width=scene.width,
        height=scene.height,
        fps=_fps_for(scene),
        extra=_extra_for(scene, animation_times),
    )

    return CompiledScene(
        plan=plan,
        scene_hash=scene.content_hash(),
        animation_state_ms=animation_times,
        lowered_elements=tuple(lowered),
        unlowered_elements=tuple(unlowered),
    )


def _primary_text(element: VisualElement) -> str:
    if element.element_type is VisualElementType.TEXT:
        return str(element.content.get("text", ""))
    if element.element_type is VisualElementType.SHAPE:
        return str(element.content.get("label", ""))
    return ""


def _animation_sample_times(scene: VisualSceneIR) -> tuple[int, ...]:
    """The instants a renderer must be able to reproduce.

    Every animation's start and end, plus the scene end. A renderer driven at other
    times must interpolate, and these are the points where it has to agree with
    ``VisualSceneIR.state_at``.
    """
    times = {0, scene.duration_ms}
    for animation in scene.animations:
        times.add(animation.start_ms)
        times.add(animation.end_ms)
    return tuple(sorted(t for t in times if 0 <= t <= scene.duration_ms))


def _fps_for(scene: VisualSceneIR) -> int:
    """The scene's exact frame rate, narrowed to what ``RenderPlan`` can carry.

    ``RenderPlan.fps`` is typed ``int`` in the existing renderer base, so an exact
    fractional rate (30000/1001) cannot be represented there without widening that
    contract. Rather than silently rounding -- which would put a different frame rate in
    the render than the scene declared -- the exact value travels in
    ``extra["fps_exact"]`` and a non-integral rate is refused here.

    Integral rates (24, 25, 30, 60) pass through unchanged, which is what the E2E and
    the existing P5.2 acceptance path use.
    """
    if scene.fps.denominator != 1:
        raise UnsupportedSceneComponent(
            f"NON_INTEGER_FPS_NOT_REPRESENTABLE:{scene.fps}; RenderPlan.fps is an int. "
            "Widening hevi/renderers/base.py is required before a fractional rate can "
            "be rendered -- rounding it here would render at a different rate than the "
            "scene declares."
        )
    return int(scene.fps)


def _extra_for(scene: VisualSceneIR, animation_times: tuple[int, ...]) -> dict[str, Any]:
    """Facts the existing renderer already reads, plus the ones it will need.

    ``background``/``title``/``title_size`` are consumed by ``html_gsap`` today. The
    ``scene_*`` keys are additive and inert to the current renderer, which is what lets
    this land without rewriting it; a later step consumes them to drive real frames.
    """
    title = ""
    title_size = 44
    for element in scene.elements:
        if element.element_type is VisualElementType.TEXT and not title:
            title = str(element.content.get("text", ""))
            title_size = int(element.content.get("font_size", 44))
            break

    return {
        "background": scene.background.color,
        "accent": scene.background.color,
        "title": title,
        "title_size": title_size,
        "scene_hash": scene.content_hash(),
        "scene_duration_ms": scene.duration_ms,
        "fps_exact": str(scene.fps),
        "layout_mode": scene.layout_mode.value,
        "animation_sample_times_ms": list(animation_times),
        "element_count": len(scene.elements),
    }


def frame_state(scene: VisualSceneIR, time_ms: int) -> dict[str, Any]:
    """The frame state at ``time_ms``, as the renderer would need it (§18 V2/V3).

    Exposed so a caller can prove a renderer honoured the IR: compare this against
    what the renderer actually drew. A renderer that re-derives animation state instead
    of reading it is the failure this makes visible.
    """
    return {
        "time_ms": time_ms,
        "state": scene.state_at(time_ms),
        "frame_identity": scene.frame_identity(time_ms),
    }


__all__ = [
    "CompiledScene",
    "UnsupportedSceneComponent",
    "compile_scene",
    "frame_state",
]
