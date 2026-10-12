"""oskill：想（LLM 生成回复，逐句产出并按 max_reply_chars 截断）。"""

from __future__ import annotations

import logging
import time

from hevi.live_host.oprim.llm_ollama import OllamaLLM
from hevi.live_host.schemas import EngineConfig, TurnOutput, Utterance

logger = logging.getLogger(__name__)

_SENT_PUNCT = "。！？!?；;．·\n"


def _split_sentences(text: str) -> list[str]:
    out, buf = [], ""
    for ch in text:
        buf += ch
        if ch in _SENT_PUNCT and buf.strip():
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


def skill_think(
    question: str,
    llm: OllamaLLM,
    out: TurnOutput,
    cfg: EngineConfig,
) -> TurnOutput:
    """流式调用 LLM，逐句累加，累计字符超 max_reply_chars 即停。填充 out.reply_text/utterances/timing。"""
    if not question.strip():
        out.reply_text = ""
        return out

    t0 = time.perf_counter()
    first_ts = None
    accumulated = ""
    for sentence in llm.stream_reply(question):
        if first_ts is None:
            first_ts = time.perf_counter() - t0
        accumulated += sentence
        out.reply_text = accumulated
        if len(accumulated) >= cfg.max_reply_chars:
            break
    out.timing.llm_first_token = first_ts or 0.0
    out.timing.llm_total = time.perf_counter() - t0

    sentences = _split_sentences(accumulated)
    out.utterances = [Utterance(index=i, text=s) for i, s in enumerate(sentences)]
    logger.info(
        "LLM: %d 句（首 token %.2fs, 总 %.2fs）",
        len(out.utterances),
        out.timing.llm_first_token,
        out.timing.llm_total,
    )
    return out
