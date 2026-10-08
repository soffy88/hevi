"""P0.8 — HEVI operation ↔ OpenReel action mapping (§21, §42).

§42 is the constraint that matters: a mapping is not one-to-one.

    HEVI VISUAL_SCENE  ->  create_track, create_clip, set_transform, set_text, …

One HEVI operation fans out into several OpenReel actions, because OpenReel's action
layer is finer-grained than HEVI's operation layer. The reverse is deliberately *not*
implemented as "OpenReel actions become HEVI semantic intent" -- §42 forbids it, and
it would make OpenReel a semantic authority. Only the forward direction exists.

Every action carries ``depends_on`` so OpenReel's own runner can order them. HEVI does
not trust that ordering back: the canonical order stays ``resolve_execution_order`` in
``hevi.production.operation``.
"""

from __future__ import annotations

from hevi.adapters.openreel import OpenReelAction
from hevi.production.operation import (
    ArtifactExpectation,
    ProductionOperation,
    ProductionOperationType,
)


class UnsupportedOperation(ValueError):
    """An operation type with no OpenReel mapping."""


def map_operation(
    operation: ProductionOperation, *, scene_id: str = ""
) -> tuple[OpenReelAction, ...]:
    """Lower one HEVI operation into OpenReel actions.

    Returns a tuple because the mapping is one-to-many. An operation with no mapping
    raises rather than returning an empty tuple: an empty list would read to a caller
    as "ran and produced nothing", which is the §35 anti-pattern in a new costume.
    """
    scene = scene_id or operation.metadata.get("scene_id") or operation.production_id

    if operation.operation_type is ProductionOperationType.VISUAL_SCENE:
        return _visual_scene_actions(operation, scene)
    if operation.operation_type is ProductionOperationType.TIMELINE:
        return _timeline_actions(operation)
    if operation.operation_type is ProductionOperationType.MEDIA:
        return _media_actions(operation)
    if operation.operation_type is ProductionOperationType.AUDIO:
        return _audio_actions(operation)
    if operation.operation_type is ProductionOperationType.RENDER:
        return _render_actions(operation, scene)
    raise UnsupportedOperation(
        f"OPENREEL_UNMAPPED_OPERATION:{operation.operation_type.value}"
    )


def _visual_scene_actions(
    operation: ProductionOperation, scene_id: str
) -> tuple[OpenReelAction, ...]:
    """§42: one HEVI operation, several OpenReel actions.

    The order is fixed and documented so a caller can reason about it. The result is
    deliberately ordered -- OpenReel replays it in sequence, and a mapping that
    returned these in dictionary order would produce different timelines per run.
    """
    actions: list[OpenReelAction] = [
        OpenReelAction("create_track", {"scene_id": scene_id, "index": 0}),
        OpenReelAction(
            "create_clip",
            {"scene_id": scene_id, "track": 0, "duration_ms": operation.parameters.get(
                "duration_ms", 0
            )},
            depends_on=("create_track",),
        ),
        OpenReelAction(
            "set_transform",
            {
                "scene_id": scene_id,
                "track": 0,
                "transform": operation.parameters.get("transform", {}),
            },
            depends_on=("create_clip",),
        ),
    ]
    text = operation.parameters.get("text")
    if text is not None:
        actions.append(
            OpenReelAction(
                "set_text",
                {"scene_id": scene_id, "track": 0, "text": str(text)},
                depends_on=("create_clip",),
            )
        )
    keyframes = operation.parameters.get("keyframes")
    if keyframes:
        actions.append(
            OpenReelAction(
                "set_keyframe",
                {"scene_id": scene_id, "track": 0, "keyframes": keyframes},
                depends_on=("set_transform",),
            )
        )
    return tuple(actions)


def _timeline_actions(operation: ProductionOperation) -> tuple[OpenReelAction, ...]:
    """A timeline mutation maps to one atomic action.

    §3.1 forbids this from touching Director intent, and the payload carries only
    timeline data: track, clip, duration, alignment. No semantic fields are forwarded,
    because forwarding them would let an OpenReel timeline become a second semantic
    authority.
    """
    payload = {
        key: operation.parameters[key]
        for key in ("timeline_id", "track", "clip", "duration_ms", "align")
        if key in operation.parameters
    }
    return (OpenReelAction("mutate_timeline", payload),)


def _media_actions(operation: ProductionOperation) -> tuple[OpenReelAction, ...]:
    """§3.3: MEDIA materialises and normalises. It does not choose the asset.

    The source is whatever the canonical selector already decided, passed in as
    ``resolved_source``. Nothing here ranks or picks -- that would make the adapter an
    asset selector, which §62 lists as prohibited.
    """
    source = operation.parameters.get("resolved_source")
    if not source:
        raise UnsupportedOperation(
            f"OPENREEL_MEDIA_WITHOUT_RESOLVED_SOURCE:{operation.operation_id}; asset "
            "selection must happen in the canonical selector, not in an adapter"
        )
    return (
        OpenReelAction("import_media", {"source": source, "kind": operation.parameters.get(
            "kind", "video"
        )}),
    )


def _audio_actions(operation: ProductionOperation) -> tuple[OpenReelAction, ...]:
    actions = [
        OpenReelAction(
            "add_audio_track",
            {"kind": operation.parameters.get("audio_kind", "voice"),
             "uri": operation.parameters.get("uri", "")},
        )
    ]
    if operation.parameters.get("normalize"):
        actions.append(
            OpenReelAction("normalize_audio", {"track": 0},
                           depends_on=("add_audio_track",))
        )
    if operation.parameters.get("align_to"):
        actions.append(
            OpenReelAction("align_audio", {"track": 0,
                                           "align_to": operation.parameters["align_to"]},
                           depends_on=("add_audio_track",))
        )
    return tuple(actions)


def _render_actions(
    operation: ProductionOperation, scene_id: str
) -> tuple[OpenReelAction, ...]:
    return (
        OpenReelAction(
            "render",
            {
                "scene_id": scene_id,
                "output": operation.parameters.get("output", ""),
                "fps": operation.parameters.get("fps", 30),
            },
        ),
    )


def expected_outputs_for(
    operation: ProductionOperation,
) -> tuple[ArtifactExpectation, ...]:
    """Pass HEVI's declared expectations through unchanged.

    The mapping must not invent or drop outputs. An adapter that decided its own
    outputs would be a second statement of what a production produces.
    """
    return operation.expected_outputs


__all__ = [
    "UnsupportedOperation",
    "expected_outputs_for",
    "map_operation",
]
