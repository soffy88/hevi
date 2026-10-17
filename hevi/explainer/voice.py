"""Explainer Voice — 本地 CPU TTS 合成与词级对齐（Piper + Faster-Whisper）。

无外部网络、无付费 API、禁止 mock 真实产物。
支持按分段增量缓存与重算，仅对受影响的分段重新合成和对齐。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hevi.explainer.script import OralScript, ScriptSection

logger = logging.getLogger(__name__)

PIPER_BIN = Path("/data/soffy/projects/hevi-zero/.venv/bin/piper")
PIPER_VOICES_DIR = Path("/data/soffy/projects/hevi-zero/voices")
WHISPER_MODEL_DIR = Path(
    "/data/soffy/appdata/huggingface_hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120"
)

# 默认音色
DEFAULT_ZH_VOICE = "zh_CN-huayan-medium.onnx"
DEFAULT_EN_VOICE = "en_US-ryan-medium.onnx"

_WHISPER_MODEL_INSTANCE: Any = None


def get_whisper_model() -> Any:
    """按需延迟加载本地 faster-whisper CPU 模型（单例）。"""
    global _WHISPER_MODEL_INSTANCE
    if _WHISPER_MODEL_INSTANCE is None:
        from faster_whisper import WhisperModel
        if not WHISPER_MODEL_DIR.exists():
            raise RuntimeError(f"Whisper model directory not found: {WHISPER_MODEL_DIR}")
        _WHISPER_MODEL_INSTANCE = WhisperModel(
            str(WHISPER_MODEL_DIR),
            device="cpu",
            compute_type="int8",
            num_workers=2,
        )
    return _WHISPER_MODEL_INSTANCE


@dataclass
class WordAlignmentItem:
    word: str
    start_ms: int
    end_ms: int

    def to_dict(self) -> dict[str, Any]:
        return {"word": self.word, "start_ms": self.start_ms, "end_ms": self.end_ms}


@dataclass
class SectionAudioArtifact:
    section_id: str
    text_hash: str
    audio_path: str
    duration_ms: int
    words: list[WordAlignmentItem] = field(default_factory=list)
    sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "text_hash": self.text_hash,
            "audio_path": self.audio_path,
            "duration_ms": self.duration_ms,
            "words": [w.to_dict() for w in self.words],
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SectionAudioArtifact:
        words = [
            WordAlignmentItem(
                word=w["word"],
                start_ms=int(w["start_ms"]),
                end_ms=int(w["end_ms"]),
            )
            for w in data.get("words", [])
        ]
        return cls(
            section_id=data["section_id"],
            text_hash=data["text_hash"],
            audio_path=data["audio_path"],
            duration_ms=int(data["duration_ms"]),
            words=words,
            sha256=data.get("sha256", ""),
        )


@dataclass
class VoiceoverPackage:
    voice_id: str
    speed: float
    total_duration_ms: int
    full_audio_path: str
    sections: dict[str, SectionAudioArtifact] = field(default_factory=dict)
    timeline_words: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "voice_id": self.voice_id,
            "speed": self.speed,
            "total_duration_ms": self.total_duration_ms,
            "full_audio_path": self.full_audio_path,
            "sections": {sid: art.to_dict() for sid, art in self.sections.items()},
            "timeline_words": self.timeline_words,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VoiceoverPackage:
        sections = {
            sid: SectionAudioArtifact.from_dict(sdata)
            for sid, sdata in data.get("sections", {}).items()
        }
        return cls(
            voice_id=data.get("voice_id", DEFAULT_ZH_VOICE),
            speed=float(data.get("speed", 1.0)),
            total_duration_ms=int(data.get("total_duration_ms", 0)),
            full_audio_path=data.get("full_audio_path", ""),
            sections=sections,
            timeline_words=data.get("timeline_words", []),
        )


def _compute_cache_key(text: str, voice: str, speed: float) -> str:
    raw = f"{text}|{voice}|{speed:.2f}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def probe_audio_duration_ms(path: Path | str) -> int:
    """使用 ffprobe 探针精准测量音频时长（毫秒）。"""
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return round(float(proc.stdout.strip()) * 1000)


def synthesize_section_piper(
    text: str,
    output_wav: Path,
    voice: str = DEFAULT_ZH_VOICE,
    speed: float = 1.0,
) -> Path:
    """调用本地 Piper 引擎合成单段音频。"""
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    voice_path = PIPER_VOICES_DIR / voice
    if not voice_path.exists():
        # 回退至 zh 默认
        voice_path = PIPER_VOICES_DIR / DEFAULT_ZH_VOICE

    raw_wav = output_wav.with_suffix(".raw.wav")

    cmd = [
        str(PIPER_BIN),
        "-m",
        str(voice_path),
        "-f",
        str(raw_wav),
        "--length_scale",
        str(round(1.0 / speed, 3)),
        "--sentence_silence",
        "0.2",
    ]

    proc = subprocess.run(
        cmd,
        input=text.encode("utf-8"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"Piper TTS synthesis failed (code {proc.returncode}): {err}")

    # 使用 ffmpeg 进行响度归一化并转成标准立体声 44100Hz
    norm_cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(raw_wav),
        "-af",
        "highpass=f=60,loudnorm=I=-16:TP=-1.5",
        "-ar",
        "44100",
        "-ac",
        "2",
        str(output_wav),
    ]
    norm_proc = subprocess.run(norm_cmd, capture_output=True, check=False)
    if norm_proc.returncode != 0:
        raise RuntimeError(f"FFmpeg audio postprocess failed: {norm_proc.stderr.decode('utf-8', errors='ignore')}")

    if raw_wav.exists():
        raw_wav.unlink(missing_ok=True)

    return output_wav


def align_audio_faster_whisper(
    audio_path: Path,
    expected_text: str = "",
    language: str = "zh",
) -> list[WordAlignmentItem]:
    """使用本地 faster-whisper 模型进行真实词级时间戳对齐。"""
    model = get_whisper_model()
    segments, _ = model.transcribe(
        str(audio_path),
        word_timestamps=True,
        language=language,
        vad_filter=True,
    )

    words: list[WordAlignmentItem] = []
    for seg in segments:
        if seg.words:
            for w in seg.words:
                cleaned = w.word.strip()
                if cleaned:
                    s_ms = round(w.start * 1000)
                    e_ms = round(w.end * 1000)
                    if e_ms <= s_ms:
                        e_ms = s_ms + 100
                    words.append(WordAlignmentItem(word=cleaned, start_ms=s_ms, end_ms=e_ms))

    # 如果 ASR 词表为空（静音或纯标点），按总时长均分段内字词
    if not words and expected_text.strip():
        dur_ms = probe_audio_duration_ms(audio_path)
        chars = [c for c in expected_text.strip() if c not in "，。！？；：、 \n"]
        if chars:
            step = dur_ms // len(chars)
            for idx, c in enumerate(chars):
                words.append(
                    WordAlignmentItem(
                        word=c,
                        start_ms=idx * step,
                        end_ms=min((idx + 1) * step, dur_ms),
                    )
                )

    return words


def build_section_audio(
    section: ScriptSection,
    out_dir: Path,
    voice: str = DEFAULT_ZH_VOICE,
    speed: float = 1.0,
) -> SectionAudioArtifact:
    """为单段脚本合成音频并提取词级对齐。"""
    key = _compute_cache_key(section.oral_text, voice, speed)
    wav_path = out_dir / f"{section.section_id}_{key[:10]}.wav"

    synthesize_section_piper(section.oral_text, wav_path, voice=voice, speed=speed)
    dur_ms = probe_audio_duration_ms(wav_path)
    words = align_audio_faster_whisper(wav_path, expected_text=section.oral_text)
    sha = hashlib.sha256(wav_path.read_bytes()).hexdigest()

    return SectionAudioArtifact(
        section_id=section.section_id,
        text_hash=key,
        audio_path=str(wav_path),
        duration_ms=dur_ms,
        words=words,
        sha256=sha,
    )


def build_voiceover_package(
    script: OralScript,
    out_dir: Path,
    voice: str = DEFAULT_ZH_VOICE,
    speed: float = 1.0,
    cached_package: VoiceoverPackage | None = None,
) -> VoiceoverPackage:
    """构建整篇口播稿配音包。

    智能增量重算：
    对比各分段缓存键，未发生变动的分段直接复用，受影响或新分段才重新合成。
    最终拼接为完整音轨并生成全时间轴词级时间戳。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sec_artifacts: dict[str, SectionAudioArtifact] = {}
    cached_secs = cached_package.sections if cached_package else {}

    reused_count = 0
    synthesized_count = 0

    for sec in script.sections:
        current_key = _compute_cache_key(sec.oral_text, voice, speed)
        old_art = cached_secs.get(sec.section_id)

        # 检查缓存是否可用且文件存在
        if old_art and old_art.text_hash == current_key and Path(old_art.audio_path).is_file():
            sec_artifacts[sec.section_id] = old_art
            reused_count += 1
        else:
            art = build_section_audio(sec, out_dir, voice=voice, speed=speed)
            sec_artifacts[sec.section_id] = art
            synthesized_count += 1

    logger.info(
        "Voiceover build: %d sections reused from cache, %d newly synthesized",
        reused_count,
        synthesized_count,
    )

    # 拼接全篇音频
    full_wav_path = out_dir / f"{script.script_id}_{script.version_id}_full.wav"
    concat_list_file = out_dir / f"concat_{script.script_id}_{script.version_id}.txt"

    lines: list[str] = []
    for sec in script.sections:
        art = sec_artifacts[sec.section_id]
        lines.append(f"file '{Path(art.audio_path).resolve()}'")
    concat_list_file.write_text("\n".join(lines), encoding="utf-8")

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_file),
            "-c",
            "copy",
            str(full_wav_path),
        ],
        capture_output=True,
        check=True,
    )
    concat_list_file.unlink(missing_ok=True)

    total_dur_ms = probe_audio_duration_ms(full_wav_path)

    # 计算全局时间轴词级时间戳
    timeline_words: list[dict[str, Any]] = []
    current_offset_ms = 0

    for sec in script.sections:
        art = sec_artifacts[sec.section_id]
        for w in art.words:
            timeline_words.append(
                {
                    "section_id": sec.section_id,
                    "word": w.word,
                    "start_ms": current_offset_ms + w.start_ms,
                    "end_ms": current_offset_ms + w.end_ms,
                }
            )
        current_offset_ms += art.duration_ms

    return VoiceoverPackage(
        voice_id=voice,
        speed=speed,
        total_duration_ms=total_dur_ms,
        full_audio_path=str(full_wav_path),
        sections=sec_artifacts,
        timeline_words=timeline_words,
    )
