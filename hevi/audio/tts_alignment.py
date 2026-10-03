"""G0.2-B TTS Alignment Artifact spike — minimal wrapper, no provider change.

不再丢弃 `oprim.edge_tts_word_boundary` 的词级时间戳:合成单段文本,
返回 (音频路径, AudioAlignment)。时间一律整数毫秒,禁浮点秒持久化。
短语级:单次合成 = 一个 phrase(phrase_id=audio_id);多行拼接的分行
phrase 是后续工作(见 report)。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class WordTiming:
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class PhraseTiming:
    phrase_id: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class AudioAlignment:
    audio_id: str
    duration_ms: int
    words: tuple[WordTiming, ...] = field(default_factory=tuple)
    phrases: tuple[PhraseTiming, ...] = field(default_factory=tuple)


class AlignmentUnavailable(RuntimeError):
    """provider 不支持/合成失败:调用方必须记 receipt,不得用估计值冒充。"""


def _to_ms(seconds: float) -> int:
    return round(seconds * 1000)


def probe_duration_ms(audio_path: Path) -> int:
    """ffprobe 读音频时长。失败抛 AlignmentUnavailable(不猜)。

    mp3 的 Xing 头时长估计含填充/尾静,先解码为 wav 再探(仅测量手段,
    不改变 artifact 格式)。"""
    import tempfile

    try:
        with tempfile.TemporaryDirectory(prefix="hevi_tts_probe_") as td:
            wav = Path(td) / "probe.wav"
            dec = subprocess.run(
                ["ffmpeg", "-v", "error", "-y", "-i", str(audio_path),
                 "-ar", "44100", "-ac", "1", str(wav)],
                capture_output=True, text=True, timeout=120, check=False,
            )
            target = wav if dec.returncode == 0 and wav.exists() else audio_path
            proc = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(target)],
                capture_output=True, text=True, timeout=60, check=False,
            )
            return _to_ms(float(proc.stdout.strip()))
    except Exception as exc:
        raise AlignmentUnavailable(f"cannot probe duration of {audio_path}: {exc}") from exc


async def synthesize_with_alignment(
    *,
    text: str,
    voice: str,
    audio_id: str = "",
    output_path: Path | None = None,
) -> tuple[Path, AudioAlignment]:
    """真实合成 + 落盘对齐。audio_id 由调用方绑定(如 tts:{unit_id}#r{revision})。

    失败抛 AlignmentUnavailable,不返回估计值。
    """
    from oprim import edge_tts_word_boundary

    if not text or not text.strip():
        raise AlignmentUnavailable("empty text")
    try:
        result = await edge_tts_word_boundary(text, voice, output_path=output_path)
    except Exception as exc:
        raise AlignmentUnavailable(f"tts synthesis failed: {exc}") from exc

    audio_path = Path(result["audio_path"])
    words = tuple(
        WordTiming(str(w["text"]), _to_ms(float(w["start"])), _to_ms(float(w["end"])))
        for w in result.get("words", [])
    )
    aid = audio_id or audio_path.stem
    duration_ms = probe_duration_ms(audio_path)
    phrases = (
        (PhraseTiming(aid, words[0].start_ms, words[-1].end_ms) if words else PhraseTiming(aid, 0, duration_ms)),
    )
    return audio_path, AudioAlignment(aid, duration_ms, words, phrases)


def alignment_to_json(alignment: AudioAlignment) -> str:
    return json.dumps(
        {
            "audio_id": alignment.audio_id,
            "duration_ms": alignment.duration_ms,
            "words": [{"token": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms} for w in alignment.words],
            "phrases": [
                {"phrase_id": p.phrase_id, "start_ms": p.start_ms, "end_ms": p.end_ms}
                for p in alignment.phrases
            ],
        },
        ensure_ascii=False,
    )


def dialogue_end_ms(alignment: AudioAlignment) -> int:
    """Dialogue End Event = last word end (not audio duration; see G0.2-B finding)."""
    return alignment.words[-1].end_ms if alignment.words else alignment.duration_ms


def write_alignment_sidecar(audio_path: Path, alignment: AudioAlignment) -> Path:
    """A4:落盘 <audio>.alignment.json。写失败不阻断合成(对齐缺失=不可评估,非失败)。"""
    sidecar = audio_path.with_suffix(audio_path.suffix + ".alignment.json")
    try:
        sidecar.write_text(alignment_to_json(alignment) + "\n", encoding="utf-8")
    except OSError:
        return sidecar
    return sidecar


def load_alignment_sidecar(audio_path: Path) -> AudioAlignment | None:
    sidecar = audio_path.with_suffix(audio_path.suffix + ".alignment.json")
    if not sidecar.is_file():
        return None
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    words = tuple(WordTiming(str(w["token"]), int(w["start_ms"]), int(w["end_ms"]))
                  for w in payload.get("words", []))
    phrases = tuple(PhraseTiming(str(p["phrase_id"]), int(p["start_ms"]), int(p["end_ms"]))
                    for p in payload.get("phrases", []))
    return AudioAlignment(str(payload.get("audio_id", "")), int(payload.get("duration_ms", 0)),
                          words, phrases)
