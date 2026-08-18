"""EchoMimicV2 talking-face via ComfyUI (AIFSH node, 10G envelope).

ComfyUI 必须用 `bash /home/soffy/ComfyUI/start-echomimic.sh` 起
(`--medvram`, 勿套 H3 的 `--reserve-vram 5`)。与 H3 互斥,共用 8188。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from hevi.gpu import VRAM_H3_LOCAL, scheduler
from hevi.providers.h3_local.comfy_client import ComfyClient, H3ComfyError

logger = logging.getLogger(__name__)

ECHO_MIMIC_CAPABILITY: dict[str, Any] = {
    "id": "echo_mimic",
    "capabilities": ["talking_face", "lip_sync"],
    "max_duration_sec": 10,
    "resolution": ["512"],
    "ref_image": True,
    "cost_per_sec": 0,
    "health": "local_comfy",
    "entrypoint": "comfyui",
    "workflow": "echomimic_v2_10g.json",
    "vram_profile": "10gb_medvram_chunked",
    "notes": "AIFSH EchoMimicV2; 512² FP16; duration=120 frames (~5s) chunks",
}

_WORKFLOWS_DIR = Path(__file__).resolve().parent / "workflows"
_DEFAULT_WIDTH = 512
_DEFAULT_HEIGHT = 512
_DEFAULT_STEPS = 20
_DEFAULT_DURATION = 120  # frames per chunk; 120 ≈ 5s @ 24fps
_DEFAULT_TIMEOUT_S = 1800.0


def _client() -> ComfyClient:
    return ComfyClient(
        base_url=os.getenv("ECHO_MIMIC_COMFY_URL") or os.getenv("H3_COMFY_URL"),
        timeout_s=float(os.getenv("ECHO_MIMIC_TIMEOUT_S", str(_DEFAULT_TIMEOUT_S))),
        workflows_dir=_WORKFLOWS_DIR,
    )


async def echo_mimic_generate(
    *,
    image_path: Path | str,
    audio_path: Path | str,
    output_path: Path | str,
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
    steps: int = _DEFAULT_STEPS,
    duration: int = _DEFAULT_DURATION,
    seed: int | None = None,
) -> Path:
    """Photo + driving audio → talking-face mp4 (chunked, 512², FP16)."""
    image_path = Path(image_path)
    audio_path = Path(audio_path)
    output_path = Path(output_path)
    if not image_path.exists():
        raise H3ComfyError(f"参考图不存在: {image_path}")
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise H3ComfyError(f"驱动音频不存在或为空: {audio_path}")
    if max(width, height) > 768:
        raise H3ComfyError(f"10G 卡禁止 {width}x{height}(上限 768,推荐 512)")

    client = _client()
    if not await client.health():
        raise H3ComfyError(
            f"ComfyUI 不可达: {client.base_url}。"
            "EchoMimic 请用 bash /home/soffy/ComfyUI/start-echomimic.sh 启动"
            "(与 H3 互斥,GPU 需空闲)"
        )

    async with scheduler.acquire(VRAM_H3_LOCAL):
        comfy_image = await client.upload_image(image_path)
        comfy_audio = await client.upload_input(audio_path, mime="audio/wav")
        workflow = client.build_workflow(
            "echomimic_v2_10g.json",
            prompt="",
            width=width,
            height=height,
            seed=seed,
            ref_images=[comfy_image],
            extra_fills={
                "__AUDIO__": comfy_audio,
                "__DURATION__": int(duration),
                "__STEPS__": int(steps),
            },
        )
        logger.info(
            "echo_mimic queued %s + %s → %s (%dx%d steps=%d chunk=%d)",
            image_path.name,
            audio_path.name,
            output_path.name,
            width,
            height,
            steps,
            duration,
        )
        return await client.run_workflow(workflow, output_path=output_path)
