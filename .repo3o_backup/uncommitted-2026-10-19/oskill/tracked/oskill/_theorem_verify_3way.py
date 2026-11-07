"""K-AII-5: theorem_verify_3way — three-way theorem verification pipeline.

Composition:
  - mathlib_lookup (Callable injected) — oprim sync primitive
  - llm (LLMCaller injected) — semantic comparison

Verification flow (strict order, first failure → reject candidate, next):
  1. mathlib_lookup(candidate) → MathlibLookupResult
  2. result.count != 1 → reject("count={n}, not unique")
  3. count == 1 → LLM semantic compare ku_text ↔ type_signature
  4. LLM "consistent" → verified(lean_name from hits[0].name, type_signature from hits[0])
     LLM "inconsistent" → reject, continue
     LLM "uncertain" → strict=True: reject; strict=False: return ambiguous
  5. All candidates exhausted → rejected

Mandates (CI-checked):
  - strict=True: uncertain treated as rejected, never passes through
  - verified requires BOTH count==1 AND LLM=="consistent"
  - lean_name and type_signature come from mathlib_lookup only, never from LLM
"""

from __future__ import annotations

import inspect
import json
import re

from oprim._aii_graph_types import TheoremVerifyResult

_SYSTEM_PROMPT = (
    "You are a mathematical logic expert. "
    "Compare a knowledge unit statement with a Lean 4 type signature. "
    "Output only valid JSON."
)

_COMPARE_TMPL = """\
Compare the mathematical knowledge unit statement with the Lean 4 type signature.

Knowledge Unit Statement:
{ku_text}

Lean 4 Type Signature ({lean_name}):
{type_signature}

Comparison rules:
1. Core mathematical assertion semantically equivalent → consistent
2. Type parameter/generalization differences (ℝ vs topological space) not affecting \
core assertion → check specific version (e.g. intermediate_value_Icc)
3. Ambiguous, partially consistent, or uncertain → uncertain \
(treated as reject when strict=True)
4. Clearly different semantics → inconsistent

Output exactly this JSON (no markdown, no extra text):
{{"verdict": "consistent"|"inconsistent"|"uncertain", "reason": "<brief explanation>"}}"""


async def theorem_verify_3way(
    *,
    ku_text: str,
    candidate_lean_names: list[str],
    mathlib_lookup,  # Callable: (lean_name: str) -> MathlibLookupResult
    llm,  # LLMCaller
    strict: bool = True,
) -> TheoremVerifyResult:
    """Verify a theorem KU against Mathlib via a three-way check.

    Three gates must all pass for "verified":
      1. Unique Mathlib hit (count == 1)
      2. LLM semantic consistency == "consistent"
      3. lean_name and type_signature sourced from mathlib_lookup (not LLM)
    """
    if not candidate_lean_names:
        return TheoremVerifyResult(
            verdict="rejected",
            lean_name=None,
            type_signature=None,
            reason="no candidates",
        )

    last_reason = "all candidates rejected"

    for candidate in candidate_lean_names:
        # Gate 1: mathlib_lookup
        try:
            if inspect.iscoroutinefunction(mathlib_lookup):
                result = await mathlib_lookup(candidate)
            else:
                result = mathlib_lookup(candidate)
        except Exception as exc:
            last_reason = f"{candidate}: mathlib_lookup error: {exc}"
            continue

        if result.count != 1:
            last_reason = f"{candidate}: count={result.count}, not unique"
            continue

        # Unique hit — source lean_name and type_signature from lookup (never LLM)
        hit = result.hits[0]
        resolved_lean_name = hit.name
        resolved_type_sig = hit.type_signature

        # Gate 2: LLM semantic comparison
        llm_verdict, llm_reason = await _llm_compare(
            ku_text=ku_text,
            lean_name=resolved_lean_name,
            type_signature=resolved_type_sig,
            llm=llm,
        )

        if llm_verdict == "consistent":
            return TheoremVerifyResult(
                verdict="verified",
                lean_name=resolved_lean_name,
                type_signature=resolved_type_sig,
                reason="",
            )

        if llm_verdict == "uncertain":
            if not strict:
                return TheoremVerifyResult(
                    verdict="ambiguous",
                    lean_name=None,
                    type_signature=None,
                    reason=llm_reason or "uncertain semantic match",
                )
            # strict=True: uncertain treated as rejected
            last_reason = f"{candidate}: LLM uncertain (strict=True → rejected): {llm_reason}"
            continue

        # inconsistent or parse failure
        last_reason = f"{candidate}: {llm_verdict}: {llm_reason}"

    return TheoremVerifyResult(
        verdict="rejected",
        lean_name=None,
        type_signature=None,
        reason=last_reason,
    )


async def _llm_compare(
    *,
    ku_text: str,
    lean_name: str,
    type_signature: str,
    llm,
) -> tuple[str, str]:
    """Call LLM to compare ku_text with type_signature.

    Returns (verdict, reason) where verdict is one of:
    "consistent" | "inconsistent" | "uncertain" | "parse_error"
    """
    prompt = _COMPARE_TMPL.format(
        ku_text=ku_text,
        lean_name=lean_name,
        type_signature=type_signature,
    )
    try:
        resp = await llm(
            messages=[{"role": "user", "content": prompt}],
            system=_SYSTEM_PROMPT,
            max_tokens=256,
        )
        text = _extract_text(resp)
        return _parse_llm_json(text)
    except Exception as exc:
        return "parse_error", f"LLM call failed: {exc}"


def _extract_text(resp: dict) -> str:
    for block in resp.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            return block["text"].strip()
    return ""


def _parse_llm_json(text: str) -> tuple[str, str]:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        val = json.loads(text)
        if not isinstance(val, dict):
            return "parse_error", "LLM returned non-object JSON"
        verdict = val.get("verdict", "")
        reason = val.get("reason", "")
        if verdict not in ("consistent", "inconsistent", "uncertain"):
            return "parse_error", f"unknown verdict: {verdict!r}"
        return verdict, reason
    except json.JSONDecodeError:
        return "parse_error", f"invalid JSON: {text[:80]}"
