"""DeepSeek Chat Completion API client.

OpenAI-compatible POST /v1/chat/completions, parses standard response.
Used by oskill.llm_agent.* (Phase 3 P15) and ultimately Helivex strategies.

Reference: https://api-docs.deepseek.com/api/create-chat-completion
"""

from __future__ import annotations

import asyncio
import json
import time

import aiohttp
from oprim.crypto import sha256_hash
from oprim.serialization import canonical_json

from oskill.llm_client.exceptions import (
    LLMAPIError,
    LLMRateLimit,
    LLMTimeout,
    LLMUnavailable,
)

# Cost per 1k tokens (USD), as of 2026-05.
# Update when DeepSeek pricing changes.
_COST_PER_1K: dict[str, tuple[float, float]] = {
    "deepseek-chat": (0.00027, 0.0011),  # deepseek-v3 standard
    "deepseek-reasoner": (0.00055, 0.0022),  # deepseek-r1 standard
    "deepseek-v3": (0.00027, 0.0011),  # alias
    "deepseek-r1": (0.00055, 0.0022),  # alias
}


async def call(
    *,
    messages: list[dict],
    model: str = "deepseek-chat",
    temperature: float = 0.0,
    max_tokens: int = 1500,
    timeout_sec: float = 30.0,
    api_key: str,
    api_base: str = "https://api.deepseek.com/v1",
    retries: int = 1,
) -> dict:
    """Call DeepSeek Chat Completion API.

    Parameters
    ----------
    messages : list of {"role": "system|user|assistant", "content": str}
    model : DeepSeek model id (default deepseek-chat = deepseek-v3)
    temperature : 0.0 for deterministic-as-possible
    max_tokens : output token cap
    timeout_sec : total request timeout
    api_key : DeepSeek API key (caller must pass — no env default)
    api_base : API base URL
    retries : auto-retry count on LLMTimeout/LLMUnavailable (default 1 → 2 attempts total)

    Returns
    -------
    dict
        {
            "content": str,            # LLM text response
            "input_tokens": int,
            "output_tokens": int,
            "cost_usd": float,
            "model_id": str,           # actual model returned by API
            "elapsed_ms": int,
            "seed": None,              # DeepSeek does not expose seed
            "prompt_hash_hex": str,    # sha256(canonical_json(messages)) for audit
            "raw_response": dict,      # full API response
        }

    Raises
    ------
    LLMTimeout : aiohttp timeout (after all retries exhausted)
    LLMRateLimit : HTTP 429 (not retried)
    LLMAPIError : non-2xx other than 429, or malformed response body
    LLMUnavailable : network / DNS / unknown transport error
    ValueError : api_key is empty
    """
    if not api_key:
        raise ValueError("api_key required, no default")

    # Canonical prompt hash for audit — stable across Python dict orderings
    prompt_canonical = canonical_json(messages)
    prompt_bytes = (
        prompt_canonical.encode() if isinstance(prompt_canonical, str) else prompt_canonical
    )
    raw_hash = sha256_hash(prompt_bytes)
    prompt_hash = raw_hash.hex() if isinstance(raw_hash, bytes) else raw_hash

    body = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        start = time.monotonic()
        try:
            return await _do_call(
                api_base=api_base,
                api_key=api_key,
                body=body,
                timeout_sec=timeout_sec,
                prompt_hash=prompt_hash,
                start=start,
                requested_model=model,
            )
        except LLMRateLimit:
            raise  # never retry 429
        except LLMAPIError:
            raise  # never retry 4xx/5xx
        except (LLMTimeout, LLMUnavailable) as exc:
            last_exc = exc
            if attempt < retries:
                await asyncio.sleep(2**attempt)  # exponential backoff
                continue
            raise

    assert last_exc is not None
    raise last_exc


async def _do_call(
    *,
    api_base: str,
    api_key: str,
    body: dict,
    timeout_sec: float,
    prompt_hash: str,
    start: float,
    requested_model: str,
) -> dict:
    url = f"{api_base}/chat/completions"
    timeout = aiohttp.ClientTimeout(total=timeout_sec)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                json=body,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            ) as resp:
                if resp.status == 429:
                    txt = await resp.text()
                    raise LLMRateLimit(f"deepseek 429: {txt[:200]}")
                if resp.status >= 500:
                    txt = await resp.text()
                    raise LLMAPIError(f"deepseek {resp.status}: {txt[:200]}")
                if resp.status != 200:
                    txt = await resp.text()
                    raise LLMAPIError(f"deepseek {resp.status}: {txt[:200]}")

                try:
                    data = await resp.json(content_type=None)
                except (aiohttp.ContentTypeError, json.JSONDecodeError) as exc:
                    raise LLMAPIError(f"deepseek response not JSON: {exc}") from exc

    except TimeoutError as exc:
        raise LLMTimeout(f"deepseek timeout after {timeout_sec}s") from exc
    except aiohttp.ClientError as exc:
        raise LLMUnavailable(f"deepseek client error: {exc}") from exc

    # Parse standard OpenAI-compatible response
    try:
        choice = data["choices"][0]
        content: str = choice["message"]["content"]
        usage = data["usage"]
        input_tokens: int = usage["prompt_tokens"]
        output_tokens: int = usage["completion_tokens"]
        model_id: str = data.get("model", requested_model)
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMAPIError(f"deepseek response malformed: {exc}: {str(data)[:200]}") from exc

    # Cost calculation
    cost_pair = _COST_PER_1K.get(requested_model) or _COST_PER_1K.get(model_id)
    if cost_pair:
        in_rate, out_rate = cost_pair
        cost_usd = (input_tokens / 1000.0) * in_rate + (output_tokens / 1000.0) * out_rate
    else:
        cost_usd = 0.0

    elapsed_ms = int((time.monotonic() - start) * 1000)

    return {
        "content": content,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "model_id": model_id,
        "elapsed_ms": elapsed_ms,
        "seed": None,
        "prompt_hash_hex": prompt_hash,
        "raw_response": data,
    }
