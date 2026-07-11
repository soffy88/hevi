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
    VRAM_GEMMA_VISION,
    VRAM_QWEN_LOCAL,
    VRAM_SDXL_LOCAL,
    VRAM_VIBEVOICE,
    VRAM_WAN_LOCAL,
    sdxl_local_provider,
    setup_model_registry,
    wan_local_provider,
)

__all__ = [
    "VRAM_DUIX",
    "VRAM_GEMMA_VISION",
    "VRAM_QWEN_LOCAL",
    "VRAM_SDXL_LOCAL",
    "VRAM_VIBEVOICE",
    "VRAM_WAN_LOCAL",
    "scheduler",
    "sdxl_local_provider",
    "wan_local_provider",
]

# Singleton scheduler with hevi model registry
scheduler = GpuScheduler(registry=setup_model_registry())
