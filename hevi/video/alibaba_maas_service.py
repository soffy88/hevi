"""阿里云百炼(Model Studio)业务空间专属域名 —— HappyHorse 1.1 / Wan 2.7 视频生成。

跟 hevi 已有的 `wan_cloud`(外部依赖 `oprim._providers.wan_cloud`,走公共
`dashscope.aliyuncs.com` 域名 + `wanx2.1-t2v-turbo` 老款模型)是同一套 DashScope
异步任务 API 契约(提交(`X-DashScope-Async: enable`)→ 轮询 task_id →
`output.video_url`),差异只有两点:

1. **Host 不是公共域名,是业务空间专属域名(workspace-dedicated domain)**——每个
   Model Studio 工作空间一个独立 host,形如
   `{workspace_id}.{region}.maas.aliyuncs.com`,由 `ALIBABA_MAAS_HOST` 环境变量
   配置(不同工作空间/地域不同,不能硬编码,阿里官方文档:
   https://www.alibabacloud.com/help/en/model-studio/base-url)。
2. **模型 ID 是阿里官方目录里的新款** `"happyhorse-1.1-t2v"` / `"wan2.7-t2v"`
   (2026-07 上线),跟 `wan_cloud` 的 `wanx2.1-t2v-turbo` 并存,不是升级替换关系。

参考图锁定生成(`happyhorse_1_1_maas_reference_to_video`,模型 ID
`happyhorse-1.1-r2v`,官方文档:
https://www.alibabacloud.com/help/en/model-studio/happyhorse-reference-to-video-api-reference):
1~9 张参考图放进 `input.media`(`{"type": "reference_image", "url": ...}`),`url`
既支持真实 URL 也支持内联 `data:image/...;base64,...`——这点上阿里直连比 WaveSpeed
版本(见 `wavespeed_service.py`)简单:不需要额外上传步骤换 URL,`ensure_platform_binding`
给的 base64 data URI 直接能用。官方文档示例里 prompt 会用 `[Image 1]`/`[Image 2]`
这类标签指代对应参考图(适合"这张图是发型、那张图是服装"这种合成场景);hevi 这边
每张参考图都是同一个角色的不同角度,不做这种按图索引的合成,故直接透传原 prompt,
不额外插入 `[Image N]` 标签。

**排错记录(别再走这条弯路)**:用户给的 `sk-ws-` 前缀 key 第一次被误判成
WaveSpeed AI 的 key(`WAVESPEED_API_KEY`,见 `wavespeed_service.py`)——"ws" 联想到
"WaveSpeed" 看似合理,但两次真实调用全是 401。后来核实用户提供的下载凭证 CSV
才发现 `sk-ws-` 里的 "ws" 是 workspace(业务空间)缩写,这其实是阿里云自己的
Model Studio 专属域名,`.maas.aliyuncs.com` 就是阿里云域名,跟 WaveSpeed(
`api.wavespeed.ai`)完全无关。`wavespeed_service.py` 那份代码本身没错(是真实的
WaveSpeed API 契约,留着以后真拿到 WaveSpeed key 时能用),只是这把 key 从来
就不属于那边。

密钥/host 都走环境变量(`ALIBABA_MAAS_API_KEY` / `ALIBABA_MAAS_HOST`),同项目里
其余云 key 的既定惯例——不进 `hevi.core.config.Settings`。

Example:
    >>> import asyncio
    >>> from pathlib import Path
    >>> from hevi.video.alibaba_maas_service import wan_2_7_maas_generate
    >>> out = asyncio.run(wan_2_7_maas_generate(
    ...     prompt="a cat walking on a fence", output_path=Path("clip.mp4"),
    ... ))

Raises:
    AlibabaMaasError: 缺 key/host、未知 model、提交/轮询失败、超时,或产物为空。
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Source: https://www.alibabacloud.com/help/en/model-studio/happyhorse-text-to-video-api-reference
#         https://www.alibabacloud.com/help/en/model-studio/text-to-video-api-reference
_MODEL_IDS = {
    "happyhorse_1_1": "happyhorse-1.1-t2v",
    "wan_2_7": "wan2.7-t2v",
}
# 只有 HappyHorse 有纯图片参考图身份锁定的型号(r2v)——Wan 2.7 在阿里目录里同样
# 没有对应物(跟 WaveSpeed 那边核实到的结论一致,见 wavespeed_service.py)。
# Source: https://www.alibabacloud.com/help/en/model-studio/happyhorse-reference-to-video-api-reference
_REFERENCE_MODEL_IDS = {
    "happyhorse_1_1": "happyhorse-1.1-r2v",
}
_MAX_REFERENCE_IMAGES = 9

# 首尾帧生视频(kf2v = keyframe-to-video)—— 独立的 image2video 端点,跟 t2v/参考图
# 锁定生成的 video-generation 端点不是一回事(见 _submit_and_download 的 submit_path)。
# flash 档:官方文档标称比 plus 档快、便宜,hevi 全项目对云端生成默认走便宜档的既定
# 惯例(如 happyhorse_1_1 而非更贵型号)。
# Source: https://help.aliyun.com/zh/model-studio/image-to-video-by-first-and-last-frame-api-reference
_KEYFRAME_MODEL_ID = "wan2.2-kf2v-flash"
_KEYFRAME_SUBMIT_PATH = "/api/v1/services/aigc/image2video/video-synthesis"


class AlibabaMaasError(Exception):
    """阿里云 Model Studio 生成失败(缺 key/host、未知 model、提交/轮询失败、超时,或产物为空)。"""


def _api_key(config: dict[str, Any] | None) -> str:
    cfg = config or {}
    key = cfg.get("ALIBABA_MAAS_API_KEY") or os.getenv("ALIBABA_MAAS_API_KEY")
    if not key:
        raise AlibabaMaasError("ALIBABA_MAAS_API_KEY not configured")
    return key


def _host(config: dict[str, Any] | None) -> str:
    cfg = config or {}
    host = cfg.get("ALIBABA_MAAS_HOST") or os.getenv("ALIBABA_MAAS_HOST")
    if not host:
        raise AlibabaMaasError("ALIBABA_MAAS_HOST not configured (workspace-dedicated domain)")
    return host.rstrip("/")


def _headers(api_key: str) -> tuple[dict[str, str], dict[str, str]]:
    submit_headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    poll_headers = {"Authorization": f"Bearer {api_key}"}
    return submit_headers, poll_headers


def _to_data_uri_if_local(ref: str) -> str:
    """本机文件路径 → data: base64 URI;已经是 URL/data: 的原样透传(同
    `happyhorse_1_1_maas_lock_generate` 的转法)——阿里这几个端点都只吃 http(s) URL
    或 data: URI,不会去读本机文件路径(真实调用实测报 InvalidParameter "Failed to
    download <本地路径>")。"""
    if ref.startswith(("http://", "https://", "data:")):
        return ref
    import base64

    suffix = Path(ref).suffix.lower().lstrip(".") or "png"
    mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
    return f"data:image/{mime};base64,{base64.b64encode(Path(ref).read_bytes()).decode()}"


_DEFAULT_SUBMIT_PATH = "/api/v1/services/aigc/video-generation/video-synthesis"


async def _submit_and_download(
    client: httpx.AsyncClient,
    *,
    host: str,
    payload: dict[str, Any],
    submit_headers: dict[str, str],
    poll_headers: dict[str, str],
    output_path: Path,
    model: str,
    poll_interval_s: float,
    timeout_s: float,
    submit_path: str = _DEFAULT_SUBMIT_PATH,
) -> Path:
    """提交任务、轮询至完成、下载视频到 output_path。t2v/参考图锁定/首尾帧生视频共用
    这一段(仨只有 payload 和提交 path 不同,轮询/下载/校验产物这套壳完全一样)。
    `submit_path` 默认是 t2v/参考图锁定用的 video-generation 端点;首尾帧生视频是
    阿里另一个端点(image2video),见 `alibaba_maas_keyframe_generate`。
    """
    try:
        resp = await client.post(
            f"https://{host}{submit_path}",
            json=payload,
            headers=submit_headers,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise AlibabaMaasError(f"{model} 任务提交失败: {e}") from e

    task_id = (resp.json().get("output") or {}).get("task_id")
    if not task_id:
        raise AlibabaMaasError(f"{model} 提交响应缺少 task_id: {resp.text[:300]}")

    elapsed = 0.0
    while elapsed < timeout_s:
        await asyncio.sleep(poll_interval_s)
        elapsed += poll_interval_s
        try:
            status_resp = await client.get(
                f"https://{host}/api/v1/tasks/{task_id}", headers=poll_headers
            )
            status_resp.raise_for_status()
        except httpx.HTTPError as e:
            raise AlibabaMaasError(f"{model} 任务查询失败 (id={task_id}): {e}") from e

        output = status_resp.json().get("output") or {}
        status = output.get("task_status")
        if status == "SUCCEEDED":
            video_url = output.get("video_url")
            if not video_url:
                raise AlibabaMaasError(f"{model} 任务 {task_id} 成功但无 video_url: {output}")
            video_resp = await client.get(video_url, timeout=httpx.Timeout(300.0))
            video_resp.raise_for_status()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(video_resp.content)
            if not output_path.exists() or output_path.stat().st_size < 1024:
                raise AlibabaMaasError(f"{model} 产出空/过小文件: {output_path}")
            logger.info(
                "%s: task %s → %s (%d bytes)",
                model,
                task_id,
                output_path.name,
                output_path.stat().st_size,
            )
            return output_path
        if status in ("FAILED", "UNKNOWN", "CANCELED"):
            raise AlibabaMaasError(f"{model} 任务 {task_id} 失败(status={status}): {output}")
        logger.debug("%s: task %s 状态 %s,继续轮询", model, task_id, status)
    raise AlibabaMaasError(f"{model} 任务 {task_id} 在 {timeout_s}s 内未完成")


async def alibaba_maas_generate(
    *,
    prompt: str,
    output_path: Path,
    model: str,
    negative_prompt: str = "",
    resolution: str = "720P",
    ratio: str = "16:9",
    duration: int = 5,
    seed: int | None = None,
    config: dict[str, Any] | None = None,
    poll_interval_s: float = 5.0,
    timeout_s: float = 600.0,
    **_kw: Any,
) -> Path:
    """提交一个阿里云 Model Studio 纯文生视频任务、轮询至完成、下载视频到 output_path。

    Args:
        prompt: 文本提示。
        output_path: 产物落盘路径。
        model: `"happyhorse_1_1"` 或 `"wan_2_7"`(见 `_MODEL_IDS`)。
        negative_prompt: 负向提示,可选。
        resolution: `"720P"` 或 `"1080P"`(注意大写 P,阿里官方文档就是这么写的)。
        ratio: 画幅,`"16:9"`/`"9:16"`/`"1:1"`/`"4:3"`/`"3:4"`。
        duration: 时长秒(官方文档:2~15s)。
        seed: 随机种子;不传则由服务侧随机。
        config: 覆盖 dict(`ALIBABA_MAAS_API_KEY`/`ALIBABA_MAAS_HOST`),缺省回退环境变量。
        _kw: registry 注入的其余 kw 一律忽略。

    Returns:
        output_path。

    Raises:
        AlibabaMaasError: 缺 key/host / 未知 model / 提交失败 / 任务失败 / 超时 / 空产物。
    """
    if model not in _MODEL_IDS:
        raise AlibabaMaasError(f"unknown model {model!r}, expected one of {sorted(_MODEL_IDS)}")
    api_key = _api_key(config)
    host = _host(config)
    output_path = Path(output_path)
    submit_headers, poll_headers = _headers(api_key)

    payload: dict[str, Any] = {
        "model": _MODEL_IDS[model],
        "input": {"prompt": prompt},
        "parameters": {"resolution": resolution, "ratio": ratio, "duration": int(duration)},
    }
    if negative_prompt:
        payload["input"]["negative_prompt"] = negative_prompt
    if seed is not None:
        payload["parameters"]["seed"] = seed

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        return await _submit_and_download(
            client,
            host=host,
            payload=payload,
            submit_headers=submit_headers,
            poll_headers=poll_headers,
            output_path=output_path,
            model=model,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )


async def alibaba_maas_reference_generate(
    *,
    prompt: str,
    reference_images: list[str],
    output_path: Path,
    model: str = "happyhorse_1_1",
    resolution: str = "720P",
    ratio: str = "16:9",
    duration: float | None = None,
    seed: int | None = None,
    watermark: bool = False,
    config: dict[str, Any] | None = None,
    poll_interval_s: float = 5.0,
    timeout_s: float = 600.0,
    **_kw: Any,
) -> Path:
    """喂 1~9 张参考图 → 阿里官方 happyhorse-1.1-r2v 身份锁定生成(跟
    `vidu_reference_to_video` 同一能力层级,可以互相替换)。目前阿里目录里只有
    HappyHorse 提供这个纯图片端点,Wan 2.7 没有对应物(见模块 docstring)。

    Args:
        prompt: 文本提示(描述场景/动作,不需要按官方示例插入 `[Image N]` 标签——
            hevi 这边每张参考图都是同一角色的不同角度,不是按图索引的合成场景)。
        reference_images: 1~9 张参考图,http(s) URL 或 `data:` URI(阿里这个端点
            两种都直接支持,不需要像 WaveSpeed 那样先上传换 URL)。
        output_path: 产物落盘路径。
        model: 目前只支持 `"happyhorse_1_1"`(见 `_REFERENCE_MODEL_IDS`)。
        duration: 时长秒(官方文档:3~15s,不传则用服务侧默认值 5)。
        watermark: 阿里默认会在右下角打"Happy Horse"水印(`watermark=True`),这里
            默认关掉——正式产出不该带第三方水印。
        config: 覆盖 dict(`ALIBABA_MAAS_API_KEY`/`ALIBABA_MAAS_HOST`),缺省回退环境变量。
        _kw: 调用方注入的其余 kw 一律忽略。

    Returns:
        output_path。

    Raises:
        AlibabaMaasError: 缺 key/host / 未知 model / 参考图数量越界 / 提交/轮询失败 / 超时 / 空产物。
    """
    if model not in _REFERENCE_MODEL_IDS:
        raise AlibabaMaasError(
            f"reference-to-video 目前只支持 {sorted(_REFERENCE_MODEL_IDS)}, got {model!r}"
        )
    if not 1 <= len(reference_images) <= _MAX_REFERENCE_IMAGES:
        raise AlibabaMaasError(
            f"reference_images must have 1-{_MAX_REFERENCE_IMAGES} items, "
            f"got {len(reference_images)}"
        )
    api_key = _api_key(config)
    host = _host(config)
    output_path = Path(output_path)
    submit_headers, poll_headers = _headers(api_key)

    payload: dict[str, Any] = {
        "model": _REFERENCE_MODEL_IDS[model],
        "input": {
            "prompt": prompt,
            "media": [{"type": "reference_image", "url": img} for img in reference_images],
        },
        "parameters": {"resolution": resolution, "ratio": ratio, "watermark": watermark},
    }
    if duration is not None:
        payload["parameters"]["duration"] = int(duration)
    if seed is not None:
        payload["parameters"]["seed"] = seed

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        return await _submit_and_download(
            client,
            host=host,
            payload=payload,
            submit_headers=submit_headers,
            poll_headers=poll_headers,
            output_path=output_path,
            model=f"{model}/reference",
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )


async def happyhorse_1_1_maas_generate(
    *, prompt: str, output_path: Path, config: dict[str, Any] | None = None, **kw: Any
) -> Path:
    """ProviderRegistry 注册用的窄接口(固定 model="happyhorse_1_1")。"""
    return await alibaba_maas_generate(
        prompt=prompt, output_path=output_path, model="happyhorse_1_1", config=config, **kw
    )


async def wan_2_7_maas_generate(
    *, prompt: str, output_path: Path, config: dict[str, Any] | None = None, **kw: Any
) -> Path:
    """ProviderRegistry 注册用的窄接口(固定 model="wan_2_7")。"""
    return await alibaba_maas_generate(
        prompt=prompt, output_path=output_path, model="wan_2_7", config=config, **kw
    )


async def happyhorse_1_1_maas_reference_to_video(
    *,
    prompt: str,
    reference_images: list[str],
    output_path: Path,
    config: dict[str, Any] | None = None,
    **kw: Any,
) -> Path:
    """跟 `vidu_reference_to_video` 同一调用约定的窄接口——可以直接替换进
    `hevi/cinematic/video_gen.py` 的 `video_gen` 参数,做智伯这类参考图锁脸场景。"""
    return await alibaba_maas_reference_generate(
        prompt=prompt,
        reference_images=reference_images,
        output_path=output_path,
        model="happyhorse_1_1",
        config=config,
        **kw,
    )


async def happyhorse_1_1_maas_lock_generate(
    *,
    prompt: str,
    output_path: Path,
    reference_image: Path | str | None = None,
    config: dict[str, Any] | None = None,
    **kw: Any,
) -> Path:
    """`hevi/pipeline/longvideo_orchestrator.py`(create_episode/Series 主线管线)用的
    参考图锁脸窄接口。

    主线管线(角色库锁定,见 orchestrate_longvideo 的 `character_reference`)跟
    `wan_local_generate`/`ltx2_cloud_generate` 走同一套约定:单张 `reference_image`
    kwarg。而 `happyhorse_1_1_maas_reference_to_video`(上面这个)是仿
    `vidu_reference_to_video` 给 `hevi/cinematic/video_gen.py` 用的窄接口,吃的是
    `reference_images: list[str]`(阵列)——两条约定并存、互不兼容,此前若直接把
    `happyhorse_1_1_maas_ref`/`vidu` 注册给主线管线用,会在 i2v 分支炸
    `unexpected keyword argument 'reference_image'` 或吃不到参考图退化成纯 t2v。
    这个函数只做转译,不改任一边的既有约定。
    """
    if not reference_image:
        raise ValueError("happyhorse_1_1_maas_lock 需要 reference_image(角色锁脸场景专用)")
    ref = str(reference_image)
    # 阿里这个端点只吃 http(s) URL 或 data: URI(见模块 docstring),不会去读本机文件
    # 路径——真实调用实测报 InvalidParameter "Failed to download <本地路径>"。主线
    # 管线传来的 character_reference 是本机文件路径,这里现算成 data URI(同
    # hevi/cinematic/platform_binding.py::ensure_platform_binding 的转法,但这里不需要
    # 它那份 vault 血缘记账,就地转,不跨模块耦合)。已经是 URL/data: 的直接透传。
    if not ref.startswith(("http://", "https://", "data:")):
        import base64

        suffix = Path(ref).suffix.lower().lstrip(".") or "png"
        mime = "jpeg" if suffix in ("jpg", "jpeg") else suffix
        ref = f"data:image/{mime};base64,{base64.b64encode(Path(ref).read_bytes()).decode()}"
    return await happyhorse_1_1_maas_reference_to_video(
        prompt=prompt,
        reference_images=[ref],
        output_path=output_path,
        config=config,
        **kw,
    )


async def alibaba_maas_keyframe_generate(
    *,
    first_frame: Path | str,
    last_frame: Path | str,
    output_path: Path,
    prompt: str = "",
    negative_prompt: str = "",
    resolution: str = "720P",
    duration_s: float = 5.0,
    seed: int | None = None,
    watermark: bool = False,
    config: dict[str, Any] | None = None,
    poll_interval_s: float = 5.0,
    timeout_s: float = 600.0,
    **_kw: Any,
) -> Path:
    """首尾帧生视频(wan2.2-kf2v-flash,阿里官方文档:
    https://help.aliyun.com/zh/model-studio/image-to-video-by-first-and-last-frame-api-reference)。

    2026-07-13:这是"首尾帧关键帧"能力此前完全没有真实 provider 的根因修复——
    `oprim.first_last_frame_transition`(`hevi/creative/assist_service.py::make_transition`
    包了一层)一直存在,但 `ProviderRegistry` 从没注册过任何 `category="image_to_video"`
    的 provider,任何 `video_provider` 值都会 100% 撞 `FrameTransitionProviderNotFoundError`
    ——这是个孤立的、保证失败的桩,不是能真用的功能。这里补上真实实现 +
    `alibaba_maas_keyframe_lock_generate`(下面,转译成 oprim 那份契约的窄接口)并注册进
    registry,首尾帧生视频才第一次是条能跑通的真实调用路径。

    first_frame/last_frame: 本机文件路径或已有 URL/data: URI 均可(内部按需转 data
    URI,见 `_to_data_uri_if_local`——跟阿里其余端点同样只吃 URL/data:,不认本机路径)。
    duration_s: 官方文档时长参数是整数秒,这里按秒取整传给 API。
    """
    api_key = _api_key(config)
    host = _host(config)
    output_path = Path(output_path)
    submit_headers, poll_headers = _headers(api_key)

    payload: dict[str, Any] = {
        "model": _KEYFRAME_MODEL_ID,
        "input": {
            "first_frame_url": _to_data_uri_if_local(str(first_frame)),
            "last_frame_url": _to_data_uri_if_local(str(last_frame)),
        },
        "parameters": {
            "resolution": resolution,
            "duration": int(duration_s),
            "watermark": watermark,
        },
    }
    if prompt:
        payload["input"]["prompt"] = prompt
    if negative_prompt:
        payload["input"]["negative_prompt"] = negative_prompt
    if seed is not None:
        payload["parameters"]["seed"] = seed

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        return await _submit_and_download(
            client,
            host=host,
            payload=payload,
            submit_headers=submit_headers,
            poll_headers=poll_headers,
            output_path=output_path,
            model=_KEYFRAME_MODEL_ID,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
            submit_path=_KEYFRAME_SUBMIT_PATH,
        )


async def alibaba_maas_keyframe_lock_generate(
    *,
    first_frame: Path,
    last_frame: Path,
    duration_s: float,
    output_path: Path,
    timeout_s: float = 600.0,
    **_kw: Any,
) -> Path:
    """`ProviderRegistry.register("image_to_video", ...)` 用的窄接口——匹配
    `oprim.first_last_frame_transition` 的固定调用契约(`first_frame`/`last_frame`/
    `duration_s`/`output_path`/`timeout_s`,没有 `prompt`,见其函数签名)。不额外加
    prompt/negative_prompt/resolution 等旋钮——那些留给
    `alibaba_maas_keyframe_generate` 本体给需要更细控制的调用方直接用。
    """
    return await alibaba_maas_keyframe_generate(
        first_frame=first_frame,
        last_frame=last_frame,
        output_path=output_path,
        duration_s=duration_s,
        timeout_s=timeout_s,
    )
