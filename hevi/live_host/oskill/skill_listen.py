"""oskill：听（VAD + STT）。"""

from __future__ import annotations

import logging
import time

import soundfile as sf

from hevi.live_host.oprim.silero_vad import SileroVAD
from hevi.live_host.oprim.stt_whisper import WhisperSTT
from hevi.live_host.schemas import TurnInput, TurnOutput

logger = logging.getLogger(__name__)


def skill_listen(
    turn: TurnInput,
    stt: WhisperSTT,
    vad: SileroVAD | None,
    out: TurnOutput,
) -> TurnOutput:
    """把音频输入转写为文本；纯文本输入直接透传。填充 out.transcript/question/timing。"""
    if turn.text is not None:
        out.transcript = turn.text
        out.question = turn.text
        return out

    if turn.audio_path is None:
        return out

    # VAD
    t0 = time.perf_counter()
    samples, sr = sf.read(str(turn.audio_path), dtype="float32")
    if sr != 16000:
        import scipy.signal as sig

        samples = sig.resample(samples, int(len(samples) * 16000 / sr))
    if vad is not None:
        vad.reset()
        has = vad.has_speech(samples)
        out.timing.vad = time.perf_counter() - t0
        if not has:
            logger.info("VAD: 无有效语音，跳过 STT")
            out.question = ""
            return out
    else:
        out.timing.vad = time.perf_counter() - t0

    # STT
    t1 = time.perf_counter()
    out.transcript = stt.transcribe(turn.audio_path)
    out.question = out.transcript
    out.timing.stt = time.perf_counter() - t1
    logger.info("STT: %s（%.2fs）", out.transcript, out.timing.stt)
    return out
