"""Textcraft capabilities: style extraction / transfer and de-AI polish.

Registers three ``hevi.capabilities`` entries (line ``textcraft``):

* ``text.style_extract`` — deterministic statistical style profile of a
  sample text (sentence/paragraph length distributions, punctuation and
  function-word frequencies, tone markers).  Pure local computation; writes
  ``profile.json``.
* ``text.style_transfer`` — rewrite a text toward a style profile (given
  directly, or extracted from ``sample_text``).  Backend resolution order:
  an explicitly injected rewrite function (see :func:`set_rewrite_fn`)
  wins; otherwise the default Monid backend (:mod:`hevi.llm.monid_chat`,
  gpt-4o-mini via blockrun — the same route and the same ``MONID_API_KEY``
  env key as ``story.film_from_prompt``, billed per Monid call at a small
  per-call rate) is used when the key is resolvable; with neither available
  the render raises ``CapabilityError`` rather than faking a transfer.
  Writes ``profile.json`` + ``rewritten.txt``.
* ``text.humanize`` — deterministic de-AI polish (template-cliché removal,
  colloquial swaps, long-sentence splitting, punctuation diversification).
  Pure local computation; writes ``humanized.txt`` + ``humanize_report.json``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# Injected LLM rewrite backend: fn(text, profile) -> rewritten text.
# Kept module-level so the coordinator / product line can wire any provider
# without this module importing one.  ``None`` = not explicitly configured
# (the default Monid backend may still apply — see _resolve_rewrite_fn).
_REWRITE_FN: Callable[[str, dict[str, Any]], str] | None = None


def set_rewrite_fn(fn: Callable[[str, dict[str, Any]], str] | None) -> None:
    """Install (or clear, with ``None``) the style-transfer rewrite backend."""
    global _REWRITE_FN
    _REWRITE_FN = fn


def get_rewrite_fn() -> Callable[[str, dict[str, Any]], str] | None:
    """Return the explicitly injected rewrite fn (``None`` if none).

    Note this does not reflect the default Monid backend; renders resolve
    the effective backend via :func:`_resolve_rewrite_fn`.
    """
    return _REWRITE_FN


def _default_rewrite_fn(text: str, profile: dict[str, Any]) -> str:
    """Default backend: Monid gpt-4o-mini chat (see hevi.llm.monid_chat)."""
    from hevi.llm import monid_chat

    return monid_chat.rewrite_text_sync(text, profile)


def _resolve_rewrite_fn() -> Callable[[str, dict[str, Any]], str] | None:
    """Effective rewrite fn: injected > default Monid (key ok) > None."""
    if _REWRITE_FN is not None:
        return _REWRITE_FN
    from hevi.llm import monid_chat

    if monid_chat.monid_key_available():
        return _default_rewrite_fn
    return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def _render_style_extract(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.textcraft.style import extract_style_profile

    text = str(params["text"])
    if not text.strip():
        raise CapabilityError("text.style_extract: text must be non-empty")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        profile = extract_style_profile(text)
    except ValueError as exc:
        raise CapabilityError(f"text.style_extract: {exc}") from exc
    profile_path = out_dir / "profile.json"
    _write_json(profile_path, profile)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(profile_path),
        qa={
            "profile_json": str(profile_path),
            "char_count": profile["char_count"],
            "sentence_count": profile["sentence_count"],
            "sentence_len_mean": profile["sentence_len"]["mean"],
        },
    )


def _render_style_transfer(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.textcraft.style import extract_style_profile, style_transfer

    text = str(params["text"])
    if not text.strip():
        raise CapabilityError("text.style_transfer: text must be non-empty")
    if "profile" in params and params["profile"] is not None:
        profile = params["profile"]
        if not isinstance(profile, dict) or "sentence_len" not in profile:
            raise CapabilityError(
                "text.style_transfer: profile must be a style profile dict"
            )
    elif params.get("sample_text"):
        try:
            profile = extract_style_profile(str(params["sample_text"]))
        except ValueError as exc:
            raise CapabilityError(f"text.style_transfer: {exc}") from exc
    else:
        raise CapabilityError(
            "text.style_transfer: provide either sample_text or profile"
        )
    rewrite_fn = _resolve_rewrite_fn()
    if rewrite_fn is None:
        from hevi.llm import monid_chat

        raise CapabilityError(
            "text.style_transfer: no rewrite backend configured; inject one "
            "via hevi.capabilities.textcraft.set_rewrite_fn; and "
            f"{monid_chat.missing_key_hint()}"
        )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        rewritten = style_transfer(text, profile, rewrite_fn)
    except ValueError as exc:
        raise CapabilityError(f"text.style_transfer: {exc}") from exc
    except Exception as exc:  # contract wants CapabilityError
        raise CapabilityError(f"text.style_transfer failed: {exc}") from exc

    profile_path = out_dir / "profile.json"
    _write_json(profile_path, profile)
    rewritten_path = out_dir / "rewritten.txt"
    rewritten_path.write_text(rewritten, encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(rewritten_path),
        qa={
            "profile_json": str(profile_path),
            "rewritten_txt": str(rewritten_path),
            "rewrite_backend": getattr(rewrite_fn, "__name__", "injected"),
            "input_chars": len(text),
            "output_chars": len(rewritten),
        },
    )


def _render_humanize(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.textcraft.humanize import humanize_text

    text = str(params["text"])
    if not text.strip():
        raise CapabilityError("text.humanize: text must be non-empty")
    max_sentence_len = int(params.get("max_sentence_len", 42))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        polished, report = humanize_text(text, max_sentence_len=max_sentence_len)
    except ValueError as exc:
        raise CapabilityError(f"text.humanize: {exc}") from exc

    text_path = out_dir / "humanized.txt"
    text_path.write_text(polished, encoding="utf-8")
    report_path = out_dir / "humanize_report.json"
    _write_json(report_path, report)
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(text_path),
        qa={
            "humanized_txt": str(text_path),
            "report_json": str(report_path),
            "changes_total": report["changes_total"],
            "by_category": report["by_category"],
            "cliche_before": report["cliche_before"],
            "cliche_after": report["cliche_after"],
        },
    )


def register_textcraft_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    registered: list[str] = []

    register(
        Capability(
            name="text.style_extract",
            kind="text",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Sample text whose style should be profiled",
                    },
                },
                "required": ["text"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_style_extract,
            description=(
                "Deterministic statistical style profile of a sample text: "
                "sentence/paragraph length distributions, punctuation and "
                "function-word frequencies, modal-particle and tone ratios. "
                "Writes profile.json. Use as the first step of style transfer "
                "or to compare two authors' styles."
            ),
            line="textcraft",
        )
    )
    registered.append("text.style_extract")

    register(
        Capability(
            name="text.style_transfer",
            kind="text",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Text to rewrite in the target style",
                    },
                    "sample_text": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Sample in the target style (profile is extracted from it)",
                    },
                    "profile": {
                        "type": "object",
                        "description": "A style profile dict from text.style_extract",
                    },
                },
                "required": ["text"],
                "anyOf": [{"required": ["sample_text"]}, {"required": ["profile"]}],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_style_transfer,
            description=(
                "Rewrite text toward a style profile (from sample_text or a "
                "profile dict). The rewrite is performed by the injected "
                "backend (set_rewrite_fn) when one is installed, otherwise "
                "by the default Monid gpt-4o-mini backend (per-call small "
                "fee, same MONID_API_KEY as story.film_from_prompt); with "
                "neither available the render raises CapabilityError. "
                "Writes profile.json + rewritten.txt."
            ),
            line="textcraft",
        )
    )
    registered.append("text.style_transfer")

    register(
        Capability(
            name="text.humanize",
            kind="text",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Text to polish",
                    },
                    "max_sentence_len": {
                        "type": "integer",
                        "minimum": 10,
                        "maximum": 200,
                        "default": 42,
                        "description": "Sentences longer than this are split at commas",
                    },
                },
                "required": ["text"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render_humanize,
            description=(
                "Deterministic de-AI polish for Chinese text: removes template "
                "clichés (值得注意的是/总而言之/…), applies colloquial swaps, "
                "splits over-long sentences and diversifies punctuation. "
                "Writes humanized.txt + humanize_report.json with per-category "
                "change counts."
            ),
            line="textcraft",
        )
    )
    registered.append("text.humanize")

    return registered


__all__ = ["get_rewrite_fn", "register_textcraft_capabilities_once", "set_rewrite_fn"]
