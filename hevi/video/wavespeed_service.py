"""WaveSpeed AI(阿里模型聚合网关)—— HappyHorse 1.1 / Wan 2.7 文生视频接入。

两个 t2v 模型(happyhorse_1_1 / wan_2_7)共享同一套 WaveSpeed REST v3 契约(提交 →
轮询 predictions/{id}/result → 取 outputs[0] → 下载),差异只在 endpoint slug 和各自
请求体里能不能传的字段。密钥走环境变量(WAVESPEED_API_KEY),同 vidu_service.py 的
既定惯例——密钥从不进 hevi.core.config.Settings。

native_audio/lip_sync:WaveSpeed 官方 REST API 文档(非营销页)未列出这两个模型的
音频/口型相关请求字段,营销页对 HappyHorse 1.1 的"原生音画+多语种对口型"宣称没有
对应的 API 契约依据——因此 capability_guard.py 里这两个 provider 暂不标 native_audio/
lip_sync=True,等真的核实到具体字段再改(同一份"只在有真实依据时标 True"的纪律)。

参考图锁定生成(happyhorse_1_1_reference_to_video):跟上面两个纯 t2v 端点是完全
不同的能力层级——喂 1~9 张参考图,身份跟着图走,不是靠文本描述长相。**这个能力
Wan 2.7 在 WaveSpeed 上没有对应物**:它的"参考"变体强制要求至少一段参考视频
(`videos` 必填),不满足"只有照片、没有视频"这个身份锁定场景;其余变体都是单图
首帧续接(image-to-video),不是身份锚定。核实过程见调研记录,只有 HappyHorse 的
`reference-to-video` 端点是跟 `hevi.video.vidu_service.vidu_reference_to_video`
同一能力层级、可以互相替换的。

WaveSpeed 的 `images` 字段文档原话是"Reference image URLs"——只吃 URL,不吃内联
base64(没有反证,但文档也从没提过 base64 这条路,反而专门给了一个上传端点
`POST /media/upload/binary` 把本地文件换成 `download_url`,这是文档给出的唯一路径)。
而 hevi 这边参考图的既有传递方式(`hevi.cinematic.platform_binding.ensure_platform_binding`)
是给 Vidu 设计的,返回的是内联 base64 data URI——所以 `happyhorse_1_1_reference_to_video`
自己内部多做一步:收到 data URI 就先解码字节、POST 给 WaveSpeed 的上传端点换成
`download_url`,再拿这些 URL 去发生成请求;收到本来就是 http(s) URL 的则直接透传。

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from hevi.video.wavespeed_service import wan_2_7_generate
    >>> out = asyncio.run(wan_2_7_generate(
    ...     prompt="a cat walking on a fence", output_path=Path("clip.mp4"),
    ... ))

Raises:
    WaveSpeedError: WAVESPEED_API_KEY 缺失、提交/轮询/上传失败、超时,或产物为空。
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

_BASE_URL = "https://api.wavespeed.ai/api/v3"
_ENDPOINTS = {
    "happyhorse_1_1": "alibaba/happyhorse-1.1/text-to-video",
    "wan_2_7": "alibaba/wan-2.7/text-to-video",
}
# 只有 HappyHorse 提供纯图片(无需视频)的多参考图身份锁定端点,见模块 docstring。
_REFERENCE_ENDPOINTS = {
    "happyhorse_1_1": "alibaba/happyhorse-1.1/reference-to-video",
}
_MAX_REFERENCE_IMAGES = 9
_MIME_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}


class WaveSpeedError(Exception):
    """WaveSpeed 生成失败(缺 key、上传/提交/轮询失败、超时,或产物为空)。"""


def _resolve_aspect_ratio(aspect_ratio: str | None, kw: dict[str, Any]) -> str:
    """解析朝向:优先显式合法值,否则从 (w, h) size 推导;缺省 16:9(WaveSpeed 两个
    端点的文档默认值)。跟 oprim._fal_queue_generate._fal_aspect_ratio 同一套推导逻辑,
    本地实现一份而非依赖外部包的私有函数。"""
    if aspect_ratio in ("16:9", "9:16", "1:1", "4:3", "3:4"):
        return aspect_ratio  # type: ignore[return-value]
    size = kw.get("size")
    if isinstance(size, (tuple, list)) and len(size) == 2:
        w, h = size
        return "16:9" if w > h else "1:1" if w == h else "9:16"
    return "16:9"


def _api_key(config: dict[str, Any] | None) -> str:
    cfg = config or {}
    key = cfg.get("WAVESPEED_API_KEY") or os.getenv("WAVESPEED_API_KEY")
    if not key:
        raise WaveSpeedError("WAVESPEED_API_KEY not configured")
    return key


async def _upload_if_needed(client: httpx.AsyncClient, headers: dict[str, str], image: str) -> str:
    """WaveSpeed 的 images 字段只吃 URL(见模块 docstring)。已经是 http(s) URL 的直接
    透传;data: URI(hevi 参考图管线的内联 base64 惯例)先解码字节,走 WaveSpeed 自己
    的上传端点换成 download_url。"""
    if image.startswith(("http://", "https://")):
        return image
    if not image.startswith("data:"):
        raise WaveSpeedError(
            f"unsupported reference image format (not a data URI or URL): {image[:60]}"
        )
    header, _, b64data = image.partition(",")
    mime = header[5:].split(";")[0] if header.startswith("data:") else "image/png"
    ext = _MIME_EXT.get(mime, "png")
    raw = base64.b64decode(b64data)
    upload_headers = {
        "Authorization": headers["Authorization"]
    }  # 上传是 multipart,不带 json content-type
    resp = await client.post(
        f"{_BASE_URL}/media/upload/binary",
        headers=upload_headers,
        files={"file": (f"ref.{ext}", raw, mime)},
    )
    try:
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise WaveSpeedError(f"WaveSpeed 参考图上传失败: {e}") from e
    data = (resp.json().get("data") or {}) if isinstance(resp.json(), dict) else {}
    url = data.get("download_url")
    if not url:
        raise WaveSpeedError(f"WaveSpeed 上传响应缺少 download_url: {resp.text[:300]}")
    return url


def _extract_request_id(submitted: dict[str, Any]) -> str | None:
    # 响应信封在不同 WaveSpeed 端点间可能是顶层字段或套一层 "data" —— 两种都探测,
    # 不假设一定是哪一种(文档页没有给出逐字段的权威 schema)。
    sub_data = submitted.get("data") if isinstance(submitted.get("data"), dict) else submitted
    return sub_data.get("id") or submitted.get("request_id")


async def _submit_and_download(
    client: httpx.AsyncClient,
    *,
    endpoint: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    output_path: Path,
    model: str,
    poll_interval_s: float,
    timeout_s: float,
) -> Path:
    """提交任务、轮询至完成、下载视频到 output_path。t2v 和参考图锁定生成共用这一段
    (二者只有 endpoint + payload 不同,提交/轮询/下载/校验产物这套壳完全一样)。"""
    try:
        resp = await client.post(f"{_BASE_URL}/{endpoint}", json=payload, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise WaveSpeedError(f"WaveSpeed({model}) 任务提交失败: {e}") from e

    request_id = _extract_request_id(resp.json())
    if not request_id:
        raise WaveSpeedError(f"WaveSpeed({model}) 提交响应缺少任务 id: {resp.text[:300]}")

    elapsed = 0.0
    while elapsed < timeout_s:
        await asyncio.sleep(poll_interval_s)
        elapsed += poll_interval_s
        try:
            status_resp = await client.get(
                f"{_BASE_URL}/predictions/{request_id}/result", headers=headers
            )
            status_resp.raise_for_status()
        except httpx.HTTPError as e:
            raise WaveSpeedError(f"WaveSpeed({model}) 任务查询失败 (id={request_id}): {e}") from e

        body = status_resp.json()
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        status = data.get("status")
        if status == "completed":
            outputs = data.get("outputs") or []
            if not outputs:
                raise WaveSpeedError(
                    f"WaveSpeed({model}) 任务 {request_id} 状态 completed 但无产物: {str(body)[:300]}"
                )
            video_resp = await client.get(outputs[0], timeout=httpx.Timeout(300.0))
            video_resp.raise_for_status()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(video_resp.content)
            if not output_path.exists() or output_path.stat().st_size < 1024:
                raise WaveSpeedError(f"WaveSpeed({model}) 产出空/过小文件: {output_path}")
            logger.info(
                "WaveSpeed(%s): task %s → %s (%d bytes)",
                model,
                request_id,
                output_path.name,
                output_path.stat().st_size,
            )
            return output_path
        if status == "failed":
            raise WaveSpeedError(f"WaveSpeed({model}) 任务 {request_id} 失败: {data.get('error')}")
        logger.debug("WaveSpeed(%s): task %s 状态 %s,继续轮询", model, request_id, status)
    raise WaveSpeedError(f"WaveSpeed({model}) 任务 {request_id} 在 {timeout_s}s 内未完成")


async def wavespeed_generate(
    *,
    prompt: str,
    output_path: Path,
    model: str,
    aspect_ratio: str = "16:9",
    duration_s: float = 5,
    resolution: str = "720p",
    negative_prompt: str = "",
    seed: int | None = None,
    config: dict[str, Any] | None = None,
    poll_interval_s: float = 5.0,
    timeout_s: float = 600.0,
    **_kw: Any,
) -> Path:
    """提交一个 WaveSpeed 纯文生视频任务、轮询至完成、下载视频到 output_path。

    Args:
        prompt: 文本提示。
        output_path: 产物落盘路径。
        model: `"happyhorse_1_1"` 或 `"wan_2_7"`(见 `_ENDPOINTS`)。
        aspect_ratio: 朝向;非法值按 size 推导或回退 16:9。
        duration_s: 时长秒(两个端点均支持 3~15s,默认 5)。
        resolution: `"720p"` 或 `"1080p"`。
        negative_prompt: 负向提示(仅 wan_2_7 端点吃这个字段,happyhorse_1_1 忽略)。
        seed: 随机种子;不传则由 WaveSpeed 侧随机。
        config: 覆盖 dict(WAVESPEED_API_KEY),缺省回退环境变量。
        _kw: registry 注入的其余 kw 一律忽略(size 可参与 aspect_ratio 推导)。

    Returns:
        output_path。

    Raises:
        WaveSpeedError: 缺 key / 未知 model / 提交失败 / 任务失败 / 超时 / 空产物。
    """
    if model not in _ENDPOINTS:
        raise WaveSpeedError(
            f"unknown WaveSpeed model {model!r}, expected one of {sorted(_ENDPOINTS)}"
        )
    api_key = _api_key(config)
    output_path = Path(output_path)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "prompt": prompt,
        "aspect_ratio": _resolve_aspect_ratio(aspect_ratio, _kw),
        "resolution": resolution,
        "duration": int(duration_s),
    }
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    if seed is not None:
        payload["seed"] = seed

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        return await _submit_and_download(
            client,
            endpoint=_ENDPOINTS[model],
            payload=payload,
            headers=headers,
            output_path=output_path,
            model=model,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )


async def wavespeed_reference_generate(
    *,
    prompt: str,
    reference_images: list[str],
    output_path: Path,
    model: str = "happyhorse_1_1",
    aspect_ratio: str = "16:9",
    duration: float | None = None,
    resolution: str = "720p",
    seed: int | None = None,
    config: dict[str, Any] | None = None,
    poll_interval_s: float = 5.0,
    timeout_s: float = 600.0,
    **_kw: Any,
) -> Path:
    """喂 1~9 张参考图 → 身份锁定生成(跟 vidu_reference_to_video 同一能力层级,可以
    互相替换)。目前 WaveSpeed 只有 happyhorse_1_1 提供这个纯图片端点,见模块 docstring。

    Args:
        prompt: 文本提示(描述这一镜想要的场景/动作,不是长相——长相由参考图决定)。
        reference_images: 1~9 张参考图,http(s) URL 或 data: URI(base64 内联会自动
            先经 WaveSpeed 上传端点换成 URL,见 `_upload_if_needed`)。
        output_path: 产物落盘路径。
        model: 目前只支持 `"happyhorse_1_1"`(见 `_REFERENCE_ENDPOINTS`)。
        duration: 时长秒(3~15s,不传用 WaveSpeed 侧默认值 5)。
        config: 覆盖 dict(WAVESPEED_API_KEY),缺省回退环境变量。
        _kw: 调用方注入的其余 kw 一律忽略。

    Returns:
        output_path。

    Raises:
        WaveSpeedError: 缺 key / 未知 model / 参考图数量越界 / 上传/提交/任务失败 / 超时 / 空产物。
    """
    if model not in _REFERENCE_ENDPOINTS:
        raise WaveSpeedError(
            f"WaveSpeed reference-to-video 目前只支持 {sorted(_REFERENCE_ENDPOINTS)}, got {model!r}"
        )
    if not 1 <= len(reference_images) <= _MAX_REFERENCE_IMAGES:
        raise WaveSpeedError(
            f"reference_images must have 1-{_MAX_REFERENCE_IMAGES} items, "
            f"got {len(reference_images)}"
        )
    api_key = _api_key(config)
    output_path = Path(output_path)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        image_urls = [await _upload_if_needed(client, headers, img) for img in reference_images]
        payload: dict[str, Any] = {
            "images": image_urls,
            "prompt": prompt,
            "aspect_ratio": _resolve_aspect_ratio(aspect_ratio, _kw),
            "resolution": resolution,
        }
        if duration is not None:
            payload["duration"] = int(duration)
        if seed is not None:
            payload["seed"] = seed

        return await _submit_and_download(
            client,
            endpoint=_REFERENCE_ENDPOINTS[model],
            payload=payload,
            headers=headers,
            output_path=output_path,
            model=f"{model}/reference",
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )


async def happyhorse_1_1_generate(
    *, prompt: str, output_path: Path, config: dict[str, Any] | None = None, **kw: Any
) -> Path:
    """ProviderRegistry 注册用的窄接口(固定 model="happyhorse_1_1",纯 t2v)。"""
    return await wavespeed_generate(
        prompt=prompt, output_path=output_path, model="happyhorse_1_1", config=config, **kw
    )


async def wan_2_7_generate(
    *, prompt: str, output_path: Path, config: dict[str, Any] | None = None, **kw: Any
) -> Path:
    """ProviderRegistry 注册用的窄接口(固定 model="wan_2_7",纯 t2v)。"""
    return await wavespeed_generate(
        prompt=prompt, output_path=output_path, model="wan_2_7", config=config, **kw
    )


async def happyhorse_1_1_reference_to_video(
    *,
    prompt: str,
    reference_images: list[str],
    output_path: Path,
    config: dict[str, Any] | None = None,
    **kw: Any,
) -> Path:
    """跟 `vidu_reference_to_video` 同一调用约定的窄接口——可以直接替换进
    `hevi/cinematic/video_gen.py` 的 `video_gen` 参数,做智伯这类参考图锁脸场景。"""
    return await wavespeed_reference_generate(
        prompt=prompt,
        reference_images=reference_images,
        output_path=output_path,
        model="happyhorse_1_1",
        config=config,
        **kw,
    )
