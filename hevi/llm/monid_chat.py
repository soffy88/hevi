"""Shared Monid-backed chat LLM for hevi (gpt-4o-mini via blockrun).

One route for every text-generation default backend in hevi, identical to
the one ``story.film_from_prompt`` already uses
(``hevi/storyfilm/pipeline.py: generate_story``):

* provider ``blockrun.ai``, endpoint ``/api/v1/chat/completions``,
  model ``gpt-4o-mini``, transported by
  :func:`hevi.audio.monid_client.run_endpoint` (Monid REST).

Key resolution — identical to storyfilm, by construction: this module never
reads a key itself.  ``hevi.audio.monid_client`` resolves ``MONID_API_KEY``
from the process environment (Bearer; ``MONID_API_BASE`` overrides the base
URL) and raises ``MonidError`` when it is unset.  On ubuntu26 the key lives
in the Monid CLI config under ``~/.config/monid/`` and is injected into the
process environment at runtime (the same injection that lets storyfilm
run), so any environment where storyfilm works works here too — and
:func:`monid_key_available` simply mirrors that env check without ever
touching the key value.

Cost: every chat call is a paid Monid call, billed per endpoint rate
against the workspace balance (small per call — the storyfilm story draft
on this route costs ~$0.002).  Callers surface ``qa``/ledger notes
accordingly; tests must monkeypatch :func:`hevi.audio.monid_client.run_endpoint`
(or this module's ``chat_*`` functions) and run offline at zero spend.

Sync/async: :func:`achat` is the native async entry point.  The ``*_sync``
facades work both inside and outside a running event loop — when a loop is
already running in the calling thread, the coroutine is executed on a
dedicated thread with its own loop (the ``storyfilm`` / ``multimodel``
``_run_coro`` pattern), because capability ``render`` functions are
synchronous but may be invoked from async contexts.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import re
from typing import Any

__all__ = [
    "ENDPOINT",
    "MODEL",
    "PROVIDER",
    "MonidChatError",
    "achat",
    "achat_for_kind",
    "achat_text",
    "build_branch_messages",
    "build_kind_messages",
    "build_rewrite_messages",
    "chat_for_kind_sync",
    "chat_sync",
    "generate_branches_sync",
    "missing_key_hint",
    "monid_key_available",
    "parse_branch_payloads",
    "rewrite_text_sync",
    "run_coro_sync",
]

PROVIDER = "blockrun.ai"
ENDPOINT = "/api/v1/chat/completions"
MODEL = "gpt-4o-mini"


class MonidChatError(RuntimeError):
    """A Monid chat call returned an unusable response."""


# ---------------------------------------------------------------------------
# Key availability (mirrors hevi.audio.monid_client._api_key's env check;
# the value itself is never read out, logged, or returned here)
# ---------------------------------------------------------------------------


def monid_key_available() -> bool:
    """True when ``MONID_API_KEY`` is set in the environment.

    This is exactly the condition under which ``monid_client`` (and hence
    storyfilm) can run: the runtime injects the key from the Monid config
    in ``~/.config/monid/`` into the environment before launching hevi.
    """
    return bool(os.environ.get("MONID_API_KEY", "").strip())


def missing_key_hint() -> str:
    """Human-readable reason the default Monid backend is unavailable."""
    return (
        "the default Monid backend (gpt-4o-mini via blockrun) is "
        "unavailable because MONID_API_KEY is not set in the environment "
        "(the same key story.film_from_prompt uses; on ubuntu26 it is "
        "injected at runtime from ~/.config/monid/)"
    )


# ---------------------------------------------------------------------------
# Sync facade over async coroutines (works with or without a running loop)
# ---------------------------------------------------------------------------


def run_coro_sync(coro: Any) -> Any:
    """Run ``coro`` to completion from synchronous code.

    Safe inside a running event loop: the coroutine is then executed on a
    fresh thread running its own loop (``asyncio.run`` cannot be nested).
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


# ---------------------------------------------------------------------------
# Core chat calls
# ---------------------------------------------------------------------------


async def achat(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 3000,
    temperature: float = 0.7,
) -> tuple[str, float | None]:
    """One Monid chat completion. Returns ``(content, cost)``.

    Raises ``hevi.audio.monid_client.MonidError`` when the key is missing
    or the run fails, and :class:`MonidChatError` when the response has no
    message content.
    """
    from hevi.audio import monid_client

    body = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    output, cost = await monid_client.run_endpoint(PROVIDER, ENDPOINT, body=body)
    try:
        content = output["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise MonidChatError(
            f"Monid chat response has no message content: {str(output)[:200]}"
        ) from exc
    text = str(content).strip()
    if not text:
        raise MonidChatError("Monid chat response content is empty")
    return text, cost


async def achat_text(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 3000,
    temperature: float = 0.7,
) -> str:
    """Async chat returning just the message text (cost discarded)."""
    text, _cost = await achat(messages, max_tokens=max_tokens, temperature=temperature)
    return text


def chat_sync(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 3000,
    temperature: float = 0.7,
) -> str:
    """Synchronous chat: message text via :func:`run_coro_sync`."""
    return run_coro_sync(
        achat_text(messages, max_tokens=max_tokens, temperature=temperature)
    )


# ---------------------------------------------------------------------------
# Novel pipeline kinds: llm_fn(prompt, kind) -> str
# (kinds from hevi.novelpipeline.core: book_outline | chapter_body |
#  expand | shrink | summary | continue_setup)
# ---------------------------------------------------------------------------

_KIND_SPECS: dict[str, tuple[str, int, float]] = {
    "book_outline": (
        "你是长篇小说总策划。严格按用户要求输出，只输出 JSON，不要 markdown 包裹。",
        3000,
        0.7,
    ),
    "continue_setup": (
        "你是小说档案整理员。只依据原文提炼，严格按用户要求输出，"
        "只输出 JSON，不要 markdown 包裹。",
        2000,
        0.5,
    ),
    "chapter_body": (
        "你是长篇小说作者。只输出正文，不要标题，不要解释。",
        4096,
        0.8,
    ),
    "expand": (
        "你是长篇小说编辑。只输出扩写后的完整正文，不要解释。",
        4096,
        0.7,
    ),
    "shrink": (
        "你是长篇小说编辑。只输出缩减后的完整正文，不要解释。",
        4096,
        0.7,
    ),
    "summary": ("你是编辑助理。只输出摘要本身，不要解释。", 800, 0.3),
}

_DEFAULT_KIND_SPEC = ("你是写作助手，严格按用户要求输出。", 3000, 0.7)


def build_kind_messages(prompt: str, kind: str) -> list[dict[str, str]]:
    """Assemble chat messages for one novel-pipeline ``kind``."""
    system, _max_tokens, _temperature = _KIND_SPECS.get(kind, _DEFAULT_KIND_SPEC)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]


def _kind_params(kind: str) -> tuple[int, float]:
    _system, max_tokens, temperature = _KIND_SPECS.get(kind, _DEFAULT_KIND_SPEC)
    return max_tokens, temperature


async def achat_for_kind(prompt: str, kind: str) -> str:
    """Async ``llm_fn(prompt, kind)`` equivalent (see novelpipeline core)."""
    max_tokens, temperature = _kind_params(kind)
    return await achat_text(
        build_kind_messages(prompt, kind),
        max_tokens=max_tokens,
        temperature=temperature,
    )


def chat_for_kind_sync(prompt: str, kind: str) -> str:
    """Synchronous ``llm_fn(prompt, kind) -> str`` on the Monid backend.

    Matches the ``hevi.novelpipeline.core`` contract: called directly,
    never awaited, and works inside or outside a running event loop.
    """
    max_tokens, temperature = _kind_params(kind)
    return chat_sync(
        build_kind_messages(prompt, kind),
        max_tokens=max_tokens,
        temperature=temperature,
    )


# ---------------------------------------------------------------------------
# Style transfer: rewrite_fn(text, profile) -> str (hevi.textcraft)
# ---------------------------------------------------------------------------


def build_rewrite_messages(text: str, profile: dict[str, Any]) -> list[dict[str, str]]:
    """Assemble chat messages for a style-profile-driven rewrite."""
    from hevi.textcraft.style import build_style_instructions

    instructions = build_style_instructions(profile)
    return [
        {
            "role": "system",
            "content": "你是文风仿写专家。只输出改写后的文本，不要解释。",
        },
        {"role": "user", "content": f"{instructions}\n\n原文：\n{text}"},
    ]


def rewrite_text_sync(text: str, profile: dict[str, Any]) -> str:
    """Synchronous ``rewrite_fn(text, profile) -> str`` on Monid."""
    return chat_sync(
        build_rewrite_messages(text, profile), max_tokens=3000, temperature=0.7
    )


# ---------------------------------------------------------------------------
# Story branches: generator_fn(state_dict, branch_count, seed) -> payloads
# (hevi.storybranch.core: each payload needs title / beats / key_decisions /
#  state_changes / risks / intent_match — same shape the deterministic
#  placeholder generator returns)
# ---------------------------------------------------------------------------

_BRANCH_SYSTEM = (
    "你是剧情推演专家。基于给定的故事状态，推演彼此独立的未来分支。"
    "只输出 JSON，不要 markdown 包裹，不要解释。"
)

_BRANCH_USER = """故事状态（JSON）：
{state_json}

请推演恰好 {branch_count} 条彼此独立的未来分支（seed={seed}，仅作推演记录）。
只输出 JSON，结构：
{{
  "branches": [
    {{
      "branch_id": "branch-1",
      "title": "分支标题",
      "beats": ["节拍1", "节拍2", "节拍3"],
      "key_decisions": [{{"character": "人物名", "decision": "关键抉择"}}],
      "state_changes": ["预计状态变化"],
      "risks": ["风险"],
      "intent_match": 0.85
    }}
  ]
}}
约束：branches 恰好 {branch_count} 条；branch_id 依次为 branch-1..branch-{branch_count}；
beats / key_decisions / state_changes / risks 均为非空数组；
intent_match 是 0 到 1 之间的小数，表示与作者意图的契合度；
不得违背 canon_facts，不得让作者意图中禁止发生的事情发生。"""


def build_branch_messages(
    state_dict: dict[str, Any], branch_count: int, seed: int
) -> list[dict[str, str]]:
    """Assemble chat messages for a branch forecast generation."""
    return [
        {"role": "system", "content": _BRANCH_SYSTEM},
        {
            "role": "user",
            "content": _BRANCH_USER.format(
                state_json=json.dumps(state_dict, ensure_ascii=False, indent=1),
                branch_count=branch_count,
                seed=seed,
            ),
        },
    ]


def parse_branch_payloads(text: str, branch_count: int) -> list[dict[str, Any]]:
    """Parse an LLM branch response into core-shaped branch payloads.

    Accepts a bare JSON array or an object with a ``branches`` array
    (optionally fenced).  Missing/duplicate ``branch_id`` values are
    repaired to the sequential ``branch-<n>`` scheme; every other field is
    left untouched for ``hevi.storybranch.core`` to validate.
    """
    cleaned = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise MonidChatError(f"branch response is not valid JSON: {exc}") from exc
    if isinstance(data, dict):
        data = data.get("branches")
    if not isinstance(data, list):
        raise MonidChatError("branch response must be a JSON array of branches")
    if len(data) != branch_count:
        raise MonidChatError(
            f"branch response has {len(data)} branches, expected {branch_count}"
        )
    payloads: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise MonidChatError(f"branch #{i + 1}: payload must be an object")
        payload = dict(item)
        branch_id = str(payload.get("branch_id") or "").strip()
        if not branch_id or branch_id in seen:
            branch_id = f"branch-{i + 1}"
            suffix = 1
            while branch_id in seen:
                suffix += 1
                branch_id = f"branch-{i + 1}-{suffix}"
        payload["branch_id"] = branch_id
        seen.add(branch_id)
        payloads.append(payload)
    return payloads


def generate_branches_sync(
    state_dict: dict[str, Any], branch_count: int, seed: int
) -> list[dict[str, Any]]:
    """Synchronous ``generator_fn`` on Monid (storybranch core contract)."""
    text = chat_sync(
        build_branch_messages(state_dict, branch_count, seed),
        max_tokens=3500,
        temperature=0.8,
    )
    return parse_branch_payloads(text, branch_count)
