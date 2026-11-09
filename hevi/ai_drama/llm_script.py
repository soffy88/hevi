"""LLM dialogue drafting for the ai_drama script node (S19).

The script node used to be a deterministic scaffold only.  S19 routes the four
opening dialogue lines through the project's ordered text LLM (opencode first,
then the other registered channels), keeping the scaffold's scene structure,
lighting, ids and piper voices intact so the cowboy rules still pass.  When no
LLM answers (or the answer is malformed) the deterministic scaffold is kept and
the caller records ``script_source=deterministic``.

This is a text-only step: no provider SDK, no images, no paid channel added.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import json
import os
import re
from typing import Any

_MAX_LINE_CHARS = 30
_DEFAULT_TIMEOUT_S = float(os.getenv("HEVI_DRAMA_LLM_SCRIPT_TIMEOUT_S", "90"))

_PROMPT = """为主题“{theme}”写一场{style}短剧开头的四句中文对白。
按顺序：①主角打破日常的一句 ②对方反问 ③主角追问 ④对方回避或拒绝。
每句不超过 {max_chars} 个汉字，口语、有冲突感，不要旁白，不要解释。
只输出 JSON 数组，不要其它文字，例如：["第一句","第二句","第三句","第四句"]
用户主题：{theme}
"""


def _enabled() -> bool:
    return os.getenv("HEVI_DRAMA_LLM_SCRIPT", "1") not in {"0", "false", "False", "no"}


def _invoke(llm: Any, prompt: str) -> Any:
    """Call a possibly-async provider from the synchronous script node."""
    # Reasoning models spend hidden tokens first; 512 sometimes left content
    # empty (S19), which silently degraded to the deterministic scaffold.
    kwargs = {"messages": [{"role": "user", "content": prompt}], "max_tokens": 4096}

    def runner() -> Any:
        response = llm(**kwargs)
        if inspect.isawaitable(response):
            response = asyncio.run(response)
        return response

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(runner).result(timeout=_DEFAULT_TIMEOUT_S + 5)


def _parse_lines(content: Any) -> list[str]:
    raw = str(content or "").strip()
    raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw).strip()
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match is None:
        raise RuntimeError("LLM returned no JSON array")
    parsed = json.loads(match.group(0))
    if not isinstance(parsed, list):
        raise RuntimeError("LLM returned a non-array")
    lines = [str(item).strip() for item in parsed if str(item).strip()]
    if len(lines) < 4:
        raise RuntimeError(f"LLM returned {len(lines)} lines, expected 4")
    return [line[:_MAX_LINE_CHARS] for line in lines[:4]]


def draft_creative(theme: str, style: str) -> tuple[list[str] | None, str]:
    """Return ``(four_lines, channel)`` or ``(None, "")`` when unavailable."""
    theme = (theme or "").strip()
    if not theme or not _enabled():
        return None, ""
    from hevi.providers.llm_pick import TEXT_LLM_ORDER

    try:
        from obase.provider_registry import ProviderRegistry
    except Exception:  # pragma: no cover - import guard
        return None, ""
    registry = ProviderRegistry.get()
    llm = None
    name = ""
    for candidate in TEXT_LLM_ORDER:
        try:
            found = registry.llm(candidate)
        except Exception:
            continue
        if found is not None:
            llm, name = found, candidate
            break
    if llm is None:
        return None, ""
    prompt = _PROMPT.format(theme=theme, style=style or "live_action", max_chars=_MAX_LINE_CHARS)
    response = _invoke(llm, prompt)
    content = response.get("content") if isinstance(response, dict) else str(response)
    return _parse_lines(content), name


def apply_to_script(script: dict[str, Any], lines: list[str]) -> dict[str, Any]:
    """Overwrite the four scaffold dialogue lines, preserving structure."""
    scenes = script.get("scenes") or []
    if not scenes:
        return script
    dialogue = [
        line
        for beat in scenes[0].get("beats") or []
        for line in beat.get("dialogue") or []
        if isinstance(line, dict)
    ]
    for line, text in zip(dialogue, lines, strict=False):
        line["text"] = text
    if dialogue:
        from hevi.qa.hook_gate import ensure_opening_hook

        report = ensure_opening_hook(str(dialogue[0].get("text") or ""), topic=str(script.get("title") or ""))
        if report.get("rewritten"):
            dialogue[0]["text"] = report["text"]
        hook = script.setdefault("hook", {})
        hook["pass"] = bool(report["check"]["pass"])
        hook["signals"] = report["check"]["signals"]
        hook["first_3s_conflict"] = str(dialogue[0].get("text") or "")
    return script


__all__ = ["apply_to_script", "draft_creative"]
