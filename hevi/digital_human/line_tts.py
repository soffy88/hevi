"""One-line TTS for Echo talking-face (director dialogue, etc.)."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace


class LineTtsError(RuntimeError):
    """Dialogue TTS failed."""


def _provider() -> str:
    return (
        os.getenv("HEVI_TTS_FORMAL_PROVIDER")
        or os.getenv("HEVI_EXPLAINER_TTS_PROVIDER")
        or "voicebox"
    ).strip().lower()


async def synthesize_line(text: str, output_path: Path) -> Path:
    """Synthesize one utterance to wav/mp3. Provider follows explainer TTS env."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    spoken = (text or "").strip()
    if not spoken:
        raise LineTtsError("空台词")
    provider = _provider()
    try:
        if provider == "voicebox":
            from hevi.explainer.voicebox_client import synthesize

            await synthesize(spoken, output_path)
        elif provider == "cosyvoice":
            from hevi.audio.cosyvoice_service import cosyvoice_synthesize

            await cosyvoice_synthesize(
                script=[SimpleNamespace(text=spoken)],
                output_path=output_path,
            )
        else:
            from oprim import edge_tts_word_boundary

            await edge_tts_word_boundary(  # type: ignore[no-untyped-call]
                spoken,
                voice="zh-CN-YunxiNeural",
                rate="-10%",
                output_path=output_path,
            )
    except Exception as exc:
        raise LineTtsError(f"{provider} 合成失败: {exc}") from exc
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise LineTtsError(f"TTS 产物为空: {output_path}")
    return output_path
