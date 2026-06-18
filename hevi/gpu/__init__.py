"""hevi.gpu — GPU scheduling and model lifecycle management.

Usage in call sites:
    from hevi.gpu import scheduler, VRAM_VIBEVOICE

    async with scheduler.acquire(VRAM_VIBEVOICE):
        result = await vibevoice_synthesize(...)
"""
from __future__ import annotations

from obase.gpu import GpuScheduler

from hevi.gpu.providers import (
    VRAM_DUIX,
    VRAM_QWEN_LOCAL,
    VRAM_VIBEVOICE,
    VRAM_WAN_LOCAL,
    setup_model_registry,
)

__all__ = [
    "scheduler",
    "VRAM_VIBEVOICE",
    "VRAM_QWEN_LOCAL",
    "VRAM_DUIX",
    "VRAM_WAN_LOCAL",
]

# Singleton scheduler with hevi model registry
scheduler = GpuScheduler(registry=setup_model_registry())
