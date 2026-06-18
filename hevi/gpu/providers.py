"""hevi GPU model providers — LocalModelProvider implementations for each local model.

VRAM budgets (MB, measured on RTX 3080 2026-06-18):
  vibevoice     8513   (VibeVoice 1.5B bf16 — synthesis peak)
  qwen_local    7766   (Qwen3.5-9B via ollama — inference + thinking peak)
  gemma_vision     0   (gemma4:e4b via ollama — TBD pending VRAM test)
  duix          5242   (Duix container)
  wan_local     5407   (Wan2GP+CausVid 8-step subprocess — mmgp profile 5)

All pairs exceed RTX 3080 total (10240 MiB) → strict serial scheduling required.
"""
from __future__ import annotations

import logging
import subprocess

from obase.gpu import ModelRegistry

logger = logging.getLogger(__name__)

# ─── VRAM constants (MB) ────────────────────────────────────────────────────

# Measured: 8513 MiB peak (vibevoice 1.5B bf16, RTX 3080, 2026-06-18, synthesis)
VRAM_VIBEVOICE = 8513.0
# Measured: 7766 MiB peak (nvidia-smi dmon fb, RTX 3080, 2026-06-18, inference + thinking)
VRAM_QWEN_LOCAL = 7766.0
VRAM_GEMMA_VISION = 0.0  # TBD — gemma4:e4b VRAM not yet measured
VRAM_DUIX = 5242.0
# Measured: 5407 MiB peak (Wan2GP+CausVid 8-step, profile 5, RTX 3080, 2026-06-18)
# Down from 9917 MiB (native 30-step); subprocess-managed via wgp.py mmgp offloading
VRAM_WAN_LOCAL = 5407.0


# ─── VibeVoice provider ──────────────────────────────────────────────────────

class VibeVoiceProvider:
    """Manages VibeVoice model lifecycle (load = no-op; oprim handles it)."""

    def __init__(self) -> None:
        self._loaded = False

    async def load(self) -> None:
        self._loaded = True
        logger.info("GPU: vibevoice marked loaded (oprim manages model bundle)")

    async def unload(self) -> None:
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        self._loaded = False
        logger.info("GPU: vibevoice unloaded (cuda cache cleared)")

    def is_loaded(self) -> bool:
        return self._loaded


# ─── Qwen local provider (ollama) ───────────────────────────────────────────

class QwenLocalProvider:
    """Manages qwen_local (Qwen3.5-9B) via ollama CLI."""

    MODEL = "qwen3.5:9b"

    def __init__(self) -> None:
        self._loaded = False

    async def load(self) -> None:
        try:
            subprocess.run(
                ["ollama", "pull", self.MODEL],
                check=True, capture_output=True, timeout=300,
            )
        except Exception as e:
            logger.warning(f"GPU: qwen_local pull warning: {e}")
        self._loaded = True
        logger.info("GPU: qwen_local loaded (ollama)")

    async def unload(self) -> None:
        try:
            subprocess.run(
                ["ollama", "stop", self.MODEL],
                check=False, capture_output=True, timeout=30,
            )
        except Exception as e:
            logger.warning(f"GPU: qwen_local stop warning: {e}")
        self._loaded = False
        logger.info("GPU: qwen_local unloaded (ollama stop)")

    def is_loaded(self) -> bool:
        return self._loaded


# ─── Gemma vision provider (ollama, optional) ───────────────────────────────

class GemmaVisionProvider:
    """Manages gemma_vision (gemma4:e4b) via ollama CLI — optional image understanding."""

    MODEL = "gemma4:e4b"

    def __init__(self) -> None:
        self._loaded = False

    async def load(self) -> None:
        try:
            subprocess.run(
                ["ollama", "pull", self.MODEL],
                check=True, capture_output=True, timeout=300,
            )
        except Exception as e:
            logger.warning(f"GPU: gemma_vision pull warning: {e}")
        self._loaded = True
        logger.info("GPU: gemma_vision loaded (ollama)")

    async def unload(self) -> None:
        try:
            subprocess.run(
                ["ollama", "stop", self.MODEL],
                check=False, capture_output=True, timeout=30,
            )
        except Exception as e:
            logger.warning(f"GPU: gemma_vision stop warning: {e}")
        self._loaded = False
        logger.info("GPU: gemma_vision unloaded (ollama stop)")

    def is_loaded(self) -> bool:
        return self._loaded


# ─── Duix container provider ────────────────────────────────────────────────

class DuixProvider:
    """Manages Duix avatar container lifecycle (docker start/stop)."""

    CONTAINER = "duix-avatar-gen-video"

    def __init__(self) -> None:
        self._loaded = False

    async def load(self) -> None:
        try:
            subprocess.run(
                ["docker", "start", self.CONTAINER],
                check=True, capture_output=True, timeout=60,
            )
        except Exception as e:
            logger.warning(f"GPU: duix container start warning: {e}")
        self._loaded = True
        logger.info("GPU: duix container started")

    async def unload(self) -> None:
        try:
            subprocess.run(
                ["docker", "stop", self.CONTAINER],
                check=False, capture_output=True, timeout=30,
            )
        except Exception as e:
            logger.warning(f"GPU: duix container stop warning: {e}")
        self._loaded = False
        logger.info("GPU: duix container stopped")

    def is_loaded(self) -> bool:
        return self._loaded


# ─── Wan local provider ──────────────────────────────────────────────────────

class WanLocalProvider:
    """Sentinel for wan_local in GpuScheduler registry.

    Generation is handled by wan_local_service._run_wgp() (Wan2GP subprocess).
    The subprocess self-manages its own VRAM lifecycle via mmgp offloading.
    load()/unload() are no-ops; GpuScheduler.acquire() provides the serial lock.
    """

    def __init__(self) -> None:
        self._loaded = False

    async def load(self) -> None:
        self._loaded = True
        logger.info("GPU: wan_local marked active (Wan2GP subprocess manages VRAM)")

    async def unload(self) -> None:
        self._loaded = False
        logger.info("GPU: wan_local released (subprocess exited, VRAM freed by OS)")

    def is_loaded(self) -> bool:
        return self._loaded


# Module-level singleton — registered in GpuScheduler for serial lock coordination
wan_local_provider = WanLocalProvider()


# ─── Registry setup ─────────────────────────────────────────────────────────

def setup_model_registry() -> ModelRegistry:
    """Create and populate a ModelRegistry with all hevi local model providers."""
    registry = ModelRegistry()
    registry.register("vibevoice", VibeVoiceProvider())
    registry.register("qwen_local", QwenLocalProvider())
    registry.register("gemma_vision", GemmaVisionProvider())
    registry.register("duix", DuixProvider())
    registry.register("wan_local", wan_local_provider)
    return registry

