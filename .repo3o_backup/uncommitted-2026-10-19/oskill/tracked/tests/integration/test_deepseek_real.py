"""Real DeepSeek API integration test.

Skipped automatically if DEEPSEEK_TEST_API_KEY is not set in environment.
Costs $0.001-0.01 per run. Run manually, not in CI.

Usage:
    DEEPSEEK_TEST_API_KEY=sk-... pytest tests/integration/test_deepseek_real.py -v -s
"""

from __future__ import annotations

import os

import pytest

from oskill.llm_client.deepseek import call


@pytest.mark.skipif(
    not os.environ.get("DEEPSEEK_TEST_API_KEY"),
    reason="DEEPSEEK_TEST_API_KEY not set — L14-2 deferred until API key available",
)
@pytest.mark.asyncio
async def test_real_simple_call():
    """Send simple message, verify response shape and cost sanity."""
    api_key = os.environ["DEEPSEEK_TEST_API_KEY"]

    result = await call(
        messages=[
            {"role": "system", "content": "You are a concise assistant."},
            {"role": "user", "content": "Reply with just the number 42."},
        ],
        api_key=api_key,
        max_tokens=10,
        timeout_sec=15.0,
    )

    assert "42" in result["content"]
    assert result["input_tokens"] > 0
    assert result["output_tokens"] > 0
    assert result["cost_usd"] > 0
    assert result["cost_usd"] < 0.01  # short prompt, sanity cap
    assert result["model_id"]
    assert result["elapsed_ms"] > 0
    assert len(result["prompt_hash_hex"]) == 64

    print("\nReal API result:")
    print(f"  content:      {result['content']!r}")
    print(f"  tokens in/out: {result['input_tokens']}/{result['output_tokens']}")
    print(f"  cost:          ${result['cost_usd']:.6f}")
    print(f"  elapsed:       {result['elapsed_ms']}ms")
    print(f"  model_id:      {result['model_id']}")
