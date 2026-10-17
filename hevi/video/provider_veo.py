"""Veo 视频 provider 适配 —— Google Veo 2/3 via fal.ai。

对标 OpenMontage 的 veo_video 工具(13 个视频 provider 之一)。
Hevi 已有 fal_image_service.py(图像),补上 fal 视频端点(Veo/Kling/MiniMax)。

用法:
    from hevi.video.provider_veo import generate_veo_clip
    result = await generate_veo_clip(
        prompt="A warrior draws his sword in a bamboo forest",
        output_path=Path("output/veo_clip.mp4"),
        duration_s=5,
    )
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class VeoResult:
    video_url: str
    local_path: Path
    duration_s: float
    cost_usd: float
    model: str


async def generate_veo_clip(
    prompt: str,
    output_path: Path,
    *,
    duration_s: int = 5,
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    model: str = "veo-2",
    negative_prompt: str = "",
    image_url: str | None = None,
    timeout_s: int = 300,
) -> VeoResult:
    """通过 fal.ai 生成 Veo 视频片段。

    Args:
        prompt: 视频描述
        output_path: 输出文件路径
        duration_s: 时长(5 或 10)
        resolution: 480p / 720p / 1080p
        aspect_ratio: 16:9 / 9:16 / 1:1
        model: veo-2 / veo-3
        negative_prompt: 负面提示词
        image_url: 可选参考图 URL(i2v 模式)
        timeout_s: 超时

    Returns:
        VeoResult
    """
    fal_key = os.environ.get("FAL_KEY", "")
    if not fal_key:
        raise RuntimeError("FAL_KEY not set. Required for Veo video generation.")

    endpoint = "fal-ai/veo-2" if model == "veo-2" else "fal-ai/veo-3"

    payload: dict[str, Any] = {
        "prompt": prompt,
        "duration": duration_s,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
    }
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    if image_url:
        payload["image_url"] = image_url

    # 提交任务
    import json
    import subprocess

    submit_result = subprocess.run(
        [
            "curl", "-s", "-X", "POST",
            f"https://queue.fal.run/{endpoint}",
            "-H", f"Authorization: Key {fal_key}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload),
        ],
        capture_output=True, text=True, timeout=30,
    )
    if submit_result.returncode != 0:
        raise RuntimeError(f"Veo submit failed: {submit_result.stderr}")

    submit_data = json.loads(submit_result.stdout)
    request_id = submit_data.get("request_id", "")
    if not request_id:
        raise RuntimeError(f"Veo submit returned no request_id: {submit_data}")

    # 轮询结果
    video_url = ""
    start = time.time()
    while time.time() - start < timeout_s:
        status_result = subprocess.run(
            [
                "curl", "-s",
                f"https://queue.fal.run/{endpoint}/requests/{request_id}/status",
                "-H", f"Authorization: Key {fal_key}",
            ],
            capture_output=True, text=True, timeout=15,
        )
        status_data = json.loads(status_result.stdout)
        status = status_data.get("status", "")

        if status == "COMPLETED":
            result_url = f"https://queue.fal.run/{endpoint}/requests/{request_id}"
            result_resp = subprocess.run(
                ["curl", "-s", result_url, "-H", f"Authorization: Key {fal_key}"],
                capture_output=True, text=True, timeout=15,
            )
            result_data = json.loads(result_resp.stdout)
            videos = result_data.get("video", result_data.get("videos", []))
            if isinstance(videos, list) and videos:
                video_url = videos[0].get("url", "")
            elif isinstance(videos, dict):
                video_url = videos.get("url", "")
            break
        if status in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"Veo generation {status}: {status_data}")

        await asyncio.sleep(5)

    if not video_url:
        raise RuntimeError(f"Veo generation timed out after {timeout_s}s")

    # 下载
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["curl", "-sL", "-o", str(output_path), video_url],
        check=True, timeout=120,
    )

    # 成本估算(Veo 2: ~$0.05/s, Veo 3: ~$0.10/s)
    price_per_s = 0.10 if model == "veo-3" else 0.05
    cost = duration_s * price_per_s

    return VeoResult(
        video_url=video_url,
        local_path=output_path,
        duration_s=float(duration_s),
        cost_usd=round(cost, 4),
        model=model,
    )
