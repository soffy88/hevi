"""oskill：说（TTS 逐句合成 wav）。"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from hevi.live_host.schemas import EngineConfig, StageTiming, Utterance

logger = logging.getLogger(__name__)


def skill_speak(
    utterances: list[Utterance],
    tts,
    cfg: EngineConfig,
    timing: StageTiming,
    workdir: Path,
) -> list[Utterance]:
    """逐句合成 wav，写入 workdir；返回带 audio_path / tts_seconds 的 utterances。"""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    t_total = 0.0
    for u in utterances:
        t0 = time.perf_counter()
        out_path = workdir / f"utt_{u.index:02d}.wav"
        try:
            tts.synthesize(u.text, out_path)
        except Exception as exc:  # pragma: no cover - TTS 失败保留文本
            logger.error("TTS 失败: %s → %s", u.text, exc)
            u.audio_path = None
            continue
        u.audio_path = out_path
        u.tts_seconds = time.perf_counter() - t0
        t_total += u.tts_seconds
    timing.tts = t_total
    logger.info("TTS: %d 句合成完成（总 %.2fs）", len(utterances), t_total)
    return utterances
