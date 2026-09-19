"""Runway API —— 一次性备用视频/图像生成通道(仅用于 2026-07-07 手动构建智伯身份包
参考像+转身视频这一段,HEVI-EXEC-01 主视频通道仍是 hevi/video/vidu_service.py 的 Vidu)。

官方文档(docs.dev.runwayml.com,2026-07 抓取):
  - 生图: POST https://api.dev.runwayml.com/v1/text_to_image   (model=gen4_image)
  - 图生视频: POST https://api.dev.runwayml.com/v1/image_to_video (model=gen4.5)
  - 查询: GET  https://api.dev.runwayml.com/v1/tasks/{task_id}
两者都用 `Authorization: Bearer {api_key}` + `X-Runway-Version: 2024-11-06` 鉴权。
任务是提交(拿 task id)→ 轮询 status(PENDING/RUNNING/SUCCEEDED/FAILED)→ SUCCEEDED 时
output[0] 是签名 URL,24-48 小时内过期,必须立刻下载落盘,不能只存 URL(同 vidu_service.py
的既有惯例)。

RUNWAY_API_KEY 读取方式同 vidu_service.py:优先 config dict 覆盖,缺省回退环境变量。
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.dev.runwayml.com/v1"
_API_VERSION = "2024-11-06"
_TERMINAL_STATES = {"SUCCEEDED", "FAILED"}


class RunwayError(Exception):
    """Runway 生成失败(缺 key、提交/轮询失败、超时,或产物为空)。"""


def _resolve_api_key(config: dict[str, Any] | None) -> str:
    cfg = config or {}
    api_key = cfg.get("RUNWAY_API_KEY") or os.getenv("RUNWAY_API_KEY")
    if not api_key:
        raise RunwayError("RUNWAY_API_KEY not configured")
    return api_key


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "X-Runway-Version": _API_VERSION,
        "Content-Type": "application/json",
    }


def _as_uri(image: str) -> str:
    """本地文件路径 → base64 data URI;已经是 http(s)/data URI 的原样透传。"""
    if image.startswith(("http://", "https://", "data:")):
        return image
    path = Path(image)
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


async def _submit_and_poll(
    *,
    endpoint: str,
    payload: dict[str, Any],
    api_key: str,
    output_path: Path,
    poll_interval_s: float,
    timeout_s: float,
    durable: dict[str, Any] | None = None,
) -> Path:
    """Durable plane (W16): submit/poll/download run through the shared driver.

    Also fixes a latent NameError: the old submit handler referenced
    ``resp.text`` when the POST itself raised (``resp`` unbound).
    """
    from hevi.tasks.durable_provider import (
        JobPoll,
        PollTransient,
        SubmitRejected,
        run_durable_provider_job,
    )

    def _error(message: str) -> RunwayError:
        if message.startswith("DURABLE_POLL_TIMEOUT"):
            return RunwayError(f"Runway 任务在 {timeout_s}s 内未完成")
        return RunwayError(f"Runway {message}")

    async with httpx.AsyncClient(timeout=30.0) as client:

        async def _submit() -> str:
            try:
                resp = await client.post(
                    f"{_BASE_URL}/{endpoint}", json=payload, headers=_headers(api_key)
                )
            except httpx.HTTPError:
                raise  # ambiguous: surfaces for explicit resume, never retried blind
            if resp.status_code >= 400:
                raise SubmitRejected(resp.status_code, resp.text[:300])
            task_id = resp.json().get("id")
            if not task_id:
                raise SubmitRejected(None, f"Runway 提交响应缺少 id: {resp.text}")
            return str(task_id)

        async def _poll(task_id: str) -> JobPoll:
            try:
                status_resp = await client.get(
                    f"{_BASE_URL}/tasks/{task_id}", headers=_headers(api_key)
                )
                status_resp.raise_for_status()
            except httpx.HTTPError as e:
                raise PollTransient(f"Runway 任务查询失败 (task_id={task_id}): {e}") from e
            data = status_resp.json()
            status = data.get("status")
            if status == "SUCCEEDED":
                output = data.get("output") or []
                if not output:
                    return JobPoll(
                        state="failed",
                        error=f"Runway 任务 {task_id} 状态 SUCCEEDED 但无产物: {data}",
                    )
                return JobPoll(state="succeeded", artifact_url=str(output[0]), terminal=status)
            if status == "FAILED":
                return JobPoll(
                    state="failed",
                    error=f"Runway 任务 {task_id} 失败: {data.get('failure') or data}",
                )
            logger.debug("Runway: task %s 状态 %s,继续轮询", task_id, status)
            return JobPoll(state="running", terminal=status)

        config = durable if durable is not None else {}
        config, path, _record = await run_durable_provider_job(
            config=config,
            provider="runway",
            endpoint=endpoint,
            model=endpoint,
            request=payload,
            production_revision=str((durable or {}).get("revision_id") or ""),
            target_artifact_id=str(output_path),
            idempotency_key=None,
            output_path=Path(output_path),
            submit=_submit,
            poll=_poll,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
            initial_poll_delay_s=max(poll_interval_s, 2.0),
            submit_max_attempts=1,
            min_bytes=1,
            download_client=client,
            error_factory=_error,
            live_state=config,
            project_ref=str((durable or {}).get("project_id") or output_path),
            operation_type="video_generate",
        )
        if durable is not None:
            durable.clear()
            durable.update(config)
        logger.info("Runway: task %s → %s", _record.get("provider_job_id"), path.name)
        return path


async def runway_text_to_image(
    *,
    prompt: str,
    output_path: Path | str,
    config: dict[str, Any] | None = None,
    model: str = "gen4_image",
    ratio: str = "1920:1080",
    reference_images: list[str] | None = None,
    seed: int | None = None,
    poll_interval_s: float = 5.0,
    timeout_s: float = 300.0,
    durable: dict[str, Any] | None = None,
) -> Path:
    """文本(+可选 1-3 张参考图)→ 生成图片,下载到 output_path。"""
    api_key = _resolve_api_key(config)
    payload: dict[str, Any] = {"model": model, "promptText": prompt, "ratio": ratio}
    if reference_images:
        if not 1 <= len(reference_images) <= 3:
            raise RunwayError(f"reference_images must have 1-3 items, got {len(reference_images)}")
        payload["referenceImages"] = [{"uri": _as_uri(img)} for img in reference_images]
    if seed is not None:
        payload["seed"] = seed

    return await _submit_and_poll(
        endpoint="text_to_image",
        payload=payload,
        api_key=api_key,
        output_path=Path(output_path),
        poll_interval_s=poll_interval_s,
        timeout_s=timeout_s,
        durable=durable,
    )


async def runway_image_to_video(
    *,
    prompt: str,
    reference_images: list[str],
    output_path: Path | str,
    config: dict[str, Any] | None = None,
    model: str = "gen4.5",
    ratio: str = "1280:720",
    duration: int | None = 5,
    seed: int | None = None,
    poll_interval_s: float = 5.0,
    timeout_s: float = 600.0,
    durable: dict[str, Any] | None = None,
) -> Path:
    """参考图(1 张 URL/本地路径/base64)+ 文本 prompt → 生成视频,下载到 output_path。"""
    api_key = _resolve_api_key(config)
    if not reference_images:
        raise RunwayError("reference_images must have at least 1 item")

    payload: dict[str, Any] = {
        "model": model,
        "promptImage": _as_uri(reference_images[0]),
        "promptText": prompt,
        "ratio": ratio,
    }
    if duration is not None:
        payload["duration"] = duration
    if seed is not None:
        payload["seed"] = seed

    return await _submit_and_poll(
        endpoint="image_to_video",
        payload=payload,
        api_key=api_key,
        output_path=Path(output_path),
        poll_interval_s=poll_interval_s,
        timeout_s=timeout_s,
        durable=durable,
    )
