"""h3_local provider —— MiniMax H3(ComfyUI,8GB)本地视频供给,注册进 ProviderRegistry。

L0 能力行(schema 驱动,与 PROVIDER_LIMITS/成本表对齐;`H3_LOCAL_CAPABILITY` 即
规格里那一行 JSON 的 Python 镜像):

    id: h3_local | capabilities: i2v/t2v/native_audio/zh_prompt
    max_duration_sec: 8 | resolution: 512/768 | ref_image: true
    cost_per_sec: 0 | health: local_comfy | entrypoint: comfyui
    workflow: h3_w4a8_zh.json | vram_profile: 8gb_serial

调用约定与 registry 里其它 video provider 一致(见 longvideo_orchestrator 的
injected_video_fn):`caller(prompt=…, output_path=…, **kw)` → 返回产物 Path。

hevi 纪律:
  - H3 只消费已锁定的 ref(参考图路径由 Subject 适配层给出),不在这里做资产逻辑。
  - prompt 接受 compile_h3_prompt 产出的 dict(三段式)或纯字符串(整段当 integrated)。
  - 8GB 串行:GpuScheduler(VRAM_H3_LOCAL 锁)+ ComfyClient 串行队列双纪律。
  - raw 先落侧车 `<stem>.h3raw.mp4`,再走 post pipeline(FlashVSR/RIFE)到
    output_path;post 失败降级交付 raw(与 hevi「可降级」哲学一致)。
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from obase.provider_registry import ProviderRegistry

from hevi.gpu import VRAM_H3_LOCAL, scheduler
from hevi.prompt.h3_compiler import H3Render
from hevi.providers.h3_local.comfy_client import (
    ComfyClient,
    H3ComfyError,
    h3_length_for_duration,
)

logger = logging.getLogger(__name__)

#: L0 能力行(schema 驱动;能力矩阵的落地见 capability_guard.PROVIDER_LIMITS)。
H3_LOCAL_CAPABILITY: dict[str, Any] = {
    "id": "h3_local",
    "capabilities": ["i2v", "t2v", "native_audio", "zh_prompt"],
    "prompt_language": "zh",
    "max_duration_sec": 8,
    "resolution": ["512", "768"],
    "ref_image": True,
    "cost_per_sec": 0,
    "health": "local_comfy",
    "entrypoint": "comfyui",
    "workflow": "h3_w4a8_zh.json",
    "vram_profile": "8gb_serial",
    "notes": "MiniMax H3 W4A8(w4a8_mixed)+ Qwen3-VL Q2_K + FP16 视频 VAE + FP32 音频 VAE",
}

#: 8GB 档生成分辨率(竖/横/方)。调用方没给时按此默认。
_DEFAULT_SIZES = {"portrait": (768, 1344), "landscape": (1344, 768), "square": (768, 768)}
_H3_MIN_LENGTH = 124  # ~5s@24fps(17×7+5),H3 训练范围下限


def _resolve_render(prompt: Any) -> H3Render:
    """prompt 入参归一:dict(compile_h3_prompt 产物)→ H3Render;字符串整段当 integrated。"""
    if isinstance(prompt, H3Render):
        return prompt
    return H3Render.from_dict(prompt)


def _resolve_size(width: int | None, height: int | None, mode: str) -> tuple[int, int]:
    if width and height:
        return int(width), int(height)
    orientation = "portrait" if mode == "i2v" else "landscape"
    return _DEFAULT_SIZES[orientation]


async def h3_local_generate(
    *,
    prompt: str | dict[str, str] | H3Render,
    output_path: Path | str,
    reference_image: Path | str | None = None,
    reference_images: list[Path | str] | None = None,
    mode: str = "i2v",
    duration_s: float = 5.0,
    width: int | None = None,
    height: int | None = None,
    seed: int | None = None,
    config: dict[str, Any] | None = None,
    post: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Path:
    """ComfyUI H3 生成单镜 raw → 后处理(FlashVSR/RIFE)→ output_path。

    Args:
        prompt: H3 三段式 dict(compile_h3_prompt().to_dict())/H3Render,或纯字符串
            (整段当 integrated_multimodal_description;音效/配乐用缺省)。
        reference_image / reference_images: 已锁定的参考图(Subject 母卡等)。
            优先 reference_images;空则退化为纯文生视频(t2v)。
        mode: "i2v"(有 ref)/"t2v"(无 ref)。
        duration_s: 目标秒数(上限 8,能力行 max_duration_sec)。
        post: 后处理覆盖(upscale/interp/rife…,见 hevi.post.run_post_pipeline)。

    Returns:
        产物 Path(output_path):final(已超分±插帧);失败路径降级交付 raw。

    Raises:
        H3ComfyError: ComfyUI 不可达/校验失败/执行失败(调用方走 retake:重试/换种子,
            不换 Subject——hevi retake-protocol)。
    """
    cfg = dict(config or {})
    outp = Path(output_path)
    outp.parent.mkdir(parents=True, exist_ok=True)

    render = _resolve_render(prompt)
    integrated = render.integrated_multimodal_description.strip()
    if not integrated:
        raise H3ComfyError("h3_local: prompt 为空(compile_h3_prompt 产出 integrated 为空)")

    refs: list[Path] = []
    for p in [*(reference_images or []), *([reference_image] if reference_image else [])]:
        if p is None:
            continue
        path = Path(str(p))
        if path.exists() and path not in refs:
            refs.append(path)
    if not refs:
        mode = "t2v"
    duration = min(max(float(duration_s), 1.0), 8.0)
    length = max(h3_length_for_duration(duration), _H3_MIN_LENGTH)
    w, h = _resolve_size(width, height, mode)

    client = ComfyClient(
        base_url=cfg.get("comfy_url") or os.getenv("H3_COMFY_URL"),
        timeout_s=float(
            str(cfg.get("timeout_s") or os.getenv("H3_SHOT_TIMEOUT_S") or "1800")
        ),
    )
    if not await client.health():
        raise H3ComfyError(f"ComfyUI 不可达: {client.base_url}(h3_local 需要本地 ComfyUI 在跑)")

    workflow_name = str(cfg.get("workflow") or os.getenv("H3_WORKFLOW") or "h3_w4a8_zh.json")
    # 模型文件名默认值(与 .env.example 对齐;模板里 __UNET_GGUF__ 等占位符)。
    _MODEL_DEFAULTS = {
        "unet_gguf": ("H3_UNET_GGUF", "minimax_h3_fl2va_pruned_w4a8_mixed.safetensors"),
        "clip_gguf": ("H3_CLIP_GGUF", "qwen3vl-32B-MiniMax-H3-Q2_K.gguf"),
        "video_vae": ("H3_VIDEO_VAE", "minimax_h3_video_vae_fp16.safetensors"),
        "audio_vae": ("H3_AUDIO_VAE", "minimax_h3_audio_vae_fp32.safetensors"),
    }
    model_fills: dict[str, Any] = {}
    for key, (env, default) in _MODEL_DEFAULTS.items():
        model_fills[f"__{key.upper()}__"] = cfg.get(key) or os.getenv(env, default)

    workflow = client.build_workflow(
        workflow_name,
        prompt=integrated,
        length=length,
        width=w,
        height=h,
        seed=seed,
        output_prefix=f"h3_{outp.stem[:40]}",
        ref_images=refs,
        extra_fills=model_fills,
    )

    # raw 先落侧车(断点续跑/verdict 可查),final 由 post pipeline 产出。
    raw_path = outp.with_name(f"{outp.stem}.h3raw.mp4")
    logger.info(
        "h3_local: %s mode=%s dur=%.1fs len=%d %dx%d refs=%d seed=%s",
        outp.name, mode, duration, length, w, h, len(refs), seed or "random",
    )
    async with scheduler.acquire(VRAM_H3_LOCAL):
        await client.run_workflow(workflow, output_path=raw_path)

    if not raw_path.exists() or raw_path.stat().st_size < 1024:
        raise H3ComfyError(f"H3 raw 产物缺失: {raw_path}")

    # 后处理(默认按 env POST_UPSCALE/POST_INTERP;post dict 可覆盖)。
    # 延迟导入:hevi.post → h3_local.comfy_client → 本包 __init__ 存在环,函数体内
    # 再取避免 import 期循环(与 registry 启动时序无关)。
    from hevi.post import run_post_pipeline

    post_cfg = dict(post or {})
    post_cfg.setdefault("upscale", os.getenv("POST_UPSCALE", "flashvsr"))
    post_cfg.setdefault("interp", os.getenv("POST_INTERP", "rife2x"))
    try:
        await run_post_pipeline(
            raw_path, outp, config=post_cfg, fps_in=24, comfy_client=client
        )
    except Exception as e:
        logger.warning("h3_local: 后处理失败,降级交付 raw: %s", e)
        shutil.copy2(raw_path, outp)
    return outp


def register_h3_local() -> None:
    """注册 h3_local 进 ProviderRegistry(video 类目)。注册后即可被
    `ProviderRegistry.get().generic("video", "h3_local")` 取用(路由/直调同款)。"""
    ProviderRegistry.register("video", "h3_local", h3_local_generate, replace=True)
    logger.info("Registered video: h3_local (MiniMax H3 via ComfyUI, 8GB)")
