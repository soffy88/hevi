"""阿里云百炼 qwen-image 文生图 + qwen-image-edit 参考图编辑 —— 纯云水墨图像,替代本地
SDXL+LoRA+IP-Adapter(本机 RTX3080 反复掉 PCIe 总线,本地路已弃用)。

两个能力:
- `qwen_image_generate`(文生图,异步):qwen-image 出水墨人物/场景。实测水墨质地、真汉字
  题字都很好,质量比肩本地 LoRA。
- `qwen_image_edit`(参考图编辑,同步):拿一张 canonical 水墨像,改表情/姿势/加场景而
  **保住相貌与画风** —— 云端版"锁脸一致性",替代本地 IP-Adapter。注意此模型**只支持同步
  调用**(带 X-DashScope-Async 头会 403 AccessDenied)。

都走 workspace 专属域名(ALIBABA_MAAS_HOST)+ ALIBABA_MAAS_API_KEY(公共 DASHSCOPE 账户欠费)。
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


class QwenImageError(Exception):
    """qwen-image 生成/编辑失败。"""


def _creds(api_key: str | None, host: str | None) -> tuple[str, str]:
    key = api_key or os.getenv("ALIBABA_MAAS_API_KEY")
    h = host or os.getenv("ALIBABA_MAAS_HOST")
    if not key:
        raise QwenImageError("ALIBABA_MAAS_API_KEY not configured")
    if not h:
        raise QwenImageError("ALIBABA_MAAS_HOST not configured (workspace-dedicated domain)")
    return key, h


def _data_uri(image_path: Path) -> str:
    suffix = image_path.suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    return f"data:image/{mime};base64,{base64.b64encode(image_path.read_bytes()).decode()}"


async def _submit_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    json: dict[str, Any],
    headers: dict[str, str],
    label: str,
) -> httpx.Response:
    """MaaS 端点提交带指数退避重试。整集逐镜高频出关键帧(每镜 1-2 张 qwen-image-edit/
    generate)会间歇 403 Forbidden / 429 限流,隔几十秒自恢复(实测直接重试即成功)。一次
    失败就抛出 → scene_render_avatar 整镜降级空镜 → 成片只剩零星几镜(用户实测"8 镜只出 1
    镜、成片 6 秒")。5 次指数退避(~78s)够清瞬时限流。

    但**额度/计费类 403 不是瞬时限流,退避永远治不好**(实测 qwen-image-edit 免费额度耗尽
    后每镜傻等 78s×N 才失败)——识别到 AllocationQuota/FreeTierOnly 立刻抛清晰错误,不重试。

    传输层歧义(超时/断连,无响应证明是否创建)不重试:直接抛显式错误,由调用方显式恢复,
    盲重试会重复计费。"""
    last_err: Exception | None = None
    for attempt in range(5):
        try:
            r = await client.post(url, json=json, headers=headers)
            r.raise_for_status()
            return r
        except httpx.HTTPError as e:
            if getattr(e, "response", None) is None:
                raise QwenImageError(
                    f"{label} 提交传输异常(是否创建未知,未重试防重复计费): {type(e).__name__} {e}"
                ) from e
            last_err = e
            resp = getattr(e, "response", None)
            code = getattr(resp, "status_code", None)
            body = str(getattr(resp, "text", "") or "")
            if "AllocationQuota" in body or "FreeTierOnly" in body:
                raise QwenImageError(
                    f"{label} 免费额度已用尽:需在阿里云百炼控制台关闭「仅使用免费额度」模式"
                    f"(或为该模型开通付费)。退避重试无用,已快速失败。原始响应: {body[:200]}"
                ) from e
            if attempt == 4:
                break
            wait = min(30, 4 * (2**attempt))
            logger.warning(
                "%s 提交第 %d 次失败(%s code=%s),%ds 后重试",
                label,
                attempt + 1,
                type(e).__name__,
                code,
                wait,
            )
            await asyncio.sleep(wait)
    raise QwenImageError(f"{label} 提交多次失败: {type(last_err).__name__} {last_err}")


async def qwen_image_generate(
    *,
    prompt: str,
    output_path: Path,
    size: str = "1280*720",
    seed: int | None = None,
    negative_prompt: str = "",
    api_key: str | None = None,
    host: str | None = None,
    poll_interval_s: float = 4.0,
    timeout_s: float = 180.0,
    durable: dict[str, Any] | None = None,
) -> Path:
    """qwen-image 文生图(异步任务)→ 落到 output_path。

    Durable plane (W16): 提交/轮询/下载走共享 driver。提交重试只覆盖明确拒绝
    (含额度快 fail);传输歧义直接抛显式错误,不盲重试。
    """
    key, h = _creds(api_key, host)
    submit_headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    poll_headers = {"Authorization": f"Bearer {key}"}
    params: dict[str, Any] = {"size": size, "n": 1}
    if seed is not None:
        params["seed"] = seed
    if negative_prompt:
        params["negative_prompt"] = negative_prompt
    payload = {"model": "qwen-image", "input": {"prompt": prompt}, "parameters": params}
    submit_url = f"https://{h}/api/v1/services/aigc/text2image/image-synthesis"

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=15.0)) as client:
        from hevi.tasks.durable_provider import (
            JobPoll,
            PollTransient,
            SubmitRejected,
            run_durable_provider_job,
        )

        def _error(message: str) -> QwenImageError:
            if message.startswith("DURABLE_POLL_TIMEOUT"):
                return QwenImageError(f"qwen-image 任务在 {timeout_s}s 内未完成")
            if message.startswith("DURABLE_DOWNLOAD_EMPTY"):
                return QwenImageError(f"qwen-image 产出空文件: {output_path}")
            return QwenImageError(f"qwen-image {message}")

        async def _submit() -> str:
            try:
                r = await client.post(submit_url, json=payload, headers=submit_headers)
            except httpx.HTTPError:
                raise  # ambiguous: surfaces for explicit resume, never retried blind
            body = r.text[:300]
            if "AllocationQuota" in body or "FreeTierOnly" in body:
                raise QwenImageError(
                    "qwen-image 免费额度已用尽:需在阿里云百炼控制台关闭「仅使用免费额度」模式"
                    f"(或为该模型开通付费)。退避重试无用,已快速失败。原始响应: {body[:200]}"
                )
            if r.status_code >= 400:
                raise SubmitRejected(r.status_code, body)
            task_id = (r.json().get("output") or {}).get("task_id")
            if not task_id:
                raise SubmitRejected(None, f"qwen-image 提交无 task_id: {body}")
            return str(task_id)

        async def _poll(task_id: str) -> JobPoll:
            try:
                s = await client.get(f"https://{h}/api/v1/tasks/{task_id}", headers=poll_headers)
                s.raise_for_status()
            except httpx.HTTPError as e:
                raise PollTransient(f"qwen-image 轮询异常,重试: {e}") from e
            out = s.json().get("output") or {}
            status = out.get("task_status")
            if status == "SUCCEEDED":
                results = out.get("results") or []
                url = results[0].get("url") if results else None
                if not url:
                    return JobPoll(state="failed", error=f"qwen-image 成功但无图: {out}")
                return JobPoll(state="succeeded", artifact_url=str(url), terminal=status)
            if status in ("FAILED", "UNKNOWN", "CANCELED"):
                return JobPoll(state="failed", error=f"qwen-image 任务失败({status}): {out}")
            return JobPoll(state="running", terminal=status)

        state_config = durable if durable is not None else {}
        state_config, path, _record = await run_durable_provider_job(
            config=state_config,
            provider="dashscope-qwen-image",
            endpoint="image-synthesis",
            model="qwen-image",
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
            min_bytes=1024,
            download_client=client,
            error_factory=_error,
            live_state=state_config,
        )
        if durable is not None:
            durable.clear()
            durable.update(state_config)
        logger.info("qwen-image: task %s → %s", _record.get("provider_job_id"), path.name)
        return path


async def qwen_image_edit(
    *,
    image_path: Path | list[Path],
    instruction: str,
    output_path: Path,
    api_key: str | None = None,
    host: str | None = None,
) -> Path:
    """qwen-image-edit 参考图编辑(**同步调用**,不能带 async 头)→ 落到 output_path。
    instruction 描述要改什么(表情/姿势/场景),并强调保持相貌与水墨画风不变。

    `image_path` 可传单张(原有用法)或最多 3 张(多图融合,官方文档"模型支持输入
    1-3张图像",仅支持一段 text)——多人同框镜头把每个在场角色各自的 canonical
    像都传进去,一次编辑把所有人的真实长相合成进同一张关键帧,而不是只能锁一张脸。
    见 hevi/tongjian/scene_render_avatar.py 的多角色镜头调用点。
    """
    key, h = _creds(api_key, host)
    images = image_path if isinstance(image_path, list) else [image_path]
    if not 1 <= len(images) <= 3:
        raise QwenImageError(f"qwen-image-edit 只支持 1-3 张输入图,收到 {len(images)} 张")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": "qwen-image-edit",
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [{"image": _data_uri(p)} for p in images] + [{"text": instruction}],
                }
            ]
        },
        "parameters": {"watermark": False},
    }
    url = f"https://{h}/api/v1/services/aigc/multimodal-generation/generation"
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
        r = await _submit_with_retry(
            client, url, json=payload, headers=headers, label="qwen-image-edit"
        )
        out = r.json().get("output") or {}
        img_url = None
        for choice in out.get("choices") or []:
            for part in choice.get("message", {}).get("content", []):
                if isinstance(part, dict) and part.get("image"):
                    img_url = part["image"]
        if not img_url:
            raise QwenImageError(f"qwen-image-edit 无图产物: {str(out)[:300]}")
        return await _download(client, img_url, output_path)


async def _download(client: httpx.AsyncClient, url: str, output_path: Path) -> Path:
    for attempt in range(3):
        try:
            v = await client.get(url, timeout=httpx.Timeout(90.0, connect=15.0))
            v.raise_for_status()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(v.content)
            if output_path.stat().st_size >= 1024:
                return output_path
        except httpx.HTTPError as e:
            logger.warning("qwen-image 下载第 %d 次失败,重试: %s", attempt + 1, e)
    raise QwenImageError(f"qwen-image 图片下载多次失败: {url}")
