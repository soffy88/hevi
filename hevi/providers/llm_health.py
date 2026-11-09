"""Text-LLM health probe used by the host alerting cron (S19).

The production text stack is OpenCode Zen (opencode-go).  This probe runs inside
the api container (so it sees the same env/credentials) and makes one tiny real
call.  ``deploy/ops/hevi-healthcheck`` only adds it to the failure set after N
consecutive failures, then reuses the existing alert dedupe.

Exit code: 0 = answered, 1 = failed, 2 = not configured.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from typing import Any

_DEFAULT_CHANNEL = os.getenv("HEVI_LLM_HEALTH_CHANNEL", "opencode")
_DEFAULT_TIMEOUT_S = float(os.getenv("HEVI_LLM_HEALTH_TIMEOUT_S", "45"))
_PROMPT = "Reply with exactly the single word: PONG"


async def probe_text_llm(
    channel: str | None = None,
    *,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Make one real call on ``channel`` and report availability/latency."""
    from hevi.providers.free_llm import build_channel_caller

    name = (channel or _DEFAULT_CHANNEL).strip() or "opencode"
    limit = float(timeout or _DEFAULT_TIMEOUT_S)
    caller = build_channel_caller(name)
    if caller is None:
        return {"available": False, "channel": name, "reason": "not_configured"}
    start = time.monotonic()
    try:
        response = await asyncio.wait_for(
            caller(messages=[{"role": "user", "content": _PROMPT}], max_tokens=64),
            timeout=limit,
        )
        content = response.get("content") if isinstance(response, dict) else str(response)
        text = str(content or "").strip()
        latency = round(time.monotonic() - start, 2)
        if not text:
            return {
                "available": False,
                "channel": name,
                "reason": "empty_content",
                "latency_s": latency,
            }
        return {
            "available": True,
            "channel": name,
            "latency_s": latency,
            "reply": text[:40],
        }
    except Exception as exc:
        return {
            "available": False,
            "channel": name,
            "reason": f"{type(exc).__name__}: {exc}"[:200],
            "latency_s": round(time.monotonic() - start, 2),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe the HEVI text-LLM channel")
    parser.add_argument("--channel", default=os.getenv("HEVI_LLM_HEALTH_CHANNEL", ""))
    parser.add_argument("--timeout", type=float, default=_DEFAULT_TIMEOUT_S)
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args(argv)
    result = asyncio.run(probe_text_llm(args.channel or None, timeout=args.timeout))
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps(result, ensure_ascii=False))
    if result.get("reason") == "not_configured":
        return 2
    return 0 if result.get("available") else 1


if __name__ == "__main__":
    sys.exit(main())
