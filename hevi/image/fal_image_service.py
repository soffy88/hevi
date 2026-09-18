"""fal.ai Flux 文生图 —— 本地 SDXL 不可用时的云端 image_gen 兜底(见
hevi/image/resilient_image_gen.py)。复用已验证过的 FAL_API_KEY(现有 LTX-2 视频
生成在用同一把 key)。

跟 oprim.fal_queue_generate 同一套提交/轮询/deadline 协议(fal 队列制模型的通用
形状),但那个工具假定产物字段是 "video"(见其源码 _fal_queue_generate.py),
Flux 图像端点返回的是 "images"[0]["url"],形状对不上,所以这里单独写一份而不是
改 oprim(那是第三方包)。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_FAL_BASE = "https://queue.fal.run"
_POLL_INTERVAL_S = 5.0
_DEFAULT_TIMEOUT_S = 180.0
_DEFAULT_ENDPOINT = "fal-ai/flux/schnell"


class FalImageError(Exception):
    """fal.ai Flux 文生图失败(缺 key / 提交轮询失败 / 超时 / 空产物)。"""


def _resolve_api_key(config: dict[str, Any] | None) -> str:
    cfg = config or {}
    api_key = cfg.get("FAL_API_KEY") or os.getenv("FAL_API_KEY")
    if not api_key:
        raise FalImageError("FAL_API_KEY not configured")
    return api_key


async def fal_image_generate(
    *,
    prompt: str,
    negative_prompt: str = "",
    width: int = 1024,
    height: int = 1024,
    output_path: Path | str,
    seed: int | None = None,
    extra: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    endpoint: str = _DEFAULT_ENDPOINT,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    durable: dict[str, Any] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Matches sdxl_local_generate 的 ImageGenCaller 形状:{"output_path": str, "seed": int|None}。

    negative_prompt:flux 端点没有独立 negative_prompt 参数,拼进正向 prompt 里当
    "避免..."描述。seed 有就透传(fal 支持),没有就让 fal 自己随机。
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    api_key = _resolve_api_key(config)
    headers = {"Authorization": f"Key {api_key}", "Content-Type": "application/json"}

    full_prompt = prompt if not negative_prompt else f"{prompt}. Avoid: {negative_prompt}."
    payload: dict[str, Any] = {
        "prompt": full_prompt,
        "image_size": {"width": width, "height": height},
        "num_images": 1,
    }
    if seed is not None:
        payload["seed"] = seed

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        from hevi.tasks.durable_provider import (
            JobPoll,
            PollTransient,
            SubmitRejected,
            run_durable_provider_job,
        )

        submit_ctx: dict[str, Any] = {}

        def _error(message: str) -> FalImageError:
            if message.startswith("DURABLE_POLL_TIMEOUT"):
                return FalImageError(f"fal image job timeout after {timeout_s:.0f}s ({endpoint})")
            if message.startswith("DURABLE_DOWNLOAD_EMPTY"):
                return FalImageError(f"fal produced no/empty image ({endpoint})")
            return FalImageError(f"fal {message}")

        async def _submit() -> str:
            try:
                sub = await client.post(f"{_FAL_BASE}/{endpoint}", json=payload, headers=headers)
            except httpx.HTTPError:
                raise  # ambiguous: surfaces for explicit resume, never retried blind
            if sub.status_code not in (200, 201, 202):
                raise SubmitRejected(sub.status_code, sub.text[:300])
            data = sub.json()
            status_url = data.get("status_url")
            if not status_url:
                raise SubmitRejected(None, f"fal submit missing status_url: {sub.text[:300]}")
            submit_ctx["response_url"] = data.get("response_url")
            return str(status_url)

        async def _poll(status_url: str) -> JobPoll:
            try:
                st = (await client.get(status_url, headers=headers)).json()
            except httpx.HTTPError as e:
                raise PollTransient(f"fal poll failed: {e}") from e
            status = st.get("status", "")
            if status == "COMPLETED":
                try:
                    data = (
                        await client.get(
                            submit_ctx.get("response_url") or st.get("response_url") or "",
                            headers=headers,
                        )
                    ).json()
                except httpx.HTTPError as e:
                    raise PollTransient(f"fal response fetch failed: {e}") from e
                images = data.get("images") or []
                image_url = images[0].get("url") if images else None
                if not image_url:
                    return JobPoll(
                        state="failed",
                        error=f"fal: no image url in response ({endpoint}): {str(data)[:300]}",
                    )
                return JobPoll(state="succeeded", artifact_url=str(image_url), terminal=status)
            if status in ("FAILED", "CANCELLED", "ERROR"):
                return JobPoll(
                    state="failed", error=f"fal image job {status} ({endpoint}): {str(st)[:300]}"
                )
            return JobPoll(state="running", terminal=status)

        extra_cfg = extra or {}
        state_config = durable if durable is not None else {}
        state_config, path, _record = await run_durable_provider_job(
            config=state_config,
            provider="fal",
            endpoint=endpoint,
            model=endpoint,
            request=payload,
            production_revision=str(extra_cfg.get("revision_id") or ""),
            target_artifact_id=str(output_path),
            idempotency_key=None,
            output_path=Path(output_path),
            submit=_submit,
            poll=_poll,
            poll_interval_s=_POLL_INTERVAL_S,
            timeout_s=timeout_s,
            submit_max_attempts=1,
            min_bytes=512,
            download_client=client,
            error_factory=_error,
            live_state=state_config,
        )
        if durable is not None:
            durable.clear()
            durable.update(state_config)
        logger.info("fal %s → %s", endpoint, path.name)
        return {"output_path": str(path), "seed": seed}
