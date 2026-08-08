"""默认配音合成:translated cues → edge-tts 目标语种音频(复用 audio provider)。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hevi.assembly.subtitle_align import Cue


async def synth_cues_edge_tts(*, cues: list[Cue], language: str, output_path: Path) -> Path:
    """cues → edge-tts(目标语种)WAV。edge_tts_synthesize 期望 script: list[Line](鸭子类型 .text/.speaker_id)。

    情感感知配音:cue.emotion(默认 neutral)驱动 rate/pitch/volume 注入——
    未标注的台词自动按关键词启发式分类(见 hevi.dub.emotion)。"""
    from obase.provider_registry import ProviderRegistry

    from hevi.dub.emotion import detect_emotion, emotion_tts_params

    lines: list[Any] = []
    for c in cues:
        if not c.text.strip():
            continue
        # neutral(未标注)一律按关键词自动情感分类;显式非 neutral 保持
        emotion = c.emotion if c.emotion != "neutral" else detect_emotion(c.text)
        prof = emotion_tts_params(emotion)
        lines.append(
            SimpleNamespace(
                text=c.text,
                speaker_id="host",
                rate=prof["rate"],
                pitch=prof["pitch"],
                volume=prof["volume"],
            )
        )
    caller = ProviderRegistry.get().generic("audio", "edge_tts")
    await caller(script=lines, output_path=output_path, language=language)
    return output_path
