"""Unit tests for oskill.llm_client.deepseek — mocked HTTP, no real API calls."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from oskill.llm_client.deepseek import call
from oskill.llm_client.exceptions import (
    LLMAPIError,
    LLMRateLimit,
    LLMTimeout,
)

# ── mock helpers ──────────────────────────────────────────────────────────────


def _mock_session(status: int, *, json_data: dict | None = None, text: str = ""):
    """Build a patched aiohttp.ClientSession that returns a fixed response."""
    mock_resp = AsyncMock()
    mock_resp.status = status
    mock_resp.json = AsyncMock(return_value=json_data)
    mock_resp.text = AsyncMock(return_value=text)

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_cm)

    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=False)

    return patch("aiohttp.ClientSession", return_value=mock_session_cm)


_GOOD_RESPONSE = {
    "id": "test-id",
    "model": "deepseek-chat",
    "choices": [{"message": {"role": "assistant", "content": "Hello!"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
}

_REASONER_RESPONSE = {
    "id": "test-id-r",
    "model": "deepseek-reasoner",
    "choices": [
        {"message": {"role": "assistant", "content": "thinking..."}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
}


# ── test cases ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_happy_path():
    """Mock 200 response → parses content, tokens, cost, metadata."""
    with _mock_session(200, json_data=_GOOD_RESPONSE):
        result = await call(
            messages=[{"role": "user", "content": "Hi"}],
            api_key="sk-test",
            model="deepseek-chat",
        )

    assert result["content"] == "Hello!"
    assert result["input_tokens"] == 100
    assert result["output_tokens"] == 20
    # Cost: 100/1000 * 0.00027 + 20/1000 * 0.0011 = 0.000027 + 0.000022 = 0.000049
    assert abs(result["cost_usd"] - 0.000049) < 1e-9
    assert result["model_id"] == "deepseek-chat"
    assert result["seed"] is None
    assert result["prompt_hash_hex"] is not None
    assert len(result["prompt_hash_hex"]) == 64  # sha256 hex


@pytest.mark.asyncio
async def test_prompt_hash_deterministic():
    """Same messages always produce the same prompt_hash_hex."""
    msgs = [{"role": "user", "content": "Hi"}]
    with _mock_session(200, json_data=_GOOD_RESPONSE):
        r1 = await call(messages=msgs, api_key="sk-test")
    with _mock_session(200, json_data=_GOOD_RESPONSE):
        r2 = await call(messages=msgs, api_key="sk-test")

    assert r1["prompt_hash_hex"] == r2["prompt_hash_hex"]


@pytest.mark.asyncio
async def test_429_rate_limit():
    """HTTP 429 → LLMRateLimit, not retried."""
    with _mock_session(429, text="rate limit exceeded"):
        with pytest.raises(LLMRateLimit):
            await call(
                messages=[{"role": "user", "content": "Hi"}],
                api_key="sk-test",
                retries=2,  # retries param should be ignored for 429
            )


@pytest.mark.asyncio
async def test_500_error():
    """HTTP 5xx → LLMAPIError."""
    with _mock_session(500, text="internal server error"):
        with pytest.raises(LLMAPIError):
            await call(messages=[{"role": "user", "content": "Hi"}], api_key="sk-test")


@pytest.mark.asyncio
async def test_400_error():
    """HTTP 4xx (not 429) → LLMAPIError."""
    with _mock_session(400, text="bad request"):
        with pytest.raises(LLMAPIError):
            await call(messages=[{"role": "user", "content": "Hi"}], api_key="sk-test")


@pytest.mark.asyncio
async def test_timeout_raises_llm_timeout():
    """asyncio.TimeoutError → LLMTimeout after retries exhausted."""
    mock_resp_cm = AsyncMock()
    mock_resp_cm.__aenter__ = AsyncMock(side_effect=TimeoutError("timed out"))
    mock_resp_cm.__aexit__ = AsyncMock(return_value=False)

    mock_session = AsyncMock()
    mock_session.post = MagicMock(return_value=mock_resp_cm)

    mock_session_cm = AsyncMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=False)

    with patch("aiohttp.ClientSession", return_value=mock_session_cm):
        with patch("asyncio.sleep", new_callable=AsyncMock):  # skip backoff delay
            with pytest.raises(LLMTimeout):
                await call(
                    messages=[{"role": "user", "content": "Hi"}],
                    api_key="sk-test",
                    retries=1,
                    timeout_sec=1.0,
                )


@pytest.mark.asyncio
async def test_missing_api_key_raises_value_error():
    """Empty api_key raises ValueError immediately, no HTTP call."""
    with pytest.raises(ValueError, match="api_key"):
        await call(messages=[{"role": "user", "content": "Hi"}], api_key="")


@pytest.mark.asyncio
async def test_malformed_response_raises_llm_api_error():
    """200 response missing 'usage' → LLMAPIError malformed."""
    bad = {"choices": [{"message": {"content": "ok"}}]}  # missing usage

    with _mock_session(200, json_data=bad):
        with pytest.raises(LLMAPIError, match="malformed"):
            await call(messages=[{"role": "user", "content": "Hi"}], api_key="sk-test")


@pytest.mark.asyncio
async def test_reasoner_model_cost():
    """deepseek-reasoner uses higher price tier."""
    with _mock_session(200, json_data=_REASONER_RESPONSE):
        result = await call(
            messages=[{"role": "user", "content": "Hi"}],
            api_key="sk-test",
            model="deepseek-reasoner",
        )

    # Cost: 1000/1000 * 0.00055 + 500/1000 * 0.0022 = 0.00055 + 0.0011 = 0.00165
    assert abs(result["cost_usd"] - 0.00165) < 1e-9
    assert result["content"] == "thinking..."


@pytest.mark.asyncio
async def test_raw_response_included():
    """raw_response contains the full API payload for audit."""
    with _mock_session(200, json_data=_GOOD_RESPONSE):
        result = await call(
            messages=[{"role": "user", "content": "Hi"}],
            api_key="sk-test",
        )

    assert result["raw_response"] == _GOOD_RESPONSE
    assert "choices" in result["raw_response"]
    assert "usage" in result["raw_response"]
