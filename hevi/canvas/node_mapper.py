from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from oprim._hevi_types import CanvasNode

logger = logging.getLogger(__name__)

VALID_NODE_TYPES: frozenset[str] = frozenset({"text", "image", "video", "audio", "script"})


def _upstream_text(upstream: dict[str, Any]) -> str:
    """从上游节点输出里取文本(text 节点 output / 其它节点 content),拼成 prompt。
    canvas 是 DAG:video 节点常接在 text/script 节点后,用其输出做 prompt。"""
    parts: list[str] = []
    for out in upstream.values():
        if isinstance(out, dict):
            t = out.get("output") or out.get("content")
            if isinstance(t, str) and t.strip():
                parts.append(t.strip())
        elif isinstance(out, str) and out.strip():
            parts.append(out.strip())
    return " ".join(parts)


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
    """Video node — kernel 子类型走**真实**单片生成(canvas 成真 IR,§7-7)。

    此前返回回声 dict、不产片;现在 kernel 子类型调 `generate_clip`,prompt 优先取
    config,否则用上游 text/script 节点的输出。其它子类型(transition 等)暂留桩,待接
    `make_transition`/oskill。
    """
    cfg = node.config or {}
    sub = cfg.get("sub_type", "kernel")
    if sub != "kernel":
        return {"type": "video", "sub_type": sub, "config": cfg, "note": "stub — pending wiring"}

    from hevi.video.kernel_service import generate_clip

    prompt = cfg.get("prompt") or _upstream_text(upstream) or "scene"
    out = Path(cfg.get("output_path") or f"output/canvas/{node.node_id}.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    ref = cfg.get("reference_image")
    res = cfg.get("resolution") or [832, 480]
    path = await generate_clip(
        config=cfg.get("provider_config", {}),
        provider=cfg.get("provider", "wan_local"),
        mode=cfg.get("mode", "t2v"),
        prompt=prompt,
        reference_image=Path(ref) if ref else None,
        duration_s=float(cfg.get("duration_s", 5.0)),
        resolution=(int(res[0]), int(res[1])),
        audio_enabled=bool(cfg.get("audio_enabled", False)),
        output_path=out,
        quality=cfg.get("quality", "standard"),
    )
    logger.info("canvas video node %s → %s", node.node_id, path)
    return {"type": "video", "sub_type": "kernel", "output": str(path), "prompt": prompt}


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
                f"Unknown node type: {node.node_type!r}. Valid types: {sorted(VALID_NODE_TYPES)}"
            )
        result: Any = await fn(node, upstream_outputs)
        return result

    return executor
