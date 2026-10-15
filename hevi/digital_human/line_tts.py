"""One-line TTS for Echo talking-face (director dialogue, etc.)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from types import SimpleNamespace

logger = logging.getLogger(__name__)


class LineTtsError(RuntimeError):
    """Dialogue TTS failed."""


def _provider() -> str:
    return (
        (
            os.getenv("HEVI_TTS_FORMAL_PROVIDER")
            or os.getenv("HEVI_EXPLAINER_TTS_PROVIDER")
            or "lux_tts"
        )
        .strip()
        .lower()
    )


async def synthesize_line(text: str, output_path: Path) -> Path:
    """Synthesize one utterance to wav/mp3. Provider follows explainer TTS env."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    spoken = (text or "").strip()
    if not spoken:
        raise LineTtsError("空台词")
    requested = _provider()
    actual = requested
    try:
        if requested == "voicebox":
            from hevi.explainer.voicebox_client import synthesize

            await synthesize(spoken, output_path)
        elif requested == "cosyvoice":
            from hevi.audio.cosyvoice_service import cosyvoice_synthesize

            await cosyvoice_synthesize(
                script=[SimpleNamespace(text=spoken)],
                output_path=output_path,
            )
        elif requested in {"lux", "lux_tts", "luxtts"}:
            from hevi.audio.audio_router import _synthesize_formal

            envelope = await _synthesize_formal(
                text=spoken,
                output_path=output_path,
                voice="zh-CN-XiaoxiaoNeural",
                instruct="gentle, warm, clear dialogue for children aged 2-6",
            )
            output_path = Path(envelope["path"])
            actual = str(envelope.get("actual_provider") or requested)
            if actual != requested:
                logger.warning(
                    "line_tts_identity %s",
                    {
                        "requested_provider": requested,
                        "actual_provider": actual,
                        "substituted": True,
                        "fallback_reason": envelope.get("fallback_reason"),
                    },
                )
        else:
            from oprim import edge_tts_word_boundary

            actual = "edge_tts"
            await edge_tts_word_boundary(
                spoken,
                voice="zh-CN-YunxiNeural",
                rate="-10%",
                output_path=output_path,
            )
    except Exception as exc:
        raise LineTtsError(f"{requested} 合成失败: {exc}") from exc
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise LineTtsError(f"TTS 产物为空: {output_path}")
    if actual != requested:
        logger.info(
            "line_tts_identity %s",
            {
                "requested_provider": requested,
                "actual_provider": actual,
                "substituted": True,
                "fallback_reason": "unmatched_line_tts_provider",
            },
        )
    return output_path
