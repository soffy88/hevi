"""GPU 韧性守卫 —— 共享主机 GPU 余量检测与 provider 自动降级。

STATUS.md 硬约束:RTX 3080 与 ~90 个其他容器共享,随时可能掉(Xid 79)或被
占满。本模块提供:
  - gpu_headroom_mb(): 当前显存余量(0/None = 检测失败或不可用);
  - gpu_available(min_mb): 余量是否 ≥ 阈值(wan_local 需 ~5407 MiB);
  - degrade_audio_provider(): vibewoice(本地 GPU 合成)→ edge_tts(免费云端),
    主管道在 GPU 不足时自动降级,不整片失败。

纪律:只读 nvidia-smi,不在主进程 import torch/碰 CUDA(常驻进程不占显存)。
"""

from __future__ import annotations

import logging
import shutil
import subprocess

logger = logging.getLogger(__name__)

#: 各 GPU 负载的显存需求(MiB)。wan_local 实测峰值 5407。
WAN_LOCAL_VRAM_MB = 5407
SDXL_LOCAL_VRAM_MB = 4096
VIBEVOICE_VRAM_MB = 2048

#: GPU 检测失败的返回码约定。
GPU_UNKNOWN = -1


def gpu_headroom_mb() -> int:
    """当前 GPU 可用显存(MiB)。nvidia-smi 失败/不存在 → GPU_UNKNOWN(-1)。

    只读子进程,绝不 import torch —— 常驻 API 进程不能被 CUDA 初始化占住显存。
    """
    if not shutil.which("nvidia-smi"):
        return GPU_UNKNOWN
    try:
        out = subprocess.run(
            [
                "nvidia-smi", "--query-gpu=memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            # 卡掉出总线时 nvidia-smi 报 "Unable to determine the device handle"。
            return GPU_UNKNOWN
        used, total = (int(x) for x in out.stdout.strip().split(","))
        return total - used
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return GPU_UNKNOWN


def gpu_available(min_mb: int = WAN_LOCAL_VRAM_MB) -> bool:
    """GPU 余量是否 ≥ min_mb。检测失败视为不可用(保守,宁降级不冒险)。"""
    headroom = gpu_headroom_mb()
    if headroom <= 0:
        return False
    return headroom >= min_mb


def degrade_audio_provider(audio_provider: str, *, min_mb: int = VIBEVOICE_VRAM_MB) -> str:
    """本地 GPU 音频 provider 在显存不足时降级为 edge_tts(免费云端,零 GPU)。

    vibewoice 是子进程隔离的本地合成,模型加载吃显存;共享主机 GPU 被占满时
    会合成失败甚至拖垮整条任务。edge_tts 是免费且稳定的云端神经语音 ——
    降级只改 provider 名,不改任何调用方契约(ProviderRegistry 已注册 edge_tts)。

    Returns:
        降级后的 audio_provider(原值或 "edge_tts")。
    """
    if audio_provider not in ("vibewoice", "vibevoice"):
        return audio_provider  # 非本地 GPU provider,不干预
    if gpu_available(min_mb):
        return audio_provider
    logger.warning(
        "GPU 显存不足(%s MiB < %s MiB),audio provider 降级 vibewoice → edge_tts",
        gpu_headroom_mb(), min_mb,
    )
    return "edge_tts"


__all__ = [
    "GPU_UNKNOWN",
    "SDXL_LOCAL_VRAM_MB",
    "VIBEVOICE_VRAM_MB",
    "WAN_LOCAL_VRAM_MB",
    "degrade_audio_provider",
    "gpu_available",
    "gpu_headroom_mb",
]
