"""默认配音合成:translated cues → edge-tts 目标语种音频(复用 audio provider)。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hevi.assembly.subtitle_align import Cue


async def synth_cues_edge_tts(*, cues: list[Cue], language: str, output_path: Path) -> Path:
    """cues → edge-tts(目标语种)WAV。edge_tts_synthesize 期望 script: list[Line](鸭子类型 .text/.speaker_id)。"""
    from obase.provider_registry import ProviderRegistry

    lines: list[Any] = [
        SimpleNamespace(text=c.text, speaker_id="host") for c in cues if c.text.strip()
    ]
    caller = ProviderRegistry.get().generic("audio", "edge_tts")
    await caller(script=lines, output_path=output_path, language=language)
    return output_path
