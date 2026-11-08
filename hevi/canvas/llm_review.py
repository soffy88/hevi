"""LLM review for canvas text nodes (script / sentences / subtitle).

Reuses hevi's existing free-channel client resolver
(``hevi.providers.free_llm.resolve_free_llm``) — the same channels the short
drama planning layer already uses.  No new provider, no paid API, no key: when
no free channel answers, the caller gets ``None`` and ``self_check`` keeps its
deterministic offline rules, marking the node ``review_mode=offline_rules``.

Review output is strict JSON::

    {"result": "pass" | "warn" | "fail",
     "issues": ["..."],
     "suggested_prompt": "..."}

A failing text node is rewritten once by :func:`build`'s rewriter before the
executor retries it (``ExecuteOptions.llm_rewriter``).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

_FAILED_UNTIL = 0.0
_FAIL_COOLDOWN_S = float(os.getenv("HEVI_CANVAS_LLM_COOLDOWN_S", "600"))
_DEFAULT_TIMEOUT_S = float(os.getenv("HEVI_CANVAS_LLM_TIMEOUT_S", "25"))

_SYSTEM = (
    "你是中文短视频口播稿的严格审稿人。只输出严格 JSON，不要解释、不要 markdown。"
)

_REVIEW_PROMPT = """审阅下面这段口播文本，判断它是否能直接用于成片。
评判：占位/未完成/无法朗读= fail；空泛、过长、过短、答非所问= warn；其余= pass。
只输出 JSON：
{{"result":"pass|warn|fail","issues":["具体问题"],"suggested_prompt":"一句可执行的修改建议"}}

文本：
{text}
"""

_REWRITE_PROMPT = """按修改建议重写这段中文口播文本，保持口语自然、可直接朗读。
只输出重写后的正文，不要 JSON、不要引号、不要解释。

原文：
{text}

修改建议：
{suggestion}
"""


def _parse_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    clean = text.strip()
    if clean.startswith("```"):
        match = re.search(r"```(?:json)?\n?(.*?)\n?```", clean, re.S)
        if match:
            clean = match.group(1).strip()
    match = re.search(r"\{.*\}", clean, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _run_sync(factory: Any, timeout: float) -> Any:
    def runner() -> Any:
        return asyncio.run(factory())

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runner)
        return future.result(timeout=timeout)


def _resolve() -> tuple[str, Any] | None:
    global _FAILED_UNTIL
    if time.monotonic() < _FAILED_UNTIL:
        return None
    try:
        from hevi.providers.free_llm import resolve_free_llm

        channel, caller = resolve_free_llm("auto")
        return channel, caller
    except Exception as exc:
        logger.warning("canvas LLM review unavailable: %s", exc)
        _FAILED_UNTIL = time.monotonic() + _FAIL_COOLDOWN_S
        return None


def _call(channel: str, caller: Any, prompt: str, *, max_tokens: int) -> str:
    global _FAILED_UNTIL
    timeout = _DEFAULT_TIMEOUT_S

    async def factory() -> dict[str, Any]:
        return await asyncio.wait_for(
            caller(
                messages=[{"role": "user", "content": prompt}],
                system=_SYSTEM,
                max_tokens=max_tokens,
                temperature=0,
            ),
            timeout=timeout,
        )

    try:
        response = _run_sync(factory, timeout + 5)
    except Exception as exc:
        logger.warning("canvas LLM channel %s failed: %s", channel, exc)
        _FAILED_UNTIL = time.monotonic() + _FAIL_COOLDOWN_S
        raise
    content = response.get("content") if isinstance(response, dict) else None
    return str(content or "")


def _reviewer_factory(channel: str, caller: Any) -> Any:
    def review(text: str, cfg: dict[str, Any]) -> dict[str, Any]:
        prompt = _REVIEW_PROMPT.format(text=str(text)[:6000])
        content = _call(channel, caller, prompt, max_tokens=600)
        data = _parse_json(content)
        if not data:
            # A non-JSON answer is a failed review, not a node failure.
            return {
                "result": "warn",
                "issues": ["LLM 审稿返回非 JSON，已忽略"],
                "suggested_prompt": "",
                "model": f"hevi.canvas.llm_review/{channel}",
            }
        verdict = str(data.get("result") or "").lower().strip()
        if verdict not in ("pass", "warn", "fail"):
            verdict = "warn"
        issues = data.get("issues") or data.get("reasons") or []
        if isinstance(issues, str):
            issues = [issues]
        return {
            "result": verdict,
            "issues": [str(item) for item in issues][:8],
            "suggested_prompt": str(data.get("suggested_prompt") or data.get("suggestion") or ""),
            "model": f"hevi.canvas.llm_review/{channel}",
        }

    return review


def _rewriter_factory(channel: str, caller: Any) -> Any:
    def rewrite(text: str, suggestion: str, cfg: dict[str, Any]) -> str:
        prompt = _REWRITE_PROMPT.format(text=str(text)[:6000], suggestion=str(suggestion)[:800])
        content = _call(channel, caller, prompt, max_tokens=1200)
        clean = content.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```[a-zA-Z]*\n?", "", clean)
            clean = re.sub(r"\n?```$", "", clean).strip()
        return clean

    return rewrite


def build() -> tuple[Any, Any, str] | None:
    """Return ``(reviewer, rewriter, channel)`` or ``None`` when unavailable."""
    resolved = _resolve()
    if resolved is None:
        return None
    channel, caller = resolved
    return _reviewer_factory(channel, caller), _rewriter_factory(channel, caller), channel


__all__ = ["build"]
