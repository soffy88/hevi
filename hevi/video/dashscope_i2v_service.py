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
    durable: dict[str, Any] | None = None,
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
        durable=durable,
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
    durable: dict[str, Any] | None = None,
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
        durable=durable,
    )


async def _submit_video(
    *,
    image_path: Path,
    prompt: str,
    output_path: Path,
    model: str,
    input_builder: Any,
    parameters: dict[str, Any],
    config: dict[str, Any] | None = None,
    poll_interval_s: float = 6.0,
    timeout_s: float = 480.0,
    durable: dict[str, Any] | None = None,
) -> Path:
    """阿里云百炼 video-synthesis 异步任务的共享壳:提交→轮询→下载(带重试与有界超时)。
    i2v(img_url)和 happyhorse r2v(media 参考图)只是 input/model/parameters 不同。

    Durable plane (W16): submit retries cover HTTP error-status rejections
    only (transient 403/429 rate limits — the documented production case);
    transport ambiguity surfaces for explicit resume instead of blind retry.
    """
    from hevi.tasks.durable_provider import (
        JobPoll,
        PollTransient,
        SubmitRejected,
        run_durable_provider_job,
    )

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

    def _error(message: str) -> DashScopeI2VError:
        if message.startswith("DURABLE_POLL_TIMEOUT"):
            return DashScopeI2VError(f"{model} 任务在 {timeout_s}s 内未完成")
        if message.startswith("DURABLE_DOWNLOAD_EMPTY"):
            return DashScopeI2VError(f"{model} 产出空/过小文件: {output_path}")
        return DashScopeI2VError(f"{model} {message}")

    # 显式 connect/read 超时:轮询 GET 曾卡死 9 分钟不报错,必须给死;提交要上传 ~1.5MB base64
    # 图 + 排队,MaaS 负载高时 60s 不够(实测 ReadTimeout),提交单独用更长超时。
    poll_timeout = httpx.Timeout(60.0, connect=15.0)
    submit_timeout = httpx.Timeout(180.0, connect=20.0)
    async with httpx.AsyncClient(timeout=poll_timeout) as client:

        async def _submit() -> str:
            # MaaS 端点突发多请求会间歇 403 Forbidden / 429 限流一阵子(实测直接重试
            # 即成功)。只重试"服务器明确拒绝"(无任务创建);传输层歧义直接抛给显式恢复。
            try:
                r = await client.post(
                    submit_url, json=payload, headers=submit_headers, timeout=submit_timeout
                )
            except httpx.HTTPError:
                raise
            if r.status_code >= 400:
                raise SubmitRejected(r.status_code, r.text[:300])
            task_id = (r.json().get("output") or {}).get("task_id")
            if not task_id:
                raise SubmitRejected(None, f"{model} 提交响应缺少 task_id: {r.text[:300]}")
            return str(task_id)

        async def _poll(task_id: str) -> JobPoll:
            try:
                s = await client.get(f"https://{host}/api/v1/tasks/{task_id}", headers=poll_headers)
                s.raise_for_status()
            except httpx.HTTPError as e:
                raise PollTransient(f"{model} 任务查询异常(id={task_id}),继续重试: {e}") from e
            output = s.json().get("output") or {}
            status = output.get("task_status")
            if status == "SUCCEEDED":
                video_url = output.get("video_url")
                if not video_url:
                    return JobPoll(
                        state="failed",
                        error=f"{model} 任务 {task_id} 成功但无 video_url: {output}",
                    )
                return JobPoll(state="succeeded", artifact_url=str(video_url), terminal=status)
            if status in ("FAILED", "UNKNOWN", "CANCELED"):
                return JobPoll(
                    state="failed",
                    error=f"{model} 任务 {task_id} 失败(status={status}): {output}",
                )
            return JobPoll(state="running", terminal=status)

        state_config = durable if durable is not None else {}
        state_config, path, _record = await run_durable_provider_job(
            config=state_config,
            provider="dashscope-i2v",
            endpoint="video-synthesis",
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
            submit_max_attempts=5,
            submit_backoff_s=(4.0, 8.0, 16.0, 30.0, 30.0),
            download_client=client,
            error_factory=_error,
            live_state=state_config,
            project_ref=str((durable or {}).get("project_id") or output_path),
            operation_type="video_generate",
        )
        if durable is not None:
            durable.clear()
            durable.update(state_config)
        logger.info("%s i2v: task %s → %s", model, _record.get("provider_job_id"), path.name)
        return path
