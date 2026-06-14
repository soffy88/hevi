from __future__ import annotations

from collections.abc import Callable
from typing import Any

from oprim._hevi_types import CanvasNode

VALID_NODE_TYPES: frozenset[str] = frozenset({"text", "image", "video", "audio", "script"})

# Registry: node_type → executor key (for discovery / canvas node rendering)
NODE_EXECUTORS: dict[str, str] = {
    "text": "text_node_executor",
    "image": "image_node_executor",
    "video": "video_node_executor",
    "audio": "audio_node_executor",
    "script": "script_node_executor",
}


async def _text_executor(node: CanvasNode, upstream: dict[str, Any]) -> Any:
    """Text node — emits content / prompt text downstream."""
    return {
        "type": "text",
        "output": node.config.get("content", ""),
        "upstream_count": len(upstream),
    }


async def _image_executor(node: CanvasNode, upstream: dict[str, Any]) -> Any:
    """Image node — dispatches to three_view / multi_angle / storyboard_grid."""
    return {
        "type": "image",
        "sub_type": node.config.get("sub_type", "multi_angle"),
        "config": node.config,
    }


async def _video_executor(node: CanvasNode, upstream: dict[str, Any]) -> Any:
    """Video node — dispatches to kernel / transition."""
    return {
        "type": "video",
        "sub_type": node.config.get("sub_type", "kernel"),
        "config": node.config,
    }


async def _audio_executor(node: CanvasNode, upstream: dict[str, Any]) -> Any:
    """Audio node — dispatches to TTS / BGM."""
    return {
        "type": "audio",
        "sub_type": node.config.get("sub_type", "tts"),
        "config": node.config,
    }


async def _script_executor(node: CanvasNode, upstream: dict[str, Any]) -> Any:
    """Script node — dispatches to story_predict / storyboard."""
    return {
        "type": "script",
        "sub_type": node.config.get("sub_type", "storyboard"),
        "config": node.config,
    }


_EXECUTOR_MAP: dict[str, Callable[..., Any]] = {
    "text": _text_executor,
    "image": _image_executor,
    "video": _video_executor,
    "audio": _audio_executor,
    "script": _script_executor,
}


def create_node_executor() -> Callable[..., Any]:
    """Return the hevi node dispatch executor for canvas_workflow_executor."""

    async def executor(node: CanvasNode, upstream_outputs: dict[str, Any]) -> Any:
        fn = _EXECUTOR_MAP.get(node.node_type)
        if fn is None:
            raise ValueError(
                f"Unknown node type: {node.node_type!r}. "
                f"Valid types: {sorted(VALID_NODE_TYPES)}"
            )
        result: Any = await fn(node, upstream_outputs)
        return result

    return executor
