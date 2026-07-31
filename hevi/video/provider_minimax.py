"""MiniMax 视频 provider 适配 —— MiniMax via fal.ai。

对标 OpenMontage 的 minimax_video 工具。
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
class MiniMaxResult:
    video_url: str
    local_path: Path
    duration_s: float
    cost_usd: float


async def generate_minimax_clip(
    prompt: str,
    output_path: Path,
    *,
    duration_s: int = 5,
    resolution: str = "720p",
    aspect_ratio: str = "16:9",
    negative_prompt: str = "",
    image_url: str | None = None,
    timeout_s: int = 300,
) -> MiniMaxResult:
    """通过 fal.ai 生成 MiniMax 视频片段。"""
    fal_key = os.environ.get("FAL_KEY", "")
    if not fal_key:
        raise RuntimeError("FAL_KEY not set.")

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

    submit_result = subprocess.run(
        [
            "curl", "-s", "-X", "POST",
            "https://queue.fal.run/fal-ai/minimax/video-01",
            "-H", f"Authorization: Key {fal_key}",
            "-H", "Content-Type: application/json",
            "-d", json.dumps(payload),
        ],
        capture_output=True, text=True, timeout=30,
    )
    if submit_result.returncode != 0:
        raise RuntimeError(f"MiniMax submit failed: {submit_result.stderr}")

    submit_data = json.loads(submit_result.stdout)
    request_id = submit_data.get("request_id", "")
    if not request_id:
        raise RuntimeError(f"No request_id: {submit_data}")

    video_url = ""
    start = time.time()
    while time.time() - start < timeout_s:
        status_result = subprocess.run(
            [
                "curl", "-s",
                f"https://queue.fal.run/fal-ai/minimax/video-01/requests/{request_id}/status",
                "-H", f"Authorization: Key {fal_key}",
            ],
            capture_output=True, text=True, timeout=15,
        )
        status_data = json.loads(status_result.stdout)
        if status_data.get("status") == "COMPLETED":
            result_resp = subprocess.run(
                [
                    "curl", "-s",
                    f"https://queue.fal.run/fal-ai/minimax/video-01/requests/{request_id}",
                    "-H", f"Authorization: Key {fal_key}",
                ],
                capture_output=True, text=True, timeout=15,
            )
            result_data = json.loads(result_resp.stdout)
            videos = result_data.get("video", result_data.get("videos", []))
            if isinstance(videos, list) and videos:
                video_url = videos[0].get("url", "")
            elif isinstance(videos, dict):
                video_url = videos.get("url", "")
            break
        if status_data.get("status") in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"MiniMax {status_data.get('status')}")
        await asyncio.sleep(5)

    if not video_url:
        raise RuntimeError(f"MiniMax timed out after {timeout_s}s")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["curl", "-sL", "-o", str(output_path), video_url], check=True, timeout=120)

    cost = duration_s * 0.04  # MiniMax ~$0.04/s
    return MiniMaxResult(video_url=video_url, local_path=output_path,
                         duration_s=float(duration_s), cost_usd=round(cost, 4))
