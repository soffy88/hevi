"""lux_tts_service —— LuxTTS 轻量克隆 TTS 适配(可选集成, 差距 B8)。

对标 LuxTTS(zipvoice 架构: 4 步采样 / 48kHz / 150x 实时 / <1GB VRAM / CPU 可跑),
补 hevi 差距: 现有 F5/CosyVoice/Echo 都是重 GPU 模型, 缺低资源克隆档。

集成方式(3O: 可选能力, 不引入硬依赖):
  - luxvoice 模块(用户自装: `pip install luxvoice` 或源码路径)存在 → 启用;
    否则 `lux_tts_available()` 返回 False, 服务层走现有 provider。
  - `HEVI_LUXVOICE_MODEL_DIR` 指定模型目录(缺省 ~/luxvoice 或空)。
  - `synth_with_luxvoice(text, reference_audio, output_path, ...)` → wav。
  - 注册: audio_router._synthesize_formal 增加 `HEVI_TTS_FORMAL_PROVIDER=lux` 分支
    (见 hevi/audio/audio_router.py 的 lux 分支)。

测试: 不装 luxvoice 也能测(可用性探测 + 注入假模块的合成路径)。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def lux_tts_available() -> bool:
    """探测 luxvoice 是否可导入 + 模型目录是否可定位。失败仅记日志。"""
    if shutil.which("luxvoice") or _import_luxvoice() is not None:
        # CLI 或模块任一可用即视为可用; 模型目录缺省时由 CLI 自行下载
        return True
    logger.debug("luxvoice not installed (pip install luxvoice or clone LuxTTS)")
    return False


def _import_luxvoice() -> Any | None:
    try:
        import luxvoice  # type: ignore[import-not-found]

        return luxvoice
    except ImportError:
        return None


def _model_dir() -> Path | None:
    raw = os.getenv("HEVI_LUXVOICE_MODEL_DIR", "").strip()
    if not raw:
        return None
    p = Path(raw)
    return p if p.exists() else None


async def synth_with_luxvoice(
    text: str,
    output_path: Path,
    *,
    reference_audio: str | Path | None = None,
    speed: float = 1.0,
    **kwargs: Any,
) -> Path:
    """LuxTTS 合成入口。

    Args:
        text: 合成文本。
        output_path: 输出 wav 路径。
        reference_audio: 克隆参考音频(可选; 无则用默认音色)。
        speed: 语速倍率(映射到 LuxTTS speed 参数)。
        **kwargs: 透传 LuxTTS 采样参数(rms/t_shift/return_smooth 等)。
    Returns:
        输出路径(成功)。
    Raises:
        RuntimeError: luxvoice 不可用或合成失败。
    """
    mod = _import_luxvoice()
    if mod is None:
        raise RuntimeError(
            "luxvoice not available; install via `pip install luxvoice` or clone LuxTTS"
        )
    model_dir = _model_dir()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # 优先 CLI(模型管理/下载自理); 否则模块 API(按 LuxTTS 公开面适配)。
    if shutil.which("luxvoice"):
        cmd = ["luxvoice", "synth", text, str(output_path)]
        if reference_audio:
            cmd += ["--reference", str(reference_audio)]
        if model_dir:
            cmd += ["--model-dir", str(model_dir)]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"luxvoice CLI failed: {stderr.decode(errors='replace')[:400]}")
        if not output_path.exists():
            raise RuntimeError("luxvoice CLI finished without output file")
        return output_path
    synth_fn = getattr(mod, "synth", None)
    if synth_fn is None:
        raise RuntimeError("luxvoice module has no synth entry point")
    await synth_fn(
        text=text,
        output_path=str(output_path),
        reference_audio=str(reference_audio) if reference_audio else None,
        speed=speed,
        **kwargs,
    )
    if not output_path.exists():
        raise RuntimeError("luxvoice synth finished without output file")
    return output_path


__all__ = ["lux_tts_available", "synth_with_luxvoice"]
