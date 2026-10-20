"""Shared LLM backends for hevi (default: Monid gpt-4o-mini chat).

See :mod:`hevi.llm.monid_chat` for the route, key-resolution and cost
notes.  Importing this package is cheap: the Monid transport
(``hevi.audio.monid_client``) is only imported when a call is made.
"""

from __future__ import annotations

from hevi.llm.monid_chat import (
    ENDPOINT,
    MODEL,
    PROVIDER,
    MonidChatError,
    achat,
    achat_for_kind,
    build_branch_messages,
    build_kind_messages,
    build_rewrite_messages,
    chat_for_kind_sync,
    chat_sync,
    generate_branches_sync,
    missing_key_hint,
    monid_key_available,
    parse_branch_payloads,
    rewrite_text_sync,
    run_coro_sync,
)

__all__ = [
    "ENDPOINT",
    "MODEL",
    "PROVIDER",
    "MonidChatError",
    "achat",
    "achat_for_kind",
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
