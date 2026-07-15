"""fal.ai Flux 文生图 —— 本地 SDXL 不可用时的云端 image_gen 兜底(见
hevi/image/resilient_image_gen.py)。复用已验证过的 FAL_API_KEY(现有 LTX-2 视频
生成在用同一把 key)。

跟 oprim.fal_queue_generate 同一套提交/轮询/deadline 协议(fal 队列制模型的通用
形状),但那个工具假定产物字段是 "video"(见其源码 _fal_queue_generate.py),
Flux 图像端点返回的是 "images"[0]["url"],形状对不上,所以这里单独写一份而不是
改 oprim(那是第三方包)。
"""

from __future__ import annotations

import asyncio
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

    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_s

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        sub = await client.post(f"{_FAL_BASE}/{endpoint}", json=payload, headers=headers)
        if sub.status_code not in (200, 201, 202):
            raise FalImageError(f"fal submit {sub.status_code}: {sub.text[:300]}")
        data = sub.json()
        status_url = data.get("status_url")
        response_url = data.get("response_url")

        while status_url:
            if loop.time() > deadline:
                raise FalImageError(f"fal image job timeout after {timeout_s:.0f}s ({endpoint})")
            st = (await client.get(status_url, headers=headers)).json()
            status = st.get("status", "")
            if status == "COMPLETED":
                data = (await client.get(response_url, headers=headers)).json()
                break
            if status in ("FAILED", "CANCELLED", "ERROR"):
                raise FalImageError(f"fal image job {status} ({endpoint}): {str(st)[:300]}")
            await asyncio.sleep(_POLL_INTERVAL_S)

        images = data.get("images") or []
        image_url = images[0].get("url") if images else None
        if not image_url:
            raise FalImageError(f"fal: no image url in response ({endpoint}): {str(data)[:300]}")
        dl = await client.get(image_url, timeout=httpx.Timeout(60.0))
        if dl.status_code != 200:
            raise FalImageError(f"fal image download {dl.status_code}")
        output_path.write_bytes(dl.content)

    if not output_path.exists() or output_path.stat().st_size < 512:
        raise FalImageError(f"fal produced no/empty image ({endpoint})")
    logger.info("fal %s → %s (%d bytes)", endpoint, output_path.name, output_path.stat().st_size)
    return {"output_path": str(output_path), "seed": seed}
