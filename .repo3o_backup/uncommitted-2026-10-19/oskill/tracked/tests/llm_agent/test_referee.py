"""Test referee parsing, clamping, verdict normalization."""

from unittest.mock import AsyncMock, patch

import pytest

from oskill.llm_agent.referee import referee


def _mock_result(content):
    return {
        "content": content,
        "input_tokens": 200,
        "output_tokens": 100,
        "cost_usd": 0.002,
        "model_id": "deepseek-chat",
        "elapsed_ms": 800,
        "seed": None,
        "prompt_hash_hex": "b" * 64,
        "raw_response": {},
    }


@pytest.mark.asyncio
async def test_referee_happy_long():
    content = '{"reasoning": "Bull case strong", "factor_value": 0.7, "confidence": 80, "verdict": "long"}'
    with patch(
        "oskill.llm_agent.referee.deepseek_call",
        new=AsyncMock(return_value=_mock_result(content)),
    ):
        result = await referee(
            symbol="BTC-USDT",
            bull_confidence=80,
            bull_reasons=["strong momentum"],
            bear_confidence=30,
            bear_reasons=["overbought"],
            classic_factor=0.5,
            api_key="test",
        )
    assert result["factor_value"] == 0.7
    assert result["verdict"] == "long"
    assert result["confidence"] == 80.0
    assert result["parse_failed"] is False


@pytest.mark.asyncio
async def test_referee_factor_clamp_overshoot():
    """factor_value > 1.0 → clamp to 1.0."""
    content = '{"factor_value": 5.0, "confidence": 90, "verdict": "long"}'
    with patch(
        "oskill.llm_agent.referee.deepseek_call",
        new=AsyncMock(return_value=_mock_result(content)),
    ):
        result = await referee(
            symbol="BTC",
            bull_confidence=80,
            bull_reasons=[],
            bear_confidence=20,
            bear_reasons=[],
            classic_factor=0.5,
            api_key="test",
        )
    assert result["factor_value"] == 1.0


@pytest.mark.asyncio
async def test_referee_factor_clamp_undershoot():
    content = '{"factor_value": -3.0, "confidence": 70, "verdict": "short"}'
    with patch(
        "oskill.llm_agent.referee.deepseek_call",
        new=AsyncMock(return_value=_mock_result(content)),
    ):
        result = await referee(
            symbol="BTC",
            bull_confidence=20,
            bull_reasons=[],
            bear_confidence=80,
            bear_reasons=[],
            classic_factor=-0.5,
            api_key="test",
        )
    assert result["factor_value"] == -1.0


@pytest.mark.asyncio
async def test_referee_parse_fail():
    with patch(
        "oskill.llm_agent.referee.deepseek_call",
        new=AsyncMock(return_value=_mock_result("I cannot decide.")),
    ):
        result = await referee(
            symbol="BTC",
            bull_confidence=50,
            bull_reasons=[],
            bear_confidence=50,
            bear_reasons=[],
            classic_factor=0.0,
            api_key="test",
        )
    assert result["factor_value"] == 0.0
    assert result["confidence"] == 50.0
    assert result["verdict"] == "neutral"
    assert result["parse_failed"] is True


@pytest.mark.asyncio
async def test_referee_invalid_verdict_normalized():
    content = '{"factor_value": 0.5, "confidence": 70, "verdict": "BULL"}'
    with patch(
        "oskill.llm_agent.referee.deepseek_call",
        new=AsyncMock(return_value=_mock_result(content)),
    ):
        result = await referee(
            symbol="BTC",
            bull_confidence=70,
            bull_reasons=[],
            bear_confidence=30,
            bear_reasons=[],
            classic_factor=0.3,
            api_key="test",
        )
    assert result["verdict"] == "neutral"


@pytest.mark.asyncio
async def test_referee_factor_string_input():
    """factor_value as string → coerced to float."""
    content = '{"factor_value": "0.4", "confidence": 70, "verdict": "long"}'
    with patch(
        "oskill.llm_agent.referee.deepseek_call",
        new=AsyncMock(return_value=_mock_result(content)),
    ):
        result = await referee(
            symbol="BTC",
            bull_confidence=70,
            bull_reasons=[],
            bear_confidence=30,
            bear_reasons=[],
            classic_factor=0.2,
            api_key="test",
        )
    assert result["factor_value"] == 0.4
