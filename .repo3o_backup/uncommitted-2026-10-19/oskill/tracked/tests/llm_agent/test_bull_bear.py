"""Mock DeepSeek, verify bull/bear agent parse + structure."""

from unittest.mock import AsyncMock, patch

import pytest

from oskill.llm_agent.bear_analyst import bear_analyst
from oskill.llm_agent.bull_analyst import bull_analyst


def _mock_call_result(content: str, in_tokens=100, out_tokens=50, model="deepseek-chat"):
    return {
        "content": content,
        "input_tokens": in_tokens,
        "output_tokens": out_tokens,
        "cost_usd": 0.001,
        "model_id": model,
        "elapsed_ms": 500,
        "seed": None,
        "prompt_hash_hex": "a" * 64,
        "raw_response": {},
    }


SAMPLE_BULL_JSON = """{
    "reasons": ["Strong momentum", "On-chain accumulation", "Funding flat"],
    "counter_arguments": ["Macro headwinds"],
    "confidence": 72
}"""


@pytest.mark.asyncio
async def test_bull_happy():
    with patch(
        "oskill.llm_agent.bull_analyst.deepseek_call",
        new=AsyncMock(return_value=_mock_call_result(SAMPLE_BULL_JSON)),
    ):
        result = await bull_analyst(
            symbol="BTC-USDT",
            current_price=60000,
            change_24h_pct=0.02,
            volume_24h_usd=1e9,
            realized_vol_30d=0.5,
            recent_bars=[],
            daily_closes=[58000, 59000, 60000],
            bocpd_factor=0.3,
            api_key="test",
        )

    assert result["role"] == "bull_analyst"
    assert result["confidence"] == 72.0
    assert "Strong momentum" in result["reasons"]
    assert result["parse_failed"] is False
    assert result["model_id"] == "deepseek-chat"


@pytest.mark.asyncio
async def test_bull_markdown_wrapped():
    content = f"Here is my analysis:\n```json\n{SAMPLE_BULL_JSON}\n```"
    with patch(
        "oskill.llm_agent.bull_analyst.deepseek_call",
        new=AsyncMock(return_value=_mock_call_result(content)),
    ):
        result = await bull_analyst(
            symbol="BTC-USDT",
            current_price=60000,
            change_24h_pct=0.02,
            volume_24h_usd=1e9,
            realized_vol_30d=0.5,
            recent_bars=[],
            daily_closes=[60000],
            bocpd_factor=0.3,
            api_key="test",
        )

    assert result["confidence"] == 72.0
    assert result["parse_failed"] is False


@pytest.mark.asyncio
async def test_bull_parse_fail_fallback():
    """Non-JSON response → confidence=50 fallback, parse_failed=True."""
    with patch(
        "oskill.llm_agent.bull_analyst.deepseek_call",
        new=AsyncMock(return_value=_mock_call_result("I cannot determine confidence.")),
    ):
        result = await bull_analyst(
            symbol="BTC-USDT",
            current_price=60000,
            change_24h_pct=0.02,
            volume_24h_usd=1e9,
            realized_vol_30d=0.5,
            recent_bars=[],
            daily_closes=[60000],
            bocpd_factor=0.3,
            api_key="test",
        )

    assert result["confidence"] == 50.0
    assert result["parse_failed"] is True
    assert result["reasons"] == []


@pytest.mark.asyncio
async def test_bull_confidence_clamp_overshoot():
    """Confidence > 100 → clamp to 100."""
    content = '{"confidence": 150, "reasons": []}'
    with patch(
        "oskill.llm_agent.bull_analyst.deepseek_call",
        new=AsyncMock(return_value=_mock_call_result(content)),
    ):
        result = await bull_analyst(
            symbol="BTC-USDT",
            current_price=60000,
            change_24h_pct=0.02,
            volume_24h_usd=1e9,
            realized_vol_30d=0.5,
            recent_bars=[],
            daily_closes=[60000],
            bocpd_factor=0.3,
            api_key="test",
        )

    assert result["confidence"] == 100.0


@pytest.mark.asyncio
async def test_bear_happy():
    bear_json = '{"reasons": ["Resistance rejected"], "confidence": 65}'
    with patch(
        "oskill.llm_agent.bear_analyst.deepseek_call",
        new=AsyncMock(return_value=_mock_call_result(bear_json)),
    ):
        result = await bear_analyst(
            symbol="BTC-USDT",
            current_price=60000,
            change_24h_pct=-0.02,
            volume_24h_usd=1e9,
            realized_vol_30d=0.5,
            recent_bars=[],
            daily_closes=[60000],
            bocpd_factor=-0.2,
            api_key="test",
        )

    assert result["role"] == "bear_analyst"
    assert result["confidence"] == 65.0
    assert "Resistance rejected" in result["reasons"]


@pytest.mark.asyncio
async def test_bull_llm_unavailable_propagates():
    """LLMUnavailable from client → re-raised."""
    from oskill.llm_client import LLMTimeout

    with patch(
        "oskill.llm_agent.bull_analyst.deepseek_call",
        new=AsyncMock(side_effect=LLMTimeout("test")),
    ):
        with pytest.raises(LLMTimeout):
            await bull_analyst(
                symbol="BTC-USDT",
                current_price=60000,
                change_24h_pct=0.02,
                volume_24h_usd=1e9,
                realized_vol_30d=0.5,
                recent_bars=[],
                daily_closes=[60000],
                bocpd_factor=0.3,
                api_key="test",
            )


@pytest.mark.asyncio
async def test_prompt_hash_matches_canonical():
    """Same input → same prompt messages passed to deepseek_call."""
    with patch(
        "oskill.llm_agent.bull_analyst.deepseek_call",
        new=AsyncMock(return_value=_mock_call_result(SAMPLE_BULL_JSON)),
    ) as mock_call:
        kwargs = dict(
            symbol="BTC-USDT",
            current_price=60000,
            change_24h_pct=0.02,
            volume_24h_usd=1e9,
            realized_vol_30d=0.5,
            recent_bars=[],
            daily_closes=[60000],
            bocpd_factor=0.3,
            api_key="test",
        )
        await bull_analyst(**kwargs)
        await bull_analyst(**kwargs)

    call1_msgs = mock_call.call_args_list[0].kwargs["messages"]
    call2_msgs = mock_call.call_args_list[1].kwargs["messages"]
    assert call1_msgs == call2_msgs
