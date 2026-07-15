"""阿里云百炼(Model Studio / MaaS)图生视频 i2v —— 把一张水墨关键帧动起来。

跟 `alibaba_maas_service.py`(t2v / 参考图生视频)同一套 MaaS host + video-synthesis
端点、同一把 `ALIBABA_MAAS_API_KEY`/`ALIBABA_MAAS_HOST`(workspace 专属域名,独立于公共
`dashscope.aliyuncs.com`——后者对应的 DASHSCOPE_API_KEY 账户当前欠费)。区别只在 input:
i2v 传 `img_url`(首帧图),模型走 `wan2.2-i2v-flash`。

**为什么用 i2v 而不是 t2v/r2v**:HEVI 的水墨画风由本地 SDXL+水墨 LoRA 出的关键帧承载,
i2v 从这张帧出发只加运动(转头/开口/衣袂),画风忠实保留;t2v/参考图生视频(happyhorse)
是凭文本重新生成,会把国风水墨画成卡通描线(scene_v2 的教训)。2026-07-10 实测
wan2.2-i2v-flash 对水墨帧保风格良好。
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DashScopeI2VError(Exception):
    """i2v 生成失败(缺 key/host、提交或轮询失败、任务失败、超时、产物为空)。"""


_DEFAULT_MODEL = "wan2.2-i2v-flash"


def _img_to_data_uri(image_path: Path) -> str:
    suffix = image_path.suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    return f"data:image/{mime};base64,{b64}"


async def happyhorse_animate(
    *,
    image_path: Path,
    prompt: str,
    output_path: Path,
    resolution: str = "720P",
    duration: int | None = None,
    config: dict[str, Any] | None = None,
    poll_interval_s: float = 6.0,
    timeout_s: float = 480.0,
) -> Path:
    """happyhorse-1.1-r2v 参考图生视频 —— 说话镜头专用。相比 wan2.2-i2v 的通用动效,
    happyhorse 的**口型/表情/动作跟随更到位**(scene_v2 那种"会说话"的观感就来自它)。喂
    水墨关键帧当参考图能大体保住水墨画风(近景略偏描线,可接受),watermark=false 去水印。

    与 `i2v_animate` 共用 submit/poll/download,只是 input 用 media(参考图)、模型换成
    happyhorse-1.1-r2v。"""
    return await _submit_video(
        image_path=image_path,
        prompt=prompt,
        output_path=output_path,
        model="happyhorse-1.1-r2v",
        input_builder=lambda uri: {
            "prompt": prompt,
            "media": [{"type": "reference_image", "url": uri}],
        },
        parameters=(
            {"resolution": resolution, "watermark": False, "duration": duration}
            if duration
            else {"resolution": resolution, "watermark": False}
        ),
        config=config,
        poll_interval_s=poll_interval_s,
        timeout_s=timeout_s,
    )


async def i2v_animate(
    *,
    image_path: Path,
    prompt: str,
    output_path: Path,
    model: str = _DEFAULT_MODEL,
    resolution: str = "720P",
    config: dict[str, Any] | None = None,
    poll_interval_s: float = 6.0,
    timeout_s: float = 480.0,
) -> Path:
    """首帧图 + 运动 prompt → 视频(wan2.2-i2v-flash)。画风由首帧定,通用动效;说话镜头用
    `happyhorse_animate`(口型/表情跟随更好)。"""
    return await _submit_video(
        image_path=image_path,
        prompt=prompt,
        output_path=output_path,
        model=model,
        input_builder=lambda uri: {"prompt": prompt, "img_url": uri},
        parameters={"resolution": resolution, "prompt_extend": True},
        config=config,
        poll_interval_s=poll_interval_s,
        timeout_s=timeout_s,
    )


async def _submit_video(
    *,
    image_path: Path,
    prompt: str,
    output_path: Path,
    model: str,
    input_builder,
    parameters: dict[str, Any],
    config: dict[str, Any] | None = None,
    poll_interval_s: float = 6.0,
    timeout_s: float = 480.0,
) -> Path:
    """阿里云百炼 video-synthesis 异步任务的共享壳:提交→轮询→下载(带重试与有界超时)。
    i2v(img_url)和 happyhorse r2v(media 参考图)只是 input/model/parameters 不同。"""
    cfg = config or {}
    api_key = cfg.get("ALIBABA_MAAS_API_KEY") or os.getenv("ALIBABA_MAAS_API_KEY")
    host = cfg.get("ALIBABA_MAAS_HOST") or os.getenv("ALIBABA_MAAS_HOST")
    if not api_key:
        raise DashScopeI2VError("ALIBABA_MAAS_API_KEY not configured")
    if not host:
        raise DashScopeI2VError("ALIBABA_MAAS_HOST not configured (workspace-dedicated domain)")

    submit_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    poll_headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": model,
        "input": input_builder(_img_to_data_uri(image_path)),
        "parameters": parameters,
    }
    submit_url = f"https://{host}/api/v1/services/aigc/video-generation/video-synthesis"

    # 显式 connect/read 超时:轮询 GET 曾卡死 9 分钟不报错,必须给死;提交要上传 ~1.5MB base64
    # 图 + 排队,MaaS 负载高时 60s 不够(实测 ReadTimeout),提交单独用更长超时 + 重试。
    poll_timeout = httpx.Timeout(60.0, connect=15.0)
    submit_timeout = httpx.Timeout(180.0, connect=20.0)
    async with httpx.AsyncClient(timeout=poll_timeout) as client:
        resp = None
        ok = False
        last_err: Exception | None = None
        # MaaS 端点突发多请求(整集逐镜生成 + verdict 返工)会间歇 403 Forbidden / 429
        # 限流一阵子,隔几十秒自己恢复(实测直接重试即成功)。一次失败就丢镜头降级空镜 →
        # 成片只剩零星几镜(用户实测"11秒只有开头")。改 5 次指数退避(~78s),够清瞬时限流。
        # 之前的 bug:3 次全败后 resp 是最后那个 403 响应(非 None),漏进下面报"缺 task_id"。
        for attempt in range(5):
            try:
                r = await client.post(
                    submit_url, json=payload, headers=submit_headers, timeout=submit_timeout
                )
                r.raise_for_status()
                resp = r
                ok = True
                break
            except httpx.HTTPError as e:
                last_err = e
                code = getattr(getattr(e, "response", None), "status_code", None)
                wait = min(30, 4 * (2**attempt))
                logger.warning(
                    "%s 提交第 %d 次失败(%s code=%s),%ds 后重试",
                    model,
                    attempt + 1,
                    type(e).__name__,
                    code,
                    wait,
                )
                await asyncio.sleep(wait)
        if not ok or resp is None:
            raise DashScopeI2VError(
                f"{model} i2v 提交多次失败: {type(last_err).__name__} {last_err}"
            )
        task_id = (resp.json().get("output") or {}).get("task_id")
        if not task_id:
            raise DashScopeI2VError(f"{model} 提交响应缺少 task_id: {resp.text[:300]}")

        elapsed = 0.0
        while elapsed < timeout_s:
            await asyncio.sleep(poll_interval_s)
            elapsed += poll_interval_s
            try:
                s = await client.get(f"https://{host}/api/v1/tasks/{task_id}", headers=poll_headers)
                s.raise_for_status()
            except httpx.HTTPError as e:
                logger.warning("%s 任务查询异常(id=%s),继续重试: %s", model, task_id, e)
                continue
            output = s.json().get("output") or {}
            status = output.get("task_status")
            if status == "SUCCEEDED":
                video_url = output.get("video_url")
                if not video_url:
                    raise DashScopeI2VError(f"{model} 任务 {task_id} 成功但无 video_url: {output}")
                # 下载带重试 + 有界 read 超时(OSS 偶发慢/卡)。
                data = b""
                for attempt in range(3):
                    try:
                        v = await client.get(video_url, timeout=httpx.Timeout(90.0, connect=15.0))
                        v.raise_for_status()
                        data = v.content
                        break
                    except httpx.HTTPError as e:
                        logger.warning("%s 视频下载第 %d 次失败,重试: %s", model, attempt + 1, e)
                if not data:
                    raise DashScopeI2VError(f"{model} 任务 {task_id} 视频下载多次失败: {video_url}")
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(data)
                if not output_path.exists() or output_path.stat().st_size < 1024:
                    raise DashScopeI2VError(f"{model} 产出空/过小文件: {output_path}")
                logger.info(
                    "%s i2v: task %s → %s (%d bytes)",
                    model,
                    task_id,
                    output_path.name,
                    output_path.stat().st_size,
                )
                return output_path
            if status in ("FAILED", "UNKNOWN", "CANCELED"):
                raise DashScopeI2VError(f"{model} 任务 {task_id} 失败(status={status}): {output}")
        raise DashScopeI2VError(f"{model} 任务 {task_id} 在 {timeout_s}s 内未完成")
