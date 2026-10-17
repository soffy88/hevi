"""引擎注册表：可插拔 + 运行期热切换。"""

from __future__ import annotations

import logging
from typing import Any

from hevi.live_host.oprim.llm_ollama import OllamaLLM
from hevi.live_host.oprim.stt_whisper import WhisperSTT
from hevi.live_host.oprim.tts_cosyvoice import CosyVoiceTTS
from hevi.live_host.oprim.tts_luxtts import LuxTTS, LuxTTSWithFallback
from hevi.live_host.oprim.tts_piper import PiperTTS
from hevi.live_host.schemas import EngineConfig

logger = logging.getLogger(__name__)


class EngineRegistry:
    """按类别持有多个引擎实现，按 config 选择当前激活引擎。"""

    def __init__(self, cfg: EngineConfig) -> None:
        self.cfg = cfg
        self._factories = {
            "stt": {
                "whisper": lambda: WhisperSTT(
                    cfg.whisper_model, cfg.whisper_device, cfg.whisper_compute
                ),
            },
            "llm": {
                "ollama": lambda: OllamaLLM(
                    cfg.ollama_base_url, cfg.ollama_model, cfg.persona, cfg.max_reply_chars
                ),
            },
            "tts": {
                "piper": lambda: PiperTTS(cfg.piper_binary, cfg.piper_model),
                "cosyvoice": lambda: CosyVoiceTTS(cfg.cosyvoice_base_url),
                # LuxTTS 显式选中才启用；服务不可达自动回退到 piper（默认 TTS）。
                "luxtts": lambda: LuxTTSWithFallback(
                    LuxTTS(cfg.luxtts_base_url, cfg.luxtts_voice),
                    PiperTTS(cfg.piper_binary, cfg.piper_model),
                ),
            },
        }
        self._cache: dict[tuple[str, str], Any] = {}

    def select(self, category: str, key: str) -> None:
        """运行期热切换当前激活引擎（不重启进程）。"""
        if category not in self._factories or key not in self._factories[category]:
            raise KeyError(f"未知引擎: {category}/{key}")
        setattr(self.cfg, category, key)
        self._cache.pop((category, key), None)
        logger.info("热切换 %s -> %s", category, key)

    def get(self, category: str) -> Any:
        key = getattr(self.cfg, category)
        cache_key = (category, key)
        if cache_key not in self._cache:
            self._cache[cache_key] = self._factories[category][key]()
        return self._cache[cache_key]
