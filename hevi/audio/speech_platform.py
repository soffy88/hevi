"""Unified local-first speech platform contracts.

The project historically exposed TTS through several unrelated surfaces.  This
module is intentionally provider-agnostic: it describes what is installed and
what can be executed, while the existing task adapters remain responsible for
actual model execution.  Keeping discovery pure makes the catalog safe to use
from both the API and the UI without loading GPU models.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SpeechEngine:
    id: str
    name: str
    kind: str  # tts | asr
    mode: str  # local | sidecar | network
    available: bool
    requires_gpu: bool
    languages: tuple[str, ...]
    capabilities: tuple[str, ...]
    description: str
    setup: str | None = None
    implementation: str = "hevi"

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["languages"] = list(self.languages)
        body["capabilities"] = list(self.capabilities)
        body["status"] = "available" if self.available else "unavailable"
        return body


@dataclass(frozen=True)
class VoiceProfile:
    id: str
    name: str
    source: str  # builtin | catalog | reference
    engine: str
    language: str
    reference_audio: str = ""
    reference_text: str = ""
    attributes: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_TTS_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "voicebox",
        "name": "Voicebox",
        "mode": "sidecar",
        "requires_gpu": False,
        "languages": ("zh", "en"),
        "capabilities": ("tts", "emotion", "batch"),
        "description": "HEVI Voicebox sidecar，任务可持久化并回写音频产物。",
        "env": "VOICEBOX_BASE_URL",
        "setup": "配置 VOICEBOX_BASE_URL 并启动 hevi-voicebox。",
    },
    {
        "id": "cosyvoice",
        "name": "CosyVoice",
        "mode": "sidecar",
        "requires_gpu": True,
        "languages": ("zh", "en", "ja", "ko", "yue"),
        "capabilities": ("tts", "zero_shot_clone", "cross_lingual", "instruct", "batch"),
        "description": "CosyVoice GPU 算力引擎，支持零样本/跨语/指令模式。",
        "env": "GEN_ENGINE_BASE_URL",
        "setup": "配置 GEN_ENGINE_BASE_URL 或 AI_ENGINE_BASE_URL，并准备 CosyVoice 模型。",
    },
    {
        "id": "f5_tts",
        "name": "F5-TTS",
        "mode": "sidecar",
        "requires_gpu": True,
        "languages": ("zh", "en", "ja", "de", "fr"),
        "capabilities": ("tts", "zero_shot_clone", "multispeaker", "batch"),
        "description": "F5-TTS 零样本克隆和多说话人音色目录。",
        "env": "F5_TTS_REFERENCE_AUDIO",
        "setup": "提供 F5_TTS_REFERENCE_AUDIO 与对应 F5_TTS_REFERENCE_TEXT。",
    },
    {
        "id": "voxcpm",
        "name": "VoxCPM",
        "mode": "local",
        "requires_gpu": False,
        "languages": ("zh", "en", "fr", "de", "es", "pt", "it"),
        "capabilities": (
            "tts",
            "voice_design",
            "voice_clone",
            "cross_lingual",
            "streaming",
            "batch",
        ),
        "description": "VoxCPM 本地神经语音设计、参考音频克隆、跨语种与流式能力；兼容隔离 Python worker。",
        "setup": "设置 HEVI_VOXCPM_PYTHON 与 HEVI_VOXCPM_MODEL；无模型时 HEVI 原生语音仍可明确降级。",
        "implementation": "hevi-adapter",
    },
    {
        "id": "pocket_tts",
        "name": "Pocket TTS",
        "mode": "local",
        "requires_gpu": False,
        "languages": ("en", "fr", "de", "it", "pt", "es"),
        "capabilities": ("tts", "voice_clone", "cpu", "low_latency", "streaming", "batch"),
        "description": "Pocket TTS CPU 低延迟语音、参考音频克隆、批量与流式输出。",
        "setup": "项目依赖已安装 pocket-tts；首次调用会下载其模型权重。",
        "implementation": "hevi-adapter",
    },
    {
        "id": "lux_tts",
        "name": "LuxTTS",
        "mode": "local",
        "requires_gpu": False,
        "languages": ("zh", "en"),
        "capabilities": ("tts", "zero_shot_clone", "low_resource"),
        "description": "低资源本地克隆档；可在 CPU/小显存环境运行。",
        "setup": "安装 luxvoice 或提供对应本地模型。",
    },
    {
        "id": "edge_tts",
        "name": "Edge TTS",
        "mode": "network",
        "requires_gpu": False,
        "languages": ("100+" ,),
        "capabilities": ("tts", "multilingual", "word_timestamps"),
        "description": "多语言网络语音；作为明确标注的网络降级通道。",
        "setup": "安装 edge-tts，并确保运行环境可以访问服务。",
    },
)

_ASR_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "faster_whisper",
        "name": "Faster Whisper",
        "mode": "local",
        "requires_gpu": False,
        "languages": ("multilingual",),
        "capabilities": ("asr", "word_timestamps"),
        "description": "本地 Faster Whisper 转写与词级时间戳。",
        "setup": "安装 faster-whisper 并准备模型缓存。",
    },
    {
        "id": "whisper",
        "name": "Whisper family",
        "mode": "local",
        "requires_gpu": False,
        "languages": ("multilingual",),
        "capabilities": ("asr", "sentence_segments"),
        "description": "Whisper 兼容转写适配层。",
        "setup": "提供本地 Whisper 运行时。",
    },
    {
        "id": "pyannote",
        "name": "Pyannote diarization",
        "mode": "local",
        "requires_gpu": True,
        "languages": ("multilingual",),
        "capabilities": ("diarization", "speaker_labels"),
        "description": "可选强说话人分离；没有模型时保留启发式标签。",
        "setup": "安装 pyannote.audio 并配置模型访问凭据。",
    },
)


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _tts_available(spec: dict[str, Any]) -> bool:
    engine_id = str(spec["id"])
    if engine_id == "voicebox":
        return bool(os.getenv("VOICEBOX_BASE_URL", "").strip())
    if engine_id == "cosyvoice":
        return bool(
            os.getenv("GEN_ENGINE_BASE_URL", "").strip()
            or os.getenv("AI_ENGINE_BASE_URL", "").strip()
        )
    if engine_id == "f5_tts":
        return bool(os.getenv("F5_TTS_REFERENCE_AUDIO", "").strip()) or bool(
            os.getenv("GEN_ENGINE_BASE_URL", "").strip()
        )
    if engine_id == "voxcpm":
        try:
            from hevi.voicepro.oskill.native_voice import native_voice_available

            return native_voice_available() or _module_available("voxcpm")
        except Exception:
            return _module_available("voxcpm")
    if engine_id == "pocket_tts":
        try:
            from hevi.audio.pocket_tts_service import pocket_tts_available

            return bool(pocket_tts_available())
        except Exception:
            return False
    if engine_id == "lux_tts":
        try:
            from hevi.audio.lux_tts_service import lux_tts_available

            return bool(lux_tts_available())
        except Exception:
            return False
    return engine_id == "edge_tts" and _module_available("edge_tts")


def _asr_available(spec: dict[str, Any]) -> bool:
    engine_id = str(spec["id"])
    if engine_id == "faster_whisper":
        return _module_available("faster_whisper")
    if engine_id == "whisper":
        return _module_available("whisper") or _module_available("whisper_timestamped")
    if engine_id == "pyannote":
        return _module_available("pyannote.audio") or _module_available("pyannote_audio")
    return False


def list_engines(*, include_unavailable: bool = True) -> list[SpeechEngine]:
    engines: list[SpeechEngine] = []
    for spec in (*_TTS_SPECS, *_ASR_SPECS):
        is_tts = spec["id"] in {item["id"] for item in _TTS_SPECS}
        available = _tts_available(spec) if is_tts else _asr_available(spec)
        engine = SpeechEngine(
            id=str(spec["id"]),
            name=str(spec["name"]),
            kind="tts" if is_tts else "asr",
            mode=str(spec["mode"]),
            available=available,
            requires_gpu=bool(spec["requires_gpu"]),
            languages=tuple(spec["languages"]),
            capabilities=tuple(spec["capabilities"]),
            description=str(spec["description"]),
            setup=str(spec.get("setup") or "") or None,
            implementation=str(spec.get("implementation") or "hevi"),
        )
        if include_unavailable or engine.available:
            engines.append(engine)
    return engines


def get_engine(engine_id: str) -> SpeechEngine | None:
    return next((item for item in list_engines() if item.id == engine_id), None)


def list_voice_profiles() -> list[VoiceProfile]:
    profiles = [
        VoiceProfile("edge_zh_female_standard", "中文女声·标准", "builtin", "edge_tts", "zh"),
        VoiceProfile("edge_zh_male_standard", "中文男声·标准", "builtin", "edge_tts", "zh"),
        VoiceProfile("edge_en_female_standard", "English female", "builtin", "edge_tts", "en"),
    ]
    try:
        from hevi.audio.edge_tts_custom import CURATED_VOICES

        profiles.extend(
            VoiceProfile(
                id=key,
                name=key.replace("_", " "),
                source="builtin",
                engine="edge_tts",
                language=key.split("_")[0],
                attributes={"provider_voice": value},
            )
            for key, value in CURATED_VOICES.items()
            if key not in {item.id for item in profiles}
        )
    except Exception:
        pass
    try:
        from hevi.studio.voices import list_voices

        profiles.extend(
            VoiceProfile(
                id=item.voice_id,
                name=item.display,
                source="catalog",
                engine="cosyvoice",
                language=item.language,
                reference_audio=item.audio_path,
                reference_text=item.transcript,
            )
            for item in list_voices()
            if item.voice_id not in {profile.id for profile in profiles}
        )
    except Exception:
        pass
    profiles.extend(
        VoiceProfile(
            id=voice,
            name=f"Pocket TTS · {voice}",
            source="builtin",
            engine="pocket_tts",
            language=language,
            attributes={"provider_voice": voice, "cpu": True},
        )
        for voice, language in (
            ("alba", "en"),
            ("anna", "en"),
            ("azelma", "en"),
            ("estelle", "fr"),
            ("juergen", "de"),
            ("lola", "es"),
            ("rafael", "pt"),
        )
        if voice not in {profile.id for profile in profiles}
    )
    return profiles


def build_batch_plan(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Validate a batch without creating fake audio tasks."""
    jobs: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, item in enumerate(items):
        text = str(item.get("text") or "").strip()
        engine_id = str(item.get("engine") or "edge_tts")
        if not text:
            errors.append(f"items[{index}].text 不能为空")
            continue
        engine = get_engine(engine_id)
        if engine is None:
            errors.append(f"items[{index}].engine 未知: {engine_id}")
            continue
        if not engine.available:
            errors.append(f"items[{index}].engine 不可用: {engine_id}")
        jobs.append(
            {
                "index": index,
                "text": text,
                "engine": engine.id,
                "available": engine.available,
                "voice": str(item.get("voice") or ""),
                "language": str(item.get("language") or "zh"),
            }
        )
    return {"valid": not errors and bool(jobs), "jobs": jobs, "errors": errors}


def diagnostics() -> dict[str, Any]:
    engines = list_engines()
    return {
        "local_first": True,
        "python": sys.version.split()[0],
        "ffmpeg": shutil.which("ffmpeg") or None,
        "ffprobe": shutil.which("ffprobe") or None,
        "tts_available": [item.id for item in engines if item.kind == "tts" and item.available],
        "asr_available": [item.id for item in engines if item.kind == "asr" and item.available],
        "diarization": any(item.id == "pyannote" and item.available for item in engines),
        "notes": [
            "HEVI 不会因为目录项存在就声称模型已安装。",
            "没有强 diarization 模型时，现有 ingest.speakers 仍使用启发式标签。",
        ],
    }


__all__ = [
    "SpeechEngine",
    "VoiceProfile",
    "build_batch_plan",
    "diagnostics",
    "get_engine",
    "list_engines",
    "list_voice_profiles",
]
