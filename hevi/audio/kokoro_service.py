"""Kokoro TTS 引擎适配（对标 VoiceBox 的 Kokoro 集成）。

Kokoro: 82M 超轻量 TTS 模型
- CPU 即可实时推理（无需 GPU）
- 50+ 预设音色（无需参考音频）
- 8 种语言支持
- 快速生成，适合预览和低资源场景

本模块实现 Protocol 适配，可无缝接入 Hevi 的 TTS 管线。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Kokoro 预设音色分类
KOKORO_VOICE_CATEGORIES = {
    "american_female": [
        "af_alloy", "af_aoede", "af_bella", "af_heart", "af_jessica",
        "af_kore", "af_nicole", "af_nova", "af_river", "af_sarah", "af_sky",
    ],
    "american_male": [
        "am_adam", "am_echo", "am_eric", "am_fenrir", "am_liam",
        "am_michael", "am_onyx", "am_puck", "am_santa",
    ],
    "british_female": [
        "bf_alice", "bf_emma", "bf_isabella", "bf_lily",
    ],
    "british_male": [
        "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
    ],
    "chinese_female": ["zf_xiaobei", "zf_xiaoni", "zf_xiaoxiao", "zf_xiaoyi"],
    "chinese_male": ["zm_yunxi", "zm_yunjian"],
    "japanese_female": ["jf_alpha", "jf_gongitsune", "jf_nezumi", "jf_tebukuro"],
    "japanese_male": ["jm_kumo"],
    "korean_female": ["kf_sora"],
    "korean_male": ["km_koala"],
}

KOKORO_LANGUAGES = ["en", "zh", "ja", "ko", "fr", "de", "es", "it"]


@dataclass
class KokoroConfig:
    """Kokoro 配置。"""
    voice: str = "af_heart"  # 默认音色
    language: str = "en"
    sample_rate: int = 24000
    speed: float = 1.0
    device: str = "cpu"  # Kokoro 主要跑 CPU
    working_dir: str = "/tmp/hevi_kokoro"


class KokoroService:
    """Kokoro TTS 引擎服务。

    82M 超轻量模型，CPU 实时推理，50+ 预设音色。
    适合：
    - 快速预览
    - 低资源环境（无 GPU）
    - 需要大量不同音色的场景
    """

    def __init__(self, config: KokoroConfig | None = None):
        self.config = config or KokoroConfig()
        self._pipeline: Any = None
        self._loaded = False

    @property
    def supported_languages(self) -> list[str]:
        return KOKORO_LANGUAGES

    @property
    def available_voices(self) -> dict[str, list[str]]:
        """返回按分类的可用音色列表。"""
        return KOKORO_VOICE_CATEGORIES

    def list_voices(self, category: str | None = None) -> list[str]:
        """列出可用音色。"""
        if category and category in KOKORO_VOICE_CATEGORIES:
            return KOKORO_VOICE_CATEGORIES[category]
        # 返回全部
        all_voices: list[str] = []
        for voices in KOKORO_VOICE_CATEGORIES.values():
            all_voices.extend(voices)
        return sorted(all_voices)

    def _load_model(self) -> None:
        """延迟加载模型。"""
        if self._loaded:
            return

        try:
            from kokoro import KPipeline
            lang_code = self._get_lang_code(self.config.language)
            self._pipeline = KPipeline(lang_code=lang_code)
            self._loaded = True
            logger.info("Kokoro loaded on %s (lang=%s)", self.config.device, self.config.language)
        except ImportError:
            logger.warning(
                "kokoro not installed. Install with: pip install kokoro-tts"
            )
            self._loaded = False
        except Exception as e:
            logger.error("Failed to load Kokoro: %s", e)
            self._loaded = False

    def _get_lang_code(self, language: str) -> str:
        """转换语言代码为 Kokoro 内部代码。"""
        lang_map = {
            "en": "a",   # American English
            "zh": "z",   # Chinese
            "ja": "j",   # Japanese
            "ko": "k",   # Korean
            "fr": "f",   # French
            "de": "d",   # German (not standard, may fall back)
            "es": "e",   # Spanish
            "it": "i",   # Italian
        }
        return lang_map.get(language, "a")

    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        language: str | None = None,
        speed: float | None = None,
        **kwargs: Any,
    ) -> Path:
        """合成语音。

        Args:
            text: 要合成的文本
            output_path: 输出文件路径
            voice: 音色名称（默认用配置值）
            language: 语言代码
            speed: 语速（0.5-2.0）

        Returns:
            输出文件路径
        """
        self._load_model()

        voice_name = voice or self.config.voice
        lang = language or self.config.language
        spd = speed or self.config.speed

        if not self._loaded:
            return self._generate_silence(output_path, len(text) * 0.08)

        try:
            import soundfile as sf
            import numpy as np

            # Kokoro pipeline 生成音频
            generator = self._pipeline(
                text,
                voice=voice_name,
                speed=spd,
            )

            # 收集所有音频片段
            audio_chunks: list[Any] = []
            for _graphemes, _tokens, audio in generator:
                if audio is not None:
                    audio_chunks.append(audio)

            if not audio_chunks:
                return self._generate_silence(output_path, len(text) * 0.08)

            # 拼接
            full_audio = np.concatenate(audio_chunks)

            # 保存
            output_path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(str(output_path), full_audio, self.config.sample_rate)
            logger.info("Kokoro synthesized: %s (voice=%s) → %s",
                        text[:50], voice_name, output_path)
            return output_path

        except Exception as e:
            logger.error("Kokoro synthesis failed: %s", e)
            return self._generate_silence(output_path, len(text) * 0.08)

    def _generate_silence(self, output_path: Path, duration_s: float) -> Path:
        """生成静音占位文件。"""
        import numpy as np
        import soundfile as sf

        samples = int(self.config.sample_rate * duration_s)
        silence = np.zeros(samples, dtype=np.float32)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output_path), silence, self.config.sample_rate)
        return output_path

    def unload(self) -> None:
        """释放模型。"""
        if self._pipeline is not None:
            del self._pipeline
            self._pipeline = None
            self._loaded = False
            import gc
            gc.collect()
            logger.info("Kokoro model unloaded")

    def to_dict(self) -> dict[str, Any]:
        return {
            "voice": self.config.voice,
            "language": self.config.language,
            "sample_rate": self.config.sample_rate,
            "speed": self.config.speed,
            "device": self.config.device,
            "loaded": self._loaded,
            "total_voices": sum(len(v) for v in KOKORO_VOICE_CATEGORIES.values()),
            "languages": KOKORO_LANGUAGES,
        }


# ── 便捷工厂 ──────────────────────────────────────────────────────────────

def create_kokoro(
    voice: str = "af_heart",
    language: str = "en",
    device: str = "cpu",
) -> KokoroService:
    """创建 Kokoro TTS 服务。"""
    return KokoroService(KokoroConfig(
        voice=voice,
        language=language,
        device=device,
    ))
