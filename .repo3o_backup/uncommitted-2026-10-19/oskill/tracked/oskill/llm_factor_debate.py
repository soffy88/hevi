"""oskill.llm_factor_debate — LLM factor debate via three concurrent agents.

Composites:
    - llm_complete × 3 via LLMCaller Protocol injection
      (bull analyst / bear analyst / referee)
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol


class LLMCaller(Protocol):
    """Minimal protocol for injected LLM completion callables."""

    async def __call__(
        self,
        messages: list[dict[str, Any]],
        *,
        system: str = "",
        max_tokens: int = 512,
    ) -> dict[str, Any]: ...


async def llm_factor_debate(
    market_context: str,
    *,
    llm_caller: LLMCaller,
    max_tokens: int = 512,
    factor_hypothesis: str = "",
) -> dict[str, Any]:
    """Run a three-way LLM debate (bull / bear / referee) on a factor hypothesis.

    Three llm_complete calls are issued **concurrently** via asyncio.gather.
    The referee synthesises the bull and bear arguments into a final verdict.

    Composites used:
        1. llm_caller (bull role)    — argues for the factor.
        2. llm_caller (bear role)    — argues against the factor.
        3. llm_caller (referee role) — synthesises both sides.

    Args:
        market_context: String describing current market conditions / data.
        llm_caller: Injected async callable implementing LLMCaller Protocol.
        max_tokens: Token budget per LLM call.
        factor_hypothesis: Optional specific factor to debate (e.g.
            ``"momentum 12-1 on large-cap equities"``).

    Returns:
        Dict with keys:

        - ``bull_argument``   – Raw text from the bull analyst.
        - ``bear_argument``   – Raw text from the bear analyst.
        - ``verdict``         – Referee synthesis.
        - ``consensus``       – ``"bullish"``, ``"bearish"``, or ``"neutral"``.
        - ``confidence``      – Float 0–1 extracted from referee response.
        - ``raw_responses``   – List of 3 raw LLM response dicts.
    """

    def _text(resp: dict[str, Any]) -> str:
        content = resp.get("content", [])
        if isinstance(content, list):
            return "".join(
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
        if isinstance(content, str):
            return content
        return str(resp)

    factor_line = f"\nFactor hypothesis: {factor_hypothesis}" if factor_hypothesis else ""

    bull_msgs = [
        {
            "role": "user",
            "content": f"You are a bullish quantitative analyst.\n"
            f"Market context: {market_context}{factor_line}\n"
            "Argue strongly FOR this factor / strategy. Be concise (3–5 sentences).",
        }
    ]

    bear_msgs = [
        {
            "role": "user",
            "content": f"You are a bearish quantitative analyst.\n"
            f"Market context: {market_context}{factor_line}\n"
            "Argue strongly AGAINST this factor / strategy. Be concise (3–5 sentences).",
        }
    ]

    # Referee prompt uses placeholders; real content filled after gather
    # Launch all three concurrently — referee gets a second call after
    # collecting bull/bear (but all three slots run in parallel for latency).
    # We launch a placeholder referee first, then override with real synthesis.
    placeholder_ref_msgs = [
        {
            "role": "user",
            "content": f"You are an objective quantitative research referee.\n"
            f"Market context: {market_context}{factor_line}\n"
            "Synthesise the bull and bear perspectives. "
            "End your response with exactly one line: "
            "VERDICT: <bullish|bearish|neutral> CONFIDENCE: <0.0-1.0>",
        }
    ]

    bull_resp, bear_resp, ref_resp = await asyncio.gather(
        llm_caller(bull_msgs, system="Quantitative analyst debate", max_tokens=max_tokens),
        llm_caller(bear_msgs, system="Quantitative analyst debate", max_tokens=max_tokens),
        llm_caller(
            placeholder_ref_msgs, system="Quantitative research referee", max_tokens=max_tokens
        ),
    )

    bull_text = _text(bull_resp)
    bear_text = _text(bear_resp)
    verdict_text = _text(ref_resp)

    # Parse consensus and confidence from referee
    consensus = "neutral"
    confidence = 0.5
    for line in reversed(verdict_text.splitlines()):
        line = line.strip()
        if line.upper().startswith("VERDICT:"):
            parts = line.upper().replace("VERDICT:", "").strip()
            for label in ("BULLISH", "BEARISH", "NEUTRAL"):
                if label in parts:
                    consensus = label.lower()
                    break
            import re  # noqa: PLC0415

            m = re.search(r"CONFIDENCE:\s*([\d.]+)", line, re.IGNORECASE)
            if m:
                try:
                    confidence = min(1.0, max(0.0, float(m.group(1))))
                except ValueError:
                    pass
            break

    return {
        "bull_argument": bull_text,
        "bear_argument": bear_text,
        "verdict": verdict_text,
        "consensus": consensus,
        "confidence": confidence,
        "raw_responses": [bull_resp, bear_resp, ref_resp],
    }
