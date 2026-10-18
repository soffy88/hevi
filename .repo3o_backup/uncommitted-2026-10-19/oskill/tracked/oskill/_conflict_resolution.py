"""K-G1: conflict_resolution — batch LLM-confirmed conflict detection.

Composition:
  - ku_conflict_detect (oprim P-G1) — candidate pre-filtering
  - llm (LLMCaller injected) — conflict type/severity confirmation

Mandate (CI-checked):
  - grade field in ConflictPair is hardcoded "unverified"; LLM cannot raise it
  - Returns [] when no conflicts found; never fabricates conflicts
"""

from __future__ import annotations

import json
import re

from oprim._aii_graph_types import ConflictPair
from oprim._ku_conflict_detect import ku_conflict_detect

_SYSTEM = (
    "You are a knowledge consistency expert. Analyze whether two statements conflict. "
    "Output only valid JSON."
)

_PROMPT_TMPL = """\
Determine whether these two knowledge statements conflict.

Statement A (new):
{text_a}

Statement B (existing, id={existing_id}):
{text_b}

If there is a genuine conflict, respond with:
{{"conflict_type": "factual_contradiction"|"stance_opposition"|"scope_conflict",
  "description": "<concise explanation>",
  "severity": "high"|"medium"|"low"}}

如果没有真实冲突，返回 null。
If there is no genuine conflict, return the JSON value null."""


async def conflict_resolution(
    *,
    new_ku_texts: list[str],
    new_ku_embeddings: list[list[float]],
    existing_ku_texts: list[str],
    existing_ku_embeddings: list[list[float]],
    existing_ku_ids: list[str],
    llm,
    conflict_threshold: float = 0.6,
) -> list[ConflictPair]:
    """Detect conflicts between new KUs and existing KUs.

    Composition: ku_conflict_detect (P-G1) for candidate pre-filtering,
    then LLM confirmation for each candidate.

    grade in ConflictPair is always "unverified" regardless of LLM output.
    Returns [] when no conflicts; never fabricates.
    """
    pairs: list[ConflictPair] = []

    for i, (new_text, new_emb) in enumerate(zip(new_ku_texts, new_ku_embeddings)):
        for j, (exist_text, exist_emb, exist_id) in enumerate(
            zip(existing_ku_texts, existing_ku_embeddings, existing_ku_ids)
        ):
            # Gate: rule-based candidate filter
            signal = ku_conflict_detect(
                ku_text_a=new_text,
                ku_text_b=exist_text,
                embedding_a=new_emb,
                embedding_b=exist_emb,
                similarity_threshold=conflict_threshold,
            )
            if not signal.is_conflict_candidate:
                continue

            # LLM confirmation
            verdict = await _llm_confirm(
                text_a=new_text,
                text_b=exist_text,
                existing_id=exist_id,
                llm=llm,
            )
            if verdict is None:
                continue

            pairs.append(
                ConflictPair(
                    new_ku_idx=i,
                    existing_ku_id=exist_id,
                    conflict_type=verdict["conflict_type"],
                    description=verdict["description"],
                    severity=verdict.get("severity", "low"),
                    # grade is set by __post_init__ to "unverified" — not from LLM
                )
            )

    return pairs


async def _llm_confirm(*, text_a: str, text_b: str, existing_id: str, llm) -> dict | None:
    prompt = _PROMPT_TMPL.format(text_a=text_a, text_b=text_b, existing_id=existing_id)
    try:
        resp = await llm(
            messages=[{"role": "user", "content": prompt}],
            system=_SYSTEM,
            max_tokens=256,
        )
        text = _extract_text(resp)
        return _parse(text)
    except Exception:
        return None


def _extract_text(resp: dict) -> str:
    for block in resp.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            return block["text"].strip()
    return ""


def _parse(text: str) -> dict | None:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        val = json.loads(text)
        if val is None:
            return None
        if isinstance(val, dict) and "conflict_type" in val:
            return val
        return None
    except json.JSONDecodeError:
        return None
