"""INC-004 第3步(2026-07-19):check_gpu_available 的显存前置检查。真机撞见过同一份代码
GPU 空闲时能跑完(峰值 8.51GB),GPU 被共享卡上其它租户占用时直接 CUDA OOM——与其等模型
加载到一半才炸,不如在拉子进程前就用 nvidia-smi 顺带查一眼空闲显存,不够就快速失败。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hevi.image import sdxl_local_service as svc


def _fake_proc(*, returncode: int, stdout: bytes, stderr: bytes = b""):
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = returncode
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


async def test_check_gpu_available_raises_when_free_vram_below_threshold():
    proc = _fake_proc(returncode=0, stdout=b"NVIDIA GeForce RTX 3080, 5000\n")
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        with pytest.raises(svc.GPUUnavailableError, match="空闲显存不够"):
            await svc.check_gpu_available(min_free_mib=9000.0)


async def test_check_gpu_available_passes_when_free_vram_above_threshold():
    proc = _fake_proc(returncode=0, stdout=b"NVIDIA GeForce RTX 3080, 9500\n")
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        await svc.check_gpu_available(min_free_mib=9000.0)  # 不抛就是过


async def test_check_gpu_available_skips_vram_check_when_min_free_mib_none():
    """显式传 None → 只探活不查显存(旧调用方行为不变)。"""
    proc = _fake_proc(returncode=0, stdout=b"NVIDIA GeForce RTX 3080, 100\n")
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        await svc.check_gpu_available(min_free_mib=None)  # 空闲显存只有 100MiB 也不该抛


async def test_check_gpu_available_default_uses_9gb_threshold():
    """默认参数就是 9GB 门槛(不用显式传),对齐 2026-07-19 真机实测的 8.51GB 峰值+余量。"""
    proc = _fake_proc(returncode=0, stdout=b"NVIDIA GeForce RTX 3080, 2411\n")
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        with pytest.raises(svc.GPUUnavailableError):
            await svc.check_gpu_available()


async def test_check_gpu_available_still_raises_on_smi_failure():
    """探活本身失败(卡掉出总线)的既有行为不受这次改动影响。"""
    proc = _fake_proc(returncode=1, stdout=b"", stderr=b"Unable to determine the device handle")
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=proc)):
        with pytest.raises(svc.GPUUnavailableError, match="探活失败"):
            await svc.check_gpu_available()
