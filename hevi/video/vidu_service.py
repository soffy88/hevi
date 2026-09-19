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
    durable: dict[str, Any] | None = None,
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
        from hevi.tasks.durable_provider import (
            JobPoll,
            PollTransient,
            SubmitRejected,
            run_durable_provider_job,
        )

        def _error(message: str) -> ViduError:
            if message.startswith("DURABLE_POLL_TIMEOUT"):
                return ViduError(f"Vidu 任务在 {timeout_s}s 内未完成")
            return ViduError(f"Vidu {message}")

        async def _submit() -> str:
            try:
                resp = await client.post(
                    f"{_BASE_URL}/reference2video", json=payload, headers=headers
                )
            except httpx.HTTPError:
                raise  # ambiguous: surfaces for explicit resume, never retried blind
            if resp.status_code >= 400:
                raise SubmitRejected(resp.status_code, resp.text[:300])
            task_id = resp.json().get("task_id")
            if not task_id:
                raise SubmitRejected(None, f"Vidu 提交响应缺少 task_id: {resp.text}")
            return str(task_id)

        async def _poll(task_id: str) -> JobPoll:
            try:
                status_resp = await client.get(
                    f"{_BASE_URL}/tasks/{task_id}/creations",
                    headers=headers,
                )
                status_resp.raise_for_status()
            except httpx.HTTPError as e:
                raise PollTransient(f"Vidu 任务查询失败 (task_id={task_id}): {e}") from e
            data = status_resp.json()
            state = data.get("state")
            if state == "success":
                creations = data.get("creations") or []
                if not creations or not creations[0].get("url"):
                    return JobPoll(
                        state="failed",
                        error=f"Vidu 任务 {task_id} 状态 success 但无产物 URL: {data}",
                    )
                return JobPoll(
                    state="succeeded", artifact_url=str(creations[0]["url"]), terminal=state
                )
            if state == "failed":
                return JobPoll(
                    state="failed", error=f"Vidu 任务 {task_id} 失败: {data.get('err_code')}"
                )
            logger.debug("Vidu: task %s 状态 %s,继续轮询", task_id, state)
            return JobPoll(state="running", terminal=state)

        state_config = durable if durable is not None else {}
        state_config, path, _record = await run_durable_provider_job(
            config=state_config,
            provider="vidu",
            endpoint="reference2video",
            model=model,
            request=payload,
            production_revision=str((durable or {}).get("revision_id") or ""),
            target_artifact_id=str(output_path),
            idempotency_key=None,
            output_path=Path(output_path),
            submit=_submit,
            poll=_poll,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
            submit_max_attempts=1,
            min_bytes=1,
            download_client=client,
            error_factory=_error,
            live_state=state_config,
            project_ref=str((durable or {}).get("project_id") or output_path),
            operation_type="video_generate",
        )
        if durable is not None:
            durable.clear()
            durable.update(state_config)
        logger.info("Vidu: task %s → %s", _record.get("provider_job_id"), path.name)
        return path
