"""json2video 场景底图 —— L6 无角色建立镜头(establishing shot)的 image_gen 云端备选。

真实调用(api.json2video.com/v2,2026-07-08 用真实 key 验证过,消耗 1 credit):
  - 提交: POST /v2/movies
  - 查询: GET  /v2/movies?project={id}
接口/字段是现查文档 + 一次真实调用核对的响应形状,不是凭记忆猜的:
{"movie": {"status": "done"|"running"|"error", "url": "...", "message": "..."}}

**为什么只能用在无角色镜头**:json2video 的 AI 生图(Flux)是纯文本生图,没有 IP-Adapter
那种"给参考图保角色一致"的机制。hevi/tongjian/scene_render.py 里有角色的镜头靠本地
SDXL + IP-Adapter(extra["ip_adapter_image"])维持智伯/韩康子这些角色的跨镜头一致性,
换成这个 provider 会直接丢掉那份一致性——只应该接给 generate_scene_assets()(场景底图,
本来就不带角色)当 image_gen 参数传入,不能替换 render_shot() 用的那个。

json2video 没有独立的"只出图"接口——它的产品形态是"渲染一段视频",所以这里提交一个
1 秒、单张 AI 生成图片的最小 movie,渲染完用本地 ffmpeg 抽一帧存成 output_path。
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.json2video.com/v2"


class Json2VideoError(Exception):
    """json2video 生成失败(缺 key、提交/轮询失败、超时,或产物为空)。"""


def _resolve_api_key(config: dict[str, Any] | None) -> str:
    cfg = config or {}
    api_key = cfg.get("JSON2VIDEO_API_KEY") or os.getenv("JSON2VIDEO_API_KEY")
    if not api_key:
        raise Json2VideoError("JSON2VIDEO_API_KEY not configured")
    return api_key


def _extract_first_frame(video_path: Path, output_path: Path) -> None:
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-update",
                "1",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise Json2VideoError(f"ffmpeg 抽帧失败: {e.stderr}") from e


async def json2video_scene_generate(
    *,
    prompt: str,
    negative_prompt: str = "",
    width: int = 832,
    height: int = 480,
    output_path: Path | str,
    seed: int | None = None,
    extra: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    model: str = "flux-schnell",
    poll_interval_s: float = 5.0,
    timeout_s: float = 300.0,
    **_: Any,
) -> dict[str, Any]:
    """L6 无角色场景底图的云端备选(json2video Flux 文本生图),供本地 GPU 不可用时切换。

    seed 没有实际效果(json2video API 不支持),形参保留只是为了跟 sdxl_local_generate
    同一套 image_gen 调用约定兼容。extra 同理接收但忽略——IP-Adapter 条件化(有角色的
    镜头)不应该走到这个 provider,见模块docstring。

    Matches obase.provider_registry.ImageGenCaller 的返回形状(同 sdxl_local_generate):
    {"output_path": str, "seed": int | None}。
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    api_key = _resolve_api_key(config)
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}

    full_prompt = prompt if not negative_prompt else f"{prompt}. Avoid: {negative_prompt}."
    payload: dict[str, Any] = {
        "resolution": "custom",
        "width": width,
        "height": height,
        "quality": "high",
        "scenes": [
            {
                "elements": [
                    {
                        "type": "image",
                        "model": model,
                        "prompt": full_prompt,
                        "resize": "cover",
                        "duration": 1,
                    }
                ]
            }
        ],
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(f"{_BASE_URL}/movies", json=payload, headers=headers)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            body = getattr(e, "response", None)
            raise Json2VideoError(
                f"json2video 任务提交失败: {e} | {body.text if body is not None else ''}"
            ) from e
        project_id = resp.json().get("project")
        if not project_id:
            raise Json2VideoError(f"json2video 提交响应缺少 project id: {resp.text}")

        # 文档明确要求轮询间隔不小于 5 秒。
        await asyncio.sleep(max(poll_interval_s, 5.0))
        elapsed = 0.0
        while elapsed < timeout_s:
            try:
                status_resp = await client.get(
                    f"{_BASE_URL}/movies", params={"project": project_id}, headers=headers
                )
                status_resp.raise_for_status()
            except httpx.HTTPError as e:
                raise Json2VideoError(f"json2video 任务查询失败 (project={project_id}): {e}") from e

            movie = status_resp.json().get("movie") or {}
            status = movie.get("status")
            if status == "done":
                video_url = movie.get("url")
                if not video_url:
                    raise Json2VideoError(
                        f"json2video 任务 {project_id} 状态 done 但无产物 URL: {movie}"
                    )
                video_resp = await client.get(video_url)
                video_resp.raise_for_status()
                with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                    tmp.write(video_resp.content)
                    tmp_path = Path(tmp.name)
                try:
                    _extract_first_frame(tmp_path, output_path)
                finally:
                    tmp_path.unlink(missing_ok=True)
                logger.info("json2video: project %s 完成,已抽帧存到 %s", project_id, output_path)
                return {"output_path": str(output_path), "seed": seed}
            if status == "error":
                raise Json2VideoError(
                    f"json2video 任务 {project_id} 失败: {movie.get('message') or movie}"
                )
            logger.debug("json2video: project %s 状态 %s,继续轮询", project_id, status)
            await asyncio.sleep(poll_interval_s)
            elapsed += poll_interval_s

    raise Json2VideoError(f"json2video 任务 {project_id} 在 {timeout_s}s 内未完成")
