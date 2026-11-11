"""LLM-readable 3D prompt pack gate (``qa.sand3d_prompt_pack_gate``).

A sand3d-style prompt pack puts the modeling API into the
prompt so an LLM can write a 3D program. Three things must be
true at once: the pack pins the exact sand3d version it was
measured against, its token estimate follows from a measured
word count of the API document (code-dense text runs about
1.3–1.7 tokens per word; an estimate outside that band is
unmeasured, not wrong by a little), and the estimate fits the
declared token budget. Any claimed token saving must carry
its own measured evidence; a bare claim fails. Author
self-reported numbers are never copied in as verified facts:
only the measured word count and the estimate derived from
it count.

Clean-room restatement of the Sandflow-ai/sand3d method (see
``SAND3D_ATTRIBUTION.md``); no upstream code appears here.
This gate judges prompt pack descriptions only; it never runs
Blender or any sand3d code. Real execution needs a separate
py3.13 + bpy 5.2 environment and is a separate work item.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

PINNED_VERSION = "1.6.3"
TOKENS_PER_WORD_LOW = 1.3
TOKENS_PER_WORD_HIGH = 1.7


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_sand3d_prompt_pack(pack: Any) -> dict[str, Any]:
    """Validate a sand3d-style prompt pack description.

    Verdicts are ``pass`` / ``fail`` only. The pack fails when
    it is not an object, when its sand3d version is not the
    pinned version, when its API document word count, token
    estimate, or token budget is missing or not positive, when
    the token estimate falls outside the measured band of
    1.3–1.7 tokens per word of the API document, when the
    estimate exceeds the budget, or when it claims a token
    saving without measured evidence.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(pack, dict):
        return fail("pack_not_object", "prompt pack must be a JSON object")
    version = pack.get("sand3d_version")
    if version != PINNED_VERSION:
        return fail(
            "version_not_pinned",
            f"prompt pack must pin sand3d version {PINNED_VERSION!r}, got {version!r}",
        )
    words = pack.get("api_doc_words")
    if not isinstance(words, int) or isinstance(words, bool) or words <= 0:
        return fail(
            "api_doc_words_missing",
            "prompt pack must state the measured word count of its API document",
        )
    estimate = pack.get("estimated_tokens")
    if not _is_number(estimate) or estimate <= 0:
        return fail(
            "estimated_tokens_missing",
            "prompt pack must state its token estimate as a positive number",
        )
    low = TOKENS_PER_WORD_LOW * words
    high = TOKENS_PER_WORD_HIGH * words
    if estimate < low or estimate > high:
        return fail(
            "token_estimate_unmeasured",
            f"token estimate {estimate} falls outside the measured "
            f"band {low:.0f}-{high:.0f} tokens for {words} words "
            "(1.3-1.7 tokens per word)",
        )
    budget = pack.get("token_budget")
    if not _is_number(budget) or budget <= 0:
        return fail(
            "token_budget_missing",
            "prompt pack must state its token budget as a positive number",
        )
    if estimate > budget:
        return fail(
            "token_budget_exceeded",
            f"token estimate {estimate} exceeds the budget {budget}",
        )
    if pack.get("claimed_token_reduction") is not None and not pack.get("measured_reduction"):
        return fail(
            "reduction_unmeasured",
            "a claimed token saving needs measured evidence; a bare claim is not a measurement",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_sand3d_prompt_pack(params.get("pack"))
    report_path = out_dir / "sand3d_prompt_pack_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_sand3d_prompt_pack_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.sand3d_prompt_pack_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "pack": {"type": "object"},
                },
                "required": ["pack"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "sand3d prompt pack gate: version pinned, token "
                "estimate derived from a measured API word count "
                "(1.3-1.7 tokens per word), estimate within budget, "
                "claimed savings need measured evidence."
            ),
        )
    )
    return ["qa.sand3d_prompt_pack_gate"]


__all__ = [
    "PINNED_VERSION",
    "TOKENS_PER_WORD_HIGH",
    "TOKENS_PER_WORD_LOW",
    "check_sand3d_prompt_pack",
    "register_sand3d_prompt_pack_gate_capabilities_once",
]
