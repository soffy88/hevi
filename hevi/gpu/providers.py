"""hevi GPU model providers — LocalModelProvider implementations for each local model.

VRAM budgets (MB):
  vibevoice  6461   (VibeVoice 1.5B bf16)
  qwen_local 8253   (Qwen3-8B via ollama)
  duix       5242   (Duix container)
  wan_local  4243   (Wan-2.1 local, future)
"""
from __future__ import annotations

import logging
import subprocess

from obase.gpu import ModelRegistry

logger = logging.getLogger(__name__)

# ─── VRAM constants (MB) ────────────────────────────────────────────────────

VRAM_VIBEVOICE = 6461.0
VRAM_QWEN_LOCAL = 8253.0
VRAM_DUIX = 5242.0
VRAM_WAN_LOCAL = 4243.0


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
    """Manages qwen_local via ollama CLI."""

    MODEL = "qwen3:8b"

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


# ─── Duix container provider ────────────────────────────────────────────────

class DuixProvider:
    """Manages Duix avatar container lifecycle (docker start/stop)."""

    CONTAINER = "duix_avatar"

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


# ─── Registry setup ─────────────────────────────────────────────────────────

def setup_model_registry() -> ModelRegistry:
    """Create and populate a ModelRegistry with all hevi local model providers."""
    registry = ModelRegistry()
    registry.register("vibevoice", VibeVoiceProvider())
    registry.register("qwen_local", QwenLocalProvider())
    registry.register("duix", DuixProvider())
    return registry

