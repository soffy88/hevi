"""Referee agent: weigh bull + bear + classic factor → final factor value."""

from __future__ import annotations

import json
from typing import Any

import structlog

from oskill.llm_agent._parsing import coerce_confidence, extract_json
from oskill.llm_agent._prompts import PROMPT_VERSION, SYSTEM_REFEREE, USER_TEMPLATE_REFEREE
from oskill.llm_client import deepseek_call

log = structlog.get_logger(__name__)


def _clamp_factor(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    return max(-1.0, min(1.0, x))


def _normalize_verdict(v: Any) -> str:
    if not isinstance(v, str):
        return "neutral"
    vs = v.strip().lower()
    if vs in ("long", "short", "neutral"):
        return vs
    return "neutral"


async def referee(
    *,
    symbol: str,
    bull_confidence: float,
    bull_reasons: list[str],
    bear_confidence: float,
    bear_reasons: list[str],
    classic_factor: float,
    api_key: str,
    api_base: str = "https://api.deepseek.com/v1",
    model: str = "deepseek-chat",
) -> dict:
    """Run referee LLM call.

    Returns
    -------
    dict
        {
            "role": "referee",
            "prompt_version": str,
            "raw_content": str,
            "parsed": dict | None,
            "factor_value": float,    # -1.0..1.0, 0.0 on parse fail
            "confidence": float,      # 0-100, 50.0 on parse fail
            "verdict": str,           # "long"|"short"|"neutral"
            "reasoning": str,         # "" on parse fail
            "input_tokens": int,
            "output_tokens": int,
            "cost_usd": float,
            "model_id": str,
            "elapsed_ms": int,
            "prompt_hash_hex": str,
            "parse_failed": bool,
        }

    Raises
    ------
    LLMUnavailable subclass — propagated from client.
    """
    user_msg = USER_TEMPLATE_REFEREE.format(
        symbol=symbol,
        bull_confidence=bull_confidence,
        bull_reasons_json=json.dumps(bull_reasons, ensure_ascii=False),
        bear_confidence=bear_confidence,
        bear_reasons_json=json.dumps(bear_reasons, ensure_ascii=False),
        classic_factor=classic_factor,
    )

    messages = [
        {"role": "system", "content": SYSTEM_REFEREE},
        {"role": "user", "content": user_msg},
    ]

    api_result = await deepseek_call(
        messages=messages,
        model=model,
        temperature=0.0,
        max_tokens=600,
        timeout_sec=30.0,
        api_key=api_key,
        api_base=api_base,
    )

    parsed = extract_json(api_result["content"])
    parse_failed = parsed is None

    factor_value = _clamp_factor(parsed.get("factor_value") if parsed else None, default=0.0)
    confidence = coerce_confidence(parsed, default=50.0)
    verdict = _normalize_verdict(parsed.get("verdict") if parsed else "neutral")
    reasoning = parsed.get("reasoning", "") if parsed else ""

    if not parse_failed:
        if verdict == "long" and factor_value < 0:
            log.warning("referee_factor_verdict_mismatch", verdict=verdict, factor=factor_value)
        if verdict == "short" and factor_value > 0:
            log.warning("referee_factor_verdict_mismatch", verdict=verdict, factor=factor_value)

    return {
        "role": "referee",
        "prompt_version": PROMPT_VERSION,
        "raw_content": api_result["content"],
        "parsed": parsed,
        "factor_value": factor_value,
        "confidence": confidence,
        "verdict": verdict,
        "reasoning": reasoning if isinstance(reasoning, str) else "",
        "input_tokens": api_result["input_tokens"],
        "output_tokens": api_result["output_tokens"],
        "cost_usd": api_result["cost_usd"],
        "model_id": api_result["model_id"],
        "elapsed_ms": api_result["elapsed_ms"],
        "prompt_hash_hex": api_result["prompt_hash_hex"],
        "parse_failed": parse_failed,
    }
