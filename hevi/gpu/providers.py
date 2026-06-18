"""hevi GPU model providers — LocalModelProvider implementations for each local model.

VRAM budgets (MB):
  vibevoice  6461   (VibeVoice 1.5B bf16)
  qwen_local 8253   (Qwen3-8B via ollama)
  duix       5242   (Duix container)
  wan_local  9917   (Wan-2.1 T2V-1.3B FP32 — measured peak nvidia-smi, 2026-06-18)
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Any

from obase.gpu import ModelRegistry

logger = logging.getLogger(__name__)

# ─── VRAM constants (MB) ────────────────────────────────────────────────────

VRAM_VIBEVOICE = 6461.0
VRAM_QWEN_LOCAL = 8253.0
VRAM_DUIX = 5242.0
# Measured peak: 9917 MiB (nvidia-smi) during 30-step denoising, RTX 3080 10GB
# Model idle (after load, before inference): 5919 MB
VRAM_WAN_LOCAL = 9917.0


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


# ─── Wan local provider ──────────────────────────────────────────────────────

class WanLocalProvider:
    """Manages Wan 2.1 T2V-1.3B model lifecycle (lazy GPU load, kept resident).

    T5 (11GB BF16) stays on CPU; DiT (5.3GB FP32) on GPU after load.
    First load() takes ~15-20 min; subsequent generate() calls skip reload.
    """

    CKPT_DIR = str(Path.home() / "models/wan2.1-t2v-1.3b")
    WAN_CLI_PATH = str(Path.home() / "Wan-CLI")
    WAN_VENV_SITE = str(Path.home() / "Wan2GP/venv_wan/lib/python3.14/site-packages")

    def __init__(self) -> None:
        self._model: Any = None

    def _ensure_paths(self) -> None:
        import sys
        if self.WAN_CLI_PATH not in sys.path:
            sys.path.insert(0, self.WAN_CLI_PATH)
        if self.WAN_VENV_SITE not in sys.path:
            sys.path.insert(0, self.WAN_VENV_SITE)

    def _load_sync(self) -> Any:
        self._ensure_paths()
        import wan  # noqa: PLC0415
        import wan.configs as configs  # noqa: PLC0415
        return wan.WanT2V(
            config=configs.wan_t2v_1_3B.t2v_1_3B,
            checkpoint_dir=self.CKPT_DIR,
            device_id=0,
            rank=0,
            t5_cpu=True,
        )

    async def load(self) -> None:
        if self._model is not None:
            return
        loop = asyncio.get_running_loop()
        self._model = await loop.run_in_executor(None, self._load_sync)
        logger.info("GPU: wan_local loaded (T5=CPU, DiT=GPU ~5919 MB)")

    async def unload(self) -> None:
        self._model = None
        try:
            import torch  # noqa: PLC0415
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        logger.info("GPU: wan_local unloaded (GPU cache cleared)")

    def is_loaded(self) -> bool:
        return self._model is not None

    def get_model(self) -> Any:
        return self._model


# Module-level singleton — shared between GpuScheduler registry and wan_local_service
wan_local_provider = WanLocalProvider()


# ─── Registry setup ─────────────────────────────────────────────────────────

def setup_model_registry() -> ModelRegistry:
    """Create and populate a ModelRegistry with all hevi local model providers."""
    registry = ModelRegistry()
    registry.register("vibevoice", VibeVoiceProvider())
    registry.register("qwen_local", QwenLocalProvider())
    registry.register("duix", DuixProvider())
    registry.register("wan_local", wan_local_provider)
    return registry

