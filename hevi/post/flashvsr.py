"""FlashVSR 超分(ComfyUI 节点包 1038lab/ComfyUI-FlashVSR)—— raw 画面 → 2× 超分,音频不动。

连接图(8GB 版,与 hevi 约定一致):

    VHS_LoadVideoPath(输入 raw)
      → AILab_FlashVSR_Advanced
          model_version = "Tiny Long (Low VRAM)"   ← tiny-long 低显存档
          enable_tiling / tile_size 256 / tile_overlap 24
          unload_model(VAE 解码前卸载 DiT)/ vae_tiling / sageattention=disable
      → VHS_VideoCombine(纯画面,无音频)   ← 音频由 pipeline 从 raw 原轨回混

模型:节点包首次运行时自动从 HF(1038lab/FlashVSR)下载到
`ComfyUI/models/FlashVSR/`(FlashVSR1_1/LQ_proj_in/TCDecoder/Wan2.1_VAE/Prompt,
约 6.7GB)。节点类缺失时抛 FlashVSRUnavailable,由 pipeline 降级交付 raw ——
绝不假装成功。

工作流模板在 `hevi/post/workflows/flashvsr_2x.json`(占位符约定同 h3 模板)。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from hevi.providers.h3_local.comfy_client import ComfyClient, H3ComfyError

logger = logging.getLogger(__name__)

#: FlashVSR 工作流模板(可经 POST_FLASHVSR_WORKFLOW 换用户自己的)。
_DEFAULT_WORKFLOW = "flashvsr_2x"
_WORKFLOWS_DIR = Path(__file__).resolve().parent / "workflows"
#: 模板依赖的节点类(运行时用 /object_info 核对,缺了就明确不可用)。
_REQUIRED_NODE_CLASSES = (
    "VHS_LoadVideoPath",
    "AILab_FlashVSR_Advanced",
    "VHS_VideoCombine",
)


class FlashVSRUnavailable(Exception):
    """FlashVSR 不可用(节点未安装 / ComfyUI 不可达 / 模板缺失)。调用方降级交付 raw。"""


async def require_nodes(client: ComfyClient, classes: tuple[str, ...]) -> None:
    """核对 ComfyUI 是否装了这些节点类;缺任一 → FlashVSRUnavailable。"""
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10.0) as c:
            r = await c.get(f"{client.base_url}/object_info")
            r.raise_for_status()
            available = set(r.json().keys())
    except Exception as e:
        raise FlashVSRUnavailable(f"ComfyUI 不可达({client.base_url}): {e}") from e
    missing = [k for k in classes if k not in available]
    if missing:
        raise FlashVSRUnavailable(
            "FlashVSR 节点未安装: " + ", ".join(missing)
            + "（装 1038lab/ComfyUI-FlashVSR 后重试;或 POST_UPSCALE=off 降级交付 raw）"
        )


async def upscale_flashvsr(
    input_path: Path | str,
    output_path: Path | str,
    *,
    config: dict[str, Any] | None = None,
    client: ComfyClient | None = None,
    fps: int = 24,
    timeout_s: float | None = None,
) -> Path:
    """raw → FlashVSR 2× 超分(纯画面)。输出路径含视频,音频由 pipeline 回混。

    Raises:
        FlashVSRUnavailable: 节点缺失 / ComfyUI 不可达 / 模板缺。
        H3ComfyError: 提交或执行失败(调用方可决定重试或降级)。
    """
    cfg = config or {}
    inp, outp = Path(input_path), Path(output_path)
    if not inp.exists():
        raise FlashVSRUnavailable(f"FlashVSR 输入不存在: {inp}")

    client = client or ComfyClient(
        base_url=cfg.get("comfy_url") or os.getenv("H3_COMFY_URL"),
        timeout_s=timeout_s,
    )
    await require_nodes(client, _REQUIRED_NODE_CLASSES)

    workflow_name = str(
        cfg.get("workflow") or os.getenv("POST_FLASHVSR_WORKFLOW") or _DEFAULT_WORKFLOW
    )
    workflow = client.build_workflow(
        workflow_name,
        output_prefix=f"h3_vsr_{outp.stem[:40]}",
        extra_fills={"__VIDEO_PATH__": str(inp.resolve()), "__FPS__": float(fps)},
        workflows_dir=_WORKFLOWS_DIR,
    )
    try:
        return await client.run_workflow(workflow, output_path=outp, timeout_s=timeout_s)
    except H3ComfyError as e:
        logger.error("FlashVSR 执行失败: %s", e)
        raise
