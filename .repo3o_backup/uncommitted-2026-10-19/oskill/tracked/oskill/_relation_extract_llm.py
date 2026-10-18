"""K-AII-3: relation_extract_llm — LLM-based pairwise KU relation extraction.

Composition:
  - llm (LLMCaller injected)

Mandates (CI-checked):
  - grade field is hardcoded "unverified"; not settable by callers
  - Returns None when no clear relation found
  - LLM prompt instructs: "如无关系请返回 null，不要强行推断"
"""

from __future__ import annotations

import json
import re

from oprim._aii_graph_types import RelationResult

_SYSTEM_PROMPT = (
    "You are a knowledge graph specialist. Analyze relationships between "
    "knowledge units. Output valid JSON only. No markdown, no explanation."
)

_USER_TMPL = """\
Analyze the direct relationship between these two knowledge units (KUs).

KU A:
{ku_a}

KU B:
{ku_b}

If there is a clear, direct relationship, respond with exactly this JSON:
{{"relation_type": "<special_case_of|prerequisite_of|basis_of|references|contradicts>", \
"direction": "<a_to_b|b_to_a|bidirectional>", "rationale": "<concise explanation>"}}

如无关系请返回 null，不要强行推断。
If no clear relationship exists, return the JSON value null."""


async def relation_extract_llm(
    *,
    ku_a: dict,
    ku_b: dict,
    llm,
) -> RelationResult | None:
    """Extract the relationship between two KUs using an LLM.

    Composition: llm (LLMCaller injected by caller).

    Returns None if no clear relation exists; never fabricates one.
    grade is always "unverified" regardless of LLM output.
    """
    ku_a_str = json.dumps(ku_a, ensure_ascii=False, indent=2)
    ku_b_str = json.dumps(ku_b, ensure_ascii=False, indent=2)
    prompt = _USER_TMPL.format(ku_a=ku_a_str, ku_b=ku_b_str)

    resp = await llm(
        messages=[{"role": "user", "content": prompt}],
        system=_SYSTEM_PROMPT,
        max_tokens=512,
    )
    text = _extract_text(resp)
    data = _parse_json_response(text)
    if data is None:
        return None

    return RelationResult(
        relation_type=data["relation_type"],
        direction=data["direction"],
        rationale=data.get("rationale", ""),
    )


def _extract_text(resp: dict) -> str:
    for block in resp.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            return block["text"].strip()
    return ""


def _parse_json_response(text: str) -> dict | None:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        val = json.loads(text)
        if val is None:
            return None
        if isinstance(val, dict) and "relation_type" in val:
            return val
        return None
    except json.JSONDecodeError:
        if text.lower() in ("null", "none", ""):
            return None
        return None
