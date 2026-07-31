"""Seedance 2 视频 provider 适配 —— 字节跳动豆包视频生成。

能力:
- text-to-video: 文本生成视频
- image-to-video: 图片驱动视频
- video-extend: 视频续写（基于已有 request_id 续写）
- 音画原生同步（内置 audio-video sync）

用法:
    from hevi.video.provider_seedance import generate_seedance_clip
    result = await generate_seedance_clip(
        prompt="A dragon breathing fire in slow motion",
        output_path=Path("output/seedance.mp4"),
        mode="t2v",
    )
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SeedanceResult:
    video_url: str
    local_path: Path
    duration_s: float
    cost_usd: float
    mode: str  # t2v / i2v / extend
    request_id: str
    audio_url: str | None = None  # 原生音画同步时返回


async def generate_seedance_clip(
    prompt: str,
    output_path: Path,
    *,
    mode: str = "t2v",
    duration_s: int = 5,
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    image_url: str | None = None,
    extend_request_id: str | None = None,
    extend_prompt: str | None = None,
    seed: int | None = None,
    cfg_scale: float | None = None,
    timeout_s: int = 600,
) -> SeedanceResult:
    """通过 Seedance 2.0 API 生成视频片段。

    Args:
        prompt: 视频描述（t2v/i2v 时必须）
        output_path: 输出文件路径
        mode: t2v（文生视频）/ i2v（图生视频）/ extend（视频续写）
        duration_s: 时长（5 或 10）
        resolution: 480p / 720p / 1080p
        aspect_ratio: 16:9 / 9:16 / 1:1
        image_url: 参考图 URL（i2v 模式必须）
        extend_request_id: 已有 request_id（extend 模式必须）
        extend_prompt: 续写描述（extend 模式可选）
        seed: 随机种子
        cfg_scale: 引导强度
        timeout_s: 超时

    Returns:
        SeedanceResult
    """
    api_key = os.environ.get("SEEDANCE_API_KEY", "")
    api_base = os.environ.get("SEEDANCE_API_BASE", "https://api.seedance.ai/v1")

    if not api_key:
        raise RuntimeError("SEEDANCE_API_KEY not set. Required for Seedance 2 video generation.")

    # 构造请求
    payload: dict[str, Any] = {
        "model": "seedance-2.0",
        "duration": duration_s,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
    }

    if mode == "t2v":
        if not prompt:
            raise ValueError("prompt is required for t2v mode")
        payload["prompt"] = prompt
        endpoint = f"{api_base}/video/generations"

    elif mode == "i2v":
        if not image_url:
            raise ValueError("image_url is required for i2v mode")
        payload["image_url"] = image_url
        payload["prompt"] = prompt or ""
        endpoint = f"{api_base}/video/generations"

    elif mode == "extend":
        if not extend_request_id:
            raise ValueError("extend_request_id is required for extend mode")
        payload["extend_request_id"] = extend_request_id
        if extend_prompt:
            payload["prompt"] = extend_prompt
        endpoint = f"{api_base}/video/extend"

    else:
        raise ValueError(f"Unknown mode: {mode}. Use t2v, i2v, or extend.")

    if seed is not None:
        payload["seed"] = seed
    if cfg_scale is not None:
        payload["cfg_scale"] = cfg_scale

    # 提交任务
    submit_result = subprocess.run(
        [
            "curl", "-s", "-X", "POST", endpoint,
            "-H", f"Authorization: Bearer {api_key}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload),
        ],
        capture_output=True, text=True, timeout=30,
    )
    if submit_result.returncode != 0:
        raise RuntimeError(f"Seedance submit failed: {submit_result.stderr}")

    try:
        submit_data = json.loads(submit_result.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"Seedance submit returned invalid JSON: {submit_result.stdout[:500]}")

    request_id = submit_data.get("request_id", submit_data.get("id", ""))
    if not request_id:
        error = submit_data.get("error", submit_data.get("message", "unknown"))
        raise RuntimeError(f"Seedance submit returned no request_id: {error}")

    # 轮询结果
    video_url = ""
    audio_url = None
    start = time.time()

    while time.time() - start < timeout_s:
        status_result = subprocess.run(
            [
                "curl", "-s",
                f"{api_base}/video/generations/{request_id}",
                "-H", f"Authorization: Bearer {api_key}",
            ],
            capture_output=True, text=True, timeout=15,
        )
        try:
            status_data = json.loads(status_result.stdout)
        except json.JSONDecodeError:
            await asyncio.sleep(5)
            continue

        status = status_data.get("status", "")

        if status in ("completed", "succeeded", "COMPLETED"):
            videos = status_data.get("video", status_data.get("videos", status_data.get("output", {}).get("video", [])))
            if isinstance(videos, list) and videos:
                video_url = videos[0].get("url", "")
            elif isinstance(videos, dict):
                video_url = videos.get("url", "")
            elif isinstance(videos, str):
                video_url = videos

            # 检查是否有原生音频
            audio = status_data.get("audio", status_data.get("output", {}).get("audio"))
            if isinstance(audio, dict):
                audio_url = audio.get("url")
            elif isinstance(audio, str):
                audio_url = audio

            break

        if status in ("failed", "error", "FAILED", "CANCELLED"):
            error_msg = status_data.get("error", status_data.get("message", "unknown"))
            raise RuntimeError(f"Seedance generation {status}: {error_msg}")

        await asyncio.sleep(8)

    if not video_url:
        raise RuntimeError(f"Seedance generation timed out after {timeout_s}s")

    # 下载视频
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["curl", "-sL", "-o", str(output_path), video_url],
        check=True, timeout=120,
    )

    # 成本估算（Seedance 2: ~$0.08/s t2v, ~$0.12/s i2v, ~$0.06/s extend）
    price_map = {"t2v": 0.08, "i2v": 0.12, "extend": 0.06}
    price_per_s = price_map.get(mode, 0.08)
    cost = duration_s * price_per_s

    return SeedanceResult(
        video_url=video_url,
        local_path=output_path,
        duration_s=float(duration_s),
        cost_usd=round(cost, 4),
        mode=mode,
        request_id=request_id,
        audio_url=audio_url,
    )


# ── 便捷函数 ──────────────────────────────────────────────────────────────


async def seedance_text_to_video(
    prompt: str, output_path: Path, **kwargs: Any
) -> SeedanceResult:
    """Text-to-video 快捷入口。"""
    return await generate_seedance_clip(prompt, output_path, mode="t2v", **kwargs)


async def seedance_image_to_video(
    image_url: str, prompt: str, output_path: Path, **kwargs: Any
) -> SeedanceResult:
    """Image-to-video 快捷入口。"""
    return await generate_seedance_clip(
        prompt, output_path, mode="i2v", image_url=image_url, **kwargs
    )


async def seedance_extend_video(
    request_id: str, output_path: Path, prompt: str = "", **kwargs: Any
) -> SeedanceResult:
    """Video extend 快捷入口——基于已有视频续写。"""
    return await generate_seedance_clip(
        prompt, output_path, mode="extend", extend_request_id=request_id,
        extend_prompt=prompt, **kwargs
    )
