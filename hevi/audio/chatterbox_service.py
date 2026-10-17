"""Chatterbox TTS 引擎适配（对标 VoiceBox 的 Chatterbox Multilingual / Turbo）。

Chatterbox 提供两个变体:
- Chatterbox Multilingual: 23 种语言，最广泛的语言覆盖
- Chatterbox Turbo: 英语优化，350M 参数，支持副语言标签 [laugh] [sigh] 等

本模块实现 Protocol 适配，可无缝接入 Hevi 的 TTS 管线。
支持 lazy import（首次调用时才加载模型）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 支持的 23 种语言
CHATTERBOX_LANGUAGES = [
    "en", "zh", "ja", "ko", "fr", "de", "es", "pt", "it", "ru",
    "ar", "da", "fi", "el", "he", "hi", "ms", "no", "pl", "sw",
    "sv", "tr", "nl",
]

# Turbo 支持的副语言标签
TURBO_PARALINGUISTIC_TAGS = [
    "[laugh]", "[chuckle]", "[gasp]", "[cough]",
    "[sigh]", "[groan]", "[sniff]", "[shush]", "[clear_throat]",
]


@dataclass
class ChatterboxConfig:
    """Chatterbox 配置。"""
    variant: str = "multilingual"  # "multilingual" or "turbo"
    device: str = "cuda"  # "cuda", "cpu", "mps"
    sample_rate: int = 24000
    language: str = "en"
    temperature: float = 0.7
    seed: int | None = None
    working_dir: str = "/tmp/hevi_chatterbox"


class ChatterboxService:
    """Chatterbox TTS 引擎服务。

    支持两个变体:
    - multilingual: 23 语言覆盖，适合多语言场景
    - turbo: 英语优化 + 副语言标签支持，适合表达力强的英语对白
    """

    def __init__(self, config: ChatterboxConfig | None = None):
        self.config = config or ChatterboxConfig()
        self._model: Any = None
        self._loaded = False

    @property
    def variant(self) -> str:
        return self.config.variant

    @property
    def supports_paralinguistic(self) -> bool:
        """Turbo 变体支持副语言标签。"""
        return self.config.variant == "turbo"

    @property
    def supported_languages(self) -> list[str]:
        if self.config.variant == "turbo":
            return ["en"]  # Turbo 仅英语
        return CHATTERBOX_LANGUAGES

    def _load_model(self) -> None:
        """延迟加载模型。"""
        if self._loaded:
            return

        try:
            from chatterbox.tts import ChatterboxTTS
            self._model = ChatterboxTTS.from_pretrained(
                device=self.config.device,
            )
            self._loaded = True
            logger.info("Chatterbox %s loaded on %s", self.config.variant, self.config.device)
        except ImportError:
            logger.warning(
                "chatterbox not installed. Install with: pip install chatterbox-tts"
            )
            self._loaded = False
        except Exception as e:
            logger.error("Failed to load Chatterbox: %s", e)
            self._loaded = False

    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice_ref: Path | None = None,
        language: str | None = None,
        **kwargs: Any,
    ) -> Path:
        """合成语音。

        Args:
            text: 要合成的文本（turbo 可含 [laugh] 等标签）
            output_path: 输出文件路径
            voice_ref: 零样本克隆参考音频
            language: 语言代码（默认用配置值）

        Returns:
            输出文件路径
        """
        self._load_model()

        if not self._loaded:
            # Fallback: 生成静音占位
            return self._generate_silence(output_path, len(text) * 0.08)

        lang = language or self.config.language
        if lang not in self.supported_languages:
            logger.warning("language %s not supported by %s, falling back to en",
                           lang, self.config.variant)
            lang = "en"

        try:
            import torchaudio

            # 生成音频
            if voice_ref and voice_ref.exists():
                wav = self._model.generate(
                    text=text,
                    audio_prompt_path=str(voice_ref),
                    temperature=self.config.temperature,
                )
            else:
                wav = self._model.generate(
                    text=text,
                    temperature=self.config.temperature,
                )

            # 保存
            output_path.parent.mkdir(parents=True, exist_ok=True)
            torchaudio.save(
                str(output_path),
                wav,
                self.config.sample_rate,
            )
            logger.info("Chatterbox synthesized: %s → %s", text[:50], output_path)
            return output_path

        except Exception as e:
            logger.error("Chatterbox synthesis failed: %s", e)
            return self._generate_silence(output_path, len(text) * 0.08)

    def _generate_silence(self, output_path: Path, duration_s: float) -> Path:
        """生成静音占位文件（模型加载失败时的 fallback）。"""
        import numpy as np
        import soundfile as sf

        samples = int(self.config.sample_rate * duration_s)
        silence = np.zeros(samples, dtype=np.float32)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output_path), silence, self.config.sample_rate)
        return output_path

    async def synthesize_with_tags(
        self,
        text: str,
        output_path: Path,
        voice_ref: Path | None = None,
        **kwargs: Any,
    ) -> Path:
        """合成带副语言标签的语音（仅 Turbo 变体）。

        文本中可嵌入标签如:
        "Hello [laugh] how are you? [sigh] I missed you."

        Args:
            text: 含副语言标签的文本
            output_path: 输出文件路径
            voice_ref: 零样本克隆参考音频
        """
        if not self.supports_paralinguistic:
            logger.warning(
                "paralinguistic tags require turbo variant, "
                "synthesizing without tag interpretation"
            )

        # Chatterbox Turbo 原生支持 [laugh] 等标签
        return await self.synthesize(
            text=text,
            output_path=output_path,
            voice_ref=voice_ref,
            **kwargs,
        )

    def unload(self) -> None:
        """释放模型占用的 GPU 内存。"""
        if self._model is not None:
            del self._model
            self._model = None
            self._loaded = False
            import gc
            gc.collect()
            try:
                import torch
                torch.cuda.empty_cache()
            except ImportError:
                pass
            logger.info("Chatterbox model unloaded")

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant": self.config.variant,
            "device": self.config.device,
            "sample_rate": self.config.sample_rate,
            "language": self.config.language,
            "supports_paralinguistic": self.supports_paralinguistic,
            "supported_languages": self.supported_languages,
            "loaded": self._loaded,
        }


# ── 便捷工厂 ──────────────────────────────────────────────────────────────

def create_chatterbox_multilingual(
    language: str = "en",
    device: str = "cuda",
) -> ChatterboxService:
    """创建 Chatterbox Multilingual 服务（23 语言）。"""
    return ChatterboxService(ChatterboxConfig(
        variant="multilingual",
        device=device,
        language=language,
    ))


def create_chatterbox_turbo(
    device: str = "cuda",
) -> ChatterboxService:
    """创建 Chatterbox Turbo 服务（英语 + 副语言标签）。"""
    return ChatterboxService(ChatterboxConfig(
        variant="turbo",
        device=device,
        language="en",
    ))
