"""Vidu Reference-to-Video — cloud API, HEVI-EXEC-01 视频生成主通道。

官方文档(platform.vidu.com,2026-07 抓取):
  - 生成: POST https://api.vidu.com/ent/v2/reference2video
  - 查询: GET  https://api.vidu.com/ent/v2/tasks/{task_id}/creations
两者都用 `Authorization: Token {api_key}` 鉴权(不是 Bearer)。生成结果的 URL
只保留 24 小时,轮询到 state=success 后要立刻把视频下载落盘,不能只存 URL。

VIDU_API_KEY 读取方式同 oprim._fal_queue_generate 的惯例:优先 config dict 覆盖,
缺省回退环境变量,不经 hevi.core.config.Settings(密钥/凭据向来走 env,不进 Settings)。
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.vidu.com/ent/v2"
_DEFAULT_MODEL = "viduq3"
_TERMINAL_STATES = {"success", "failed"}


class ViduError(Exception):
    """Vidu 生成失败(缺 key、提交/轮询失败、超时,或产物为空)。"""


async def vidu_reference_to_video(
    *,
    prompt: str,
    reference_images: list[str],
    output_path: Path | str,
    config: dict[str, Any] | None = None,
    model: str = _DEFAULT_MODEL,
    duration: int | None = None,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    movement_amplitude: str = "auto",
    seed: int | None = None,
    bgm: bool = False,
    poll_interval_s: float = 5.0,
    timeout_s: float = 600.0,
) -> Path:
    """参考图(1-7 张 URL 或 base64)+ 文本 prompt → 生成视频,下载到 output_path。

    Args:
        reference_images: 1-7 个图片 URL 或 base64 字符串(角色/场景参考图)。
        model: viduq3-mix/viduq3-turbo/viduq3/viduq2-pro/viduq2/viduq1/vidu2.0。
        duration: 秒数,各 model 支持范围不同(如 viduq3-mix: 1-16s)。

    Raises:
        ViduError: VIDU_API_KEY 缺失、提交/轮询失败、超时,或产物为空。
    """
    cfg = config or {}
    api_key = cfg.get("VIDU_API_KEY") or os.getenv("VIDU_API_KEY")
    if not api_key:
        raise ViduError("VIDU_API_KEY not configured")
    if not 1 <= len(reference_images) <= 7:
        raise ViduError(f"reference_images must have 1-7 items, got {len(reference_images)}")

    output_path = Path(output_path)
    headers = {"Authorization": f"Token {api_key}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "images": reference_images,
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "movement_amplitude": movement_amplitude,
        "bgm": bgm,
    }
    if duration is not None:
        payload["duration"] = duration
    if seed is not None:
        payload["seed"] = seed

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(f"{_BASE_URL}/reference2video", json=payload, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise ViduError(f"Vidu 任务提交失败: {e}") from e
        task_id = resp.json().get("task_id")
        if not task_id:
            raise ViduError(f"Vidu 提交响应缺少 task_id: {resp.text}")

        elapsed = 0.0
        while elapsed < timeout_s:
            await asyncio.sleep(poll_interval_s)
            elapsed += poll_interval_s
            try:
                status_resp = await client.get(
                    f"{_BASE_URL}/tasks/{task_id}/creations",
                    headers=headers,
                )
                status_resp.raise_for_status()
            except httpx.HTTPError as e:
                raise ViduError(f"Vidu 任务查询失败 (task_id={task_id}): {e}") from e

            data = status_resp.json()
            state = data.get("state")
            if state == "success":
                creations = data.get("creations") or []
                if not creations or not creations[0].get("url"):
                    raise ViduError(f"Vidu 任务 {task_id} 状态 success 但无产物 URL: {data}")
                video_url = creations[0]["url"]
                video_resp = await client.get(video_url)
                video_resp.raise_for_status()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(video_resp.content)
                logger.info("Vidu: task %s 完成,已下载到 %s", task_id, output_path)
                return output_path
            if state == "failed":
                raise ViduError(f"Vidu 任务 {task_id} 失败: {data.get('err_code')}")
            logger.debug("Vidu: task %s 状态 %s,继续轮询", task_id, state)

    raise ViduError(f"Vidu 任务 {task_id} 在 {timeout_s}s 内未完成")
