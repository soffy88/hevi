"""Hevi live host 数据契约（3O 共享 schema）。

纯数据容器 + 协议定义，无编排逻辑。供 oprim / oskill / omodul 三层共用。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class StageTiming:
    """单阶段耗时埋点（秒）。"""

    vad: float = 0.0
    stt: float = 0.0
    llm_first_token: float = 0.0
    llm_total: float = 0.0
    tts: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "vad": round(self.vad, 4),
            "stt": round(self.stt, 4),
            "llm_first_token": round(self.llm_first_token, 4),
            "llm_total": round(self.llm_total, 4),
            "tts": round(self.tts, 4),
        }

    @property
    def first_audio(self) -> float:
        """首音频延迟：输入结束 → 第一句音频合成完成。"""
        return self.vad + self.stt + self.llm_first_token + self.tts


@dataclass
class TurnInput:
    """一轮输入：文本弹幕或音频。"""

    text: str | None = None  # 直接文本（stdin/websocket 弹幕）
    audio_path: Path | None = None  # wav 文件输入（mic 录制落盘）
    source: str = "unknown"  # danmaku_stdin | danmaku_ws | mic | wav


@dataclass
class Utterance:
    """LLM 输出的一句（已切分）。"""

    index: int
    text: str
    audio_path: Path | None = None
    tts_seconds: float = 0.0


@dataclass
class TurnOutput:
    """一轮输出。"""

    transcript: str = ""  # STT 转写（音频输入时）
    question: str = ""  # 喂给 LLM 的文本
    reply_text: str = ""  # LLM 完整回复
    utterances: list[Utterance] = field(default_factory=list)
    timing: StageTiming = field(default_factory=StageTiming)


@dataclass
class EngineConfig:
    """引擎选择 + 各引擎参数（支持热切换）。"""

    stt: str = "whisper"
    llm: str = "ollama"
    tts: str = ""  # 空 → __post_init__ 读 HEVI_LIVE_TTS，再退回 piper；piper | cosyvoice | luxtts

    # whisper
    whisper_model: str = "/home/soffy/models/faster-whisper-large-v3-turbo"
    whisper_device: str = "cpu"
    whisper_compute: str = "int8"

    # ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "xiaoya-cpm5-2b-v2"
    persona: str = "小雅"
    max_reply_chars: int = 120

    # piper
    piper_binary: str = "/data/soffy/projects/hevi-zero/.venv/bin/piper"
    piper_model: str = "/data/soffy/projects/hevi-zero/voices/zh_CN-huayan-medium.onnx"

    # cosyvoice (可选, HTTP 委托 GPU 引擎)
    cosyvoice_base_url: str = "http://localhost:17600/api/ai/cosyvoice"

    # luxtts (可选, HTTP 委托 tailnet 上的 LuxTTS 服务; 默认不启用)
    luxtts_base_url: str = ""
    luxtts_voice: str = ""

    # AIGC 标识
    aigc_label_enabled: bool = True
    aigc_label_text: str = "AI生成"

    def __post_init__(self) -> None:
        """实例化时解析"未指定"的默认值（空串），按当前 env 而不是 import 时。"""
        if not self.tts:
            self.tts = os.environ.get("HEVI_LIVE_TTS") or "piper"
        if not self.luxtts_base_url:
            self.luxtts_base_url = os.environ.get(
                "HEVI_LIVE_LUXTTS_URL", "http://100.119.113.90:8795"
            )
        if not self.luxtts_voice:
            self.luxtts_voice = os.environ.get("HEVI_LIVE_LUXTTS_VOICE", "soffy")

    def to_dict(self) -> dict[str, Any]:
        return {
            "stt": self.stt,
            "llm": self.llm,
            "tts": self.tts,
            "whisper_model": self.whisper_model,
            "whisper_device": self.whisper_device,
            "whisper_compute": self.whisper_compute,
            "ollama_base_url": self.ollama_base_url,
            "ollama_model": self.ollama_model,
            "persona": self.persona,
            "max_reply_chars": self.max_reply_chars,
            "piper_binary": self.piper_binary,
            "piper_model": self.piper_model,
            "cosyvoice_base_url": self.cosyvoice_base_url,
            "luxtts_base_url": self.luxtts_base_url,
            "luxtts_voice": self.luxtts_voice,
            "aigc_label_enabled": self.aigc_label_enabled,
            "aigc_label_text": self.aigc_label_text,
        }


@runtime_checkable
class Engine(Protocol):
    """统一引擎协议：名字 + 是否可用。"""

    name: str

    def available(self) -> bool: ...


@runtime_checkable
class StreamingEngine(Protocol):
    """流式引擎：逐句产出（LLM / TTS）。"""

    name: str

    def available(self) -> bool: ...
