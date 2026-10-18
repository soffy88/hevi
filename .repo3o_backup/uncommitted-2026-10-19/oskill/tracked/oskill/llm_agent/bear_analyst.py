"""Bear-biased analyst — single LLM call (mirrors bull_analyst, SYSTEM_BEAR)."""

from __future__ import annotations

import structlog

from oskill.llm_agent._parsing import coerce_confidence, extract_json
from oskill.llm_agent._prompts import PROMPT_VERSION, SYSTEM_BEAR, USER_TEMPLATE_BULL_BEAR
from oskill.llm_agent.bull_analyst import _format_daily_close, _format_ohlcv_table
from oskill.llm_client import deepseek_call

log = structlog.get_logger(__name__)


async def bear_analyst(
    *,
    symbol: str,
    current_price: float,
    change_24h_pct: float,
    volume_24h_usd: float,
    realized_vol_30d: float,
    recent_bars: list[dict],
    daily_closes: list[float],
    bocpd_factor: float,
    api_key: str,
    api_base: str = "https://api.deepseek.com/v1",
    model: str = "deepseek-chat",
) -> dict:
    """Run bear analyst LLM call.

    Returns
    -------
    dict
        {
            "role": "bear_analyst",
            "prompt_version": str,
            "raw_content": str,
            "parsed": dict | None,
            "confidence": float,      # 50.0 fallback on parse fail
            "reasons": list[str],
            "counter_arguments": list[str],
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
    LLMUnavailable / LLMRateLimit / LLMAPIError / LLMTimeout
    """
    user_msg = USER_TEMPLATE_BULL_BEAR.format(
        symbol=symbol,
        current_price=current_price,
        change_24h_pct=change_24h_pct,
        volume_24h_usd=volume_24h_usd,
        realized_vol_30d=realized_vol_30d,
        ohlcv_table=_format_ohlcv_table(recent_bars, n=24),
        daily_close_table=_format_daily_close(daily_closes, n=7),
        bocpd_factor=bocpd_factor,
    )

    messages = [
        {"role": "system", "content": SYSTEM_BEAR},
        {"role": "user", "content": user_msg},
    ]

    api_result = await deepseek_call(
        messages=messages,
        model=model,
        temperature=0.0,
        max_tokens=800,
        timeout_sec=30.0,
        api_key=api_key,
        api_base=api_base,
    )

    parsed = extract_json(api_result["content"])
    parse_failed = parsed is None

    confidence = coerce_confidence(parsed, default=50.0)
    reasons = parsed.get("reasons", []) if parsed else []
    counter_args = parsed.get("counter_arguments", []) if parsed else []

    if parse_failed:
        log.warning(
            "bear_analyst_parse_failed",
            symbol=symbol,
            content_preview=api_result["content"][:200],
        )

    return {
        "role": "bear_analyst",
        "prompt_version": PROMPT_VERSION,
        "raw_content": api_result["content"],
        "parsed": parsed,
        "confidence": confidence,
        "reasons": list(reasons) if isinstance(reasons, list) else [],
        "counter_arguments": list(counter_args) if isinstance(counter_args, list) else [],
        "input_tokens": api_result["input_tokens"],
        "output_tokens": api_result["output_tokens"],
        "cost_usd": api_result["cost_usd"],
        "model_id": api_result["model_id"],
        "elapsed_ms": api_result["elapsed_ms"],
        "prompt_hash_hex": api_result["prompt_hash_hex"],
        "parse_failed": parse_failed,
    }
