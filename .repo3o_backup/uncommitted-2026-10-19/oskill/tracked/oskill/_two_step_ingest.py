"""K-G2: two_step_ingest — two-pass LLM knowledge extraction.

Step 1: LLM analysis (entities, concepts, conflict candidates, structure).
Step 2: LLM KU generation using Step 1 results.

Mandate: Step 2 does NOT confirm conflicts — only outputs candidates for
conflict_resolution (K-G1) to adjudicate.

完整覆盖设计 (病根B修复):
  Step2 prompt 强制要求"穷举所有知识点", 不允许跳过段落/定理/例题.
  数学/经济学专项: 定理/引理/推导/公式/例题/反例 全部独立KU.
  max_tokens 2048→4096: 给更大输出空间以容纳完整覆盖的KU列表.
"""

from __future__ import annotations

import json
import re

from oprim._aii_graph_types import TwoStepIngestResult

_STEP1_SYSTEM = "You are a knowledge extraction specialist. Analyze the source text carefully. Output valid JSON only."
_STEP2_SYSTEM = (
    "You are an exhaustive knowledge unit extractor. "
    "Your job is to extract EVERY distinct piece of knowledge from the text — "
    "do not skip or summarize. Output valid JSON only."
)

_STEP1_TMPL = """\
Analyze the following text for knowledge extraction.

Text:
{source_text}

Existing KU summaries (for context):
{existing_summaries}

Output JSON with:
{{
  "entities": ["list of all entities, concepts, variables, symbols mentioned"],
  "concepts": ["list of all core and secondary concepts"],
  "conflict_candidates": ["descriptions of potential conflicts with existing KUs"],
  "structure": "description of argument structure and section types (theorem/proof/example/definition/etc)"
}}"""

_STEP2_TMPL = """\
Based on the following analysis, extract ALL knowledge units from the source text.

Source text:
{source_text}

Analysis from Step 1:
{analysis}

CRITICAL INSTRUCTIONS — you MUST follow all of these:
1. Extract EVERY distinct knowledge claim, definition, theorem, lemma, formula, \
example, and argument — do NOT skip any paragraph or sentence that contains knowledge.
2. Each theorem, definition, proof step, worked example, and key formula is a \
SEPARATE KU — do not merge unrelated knowledge into one KU.
3. For mathematics/economics texts: capture formal statements (with notation), \
intuitions, conditions/assumptions, and conclusions as separate KUs when distinct.
4. Do NOT only extract "important" or "key" points — extract ALL points. \
Completeness is the priority, not selectivity.
5. If a section contains N distinct claims, produce N KUs, not a summary of them.

Output JSON with:
{{
  "ku_candidates": [
    {{
      "title": "concise KU title",
      "content": "full KU content — include all relevant detail, notation, conditions",
      "type": "theorem|lemma|definition|formula|example|proof_step|claim|observation|procedure",
      "confidence": "high|medium|low"
    }}
  ]
}}

Important: Do NOT confirm conflicts here. Only generate KU content.
Conflict candidates will be verified separately."""


async def two_step_ingest(
    *,
    source_text: str,
    existing_ku_summaries: list[str],
    llm,
) -> TwoStepIngestResult:
    """Two-pass LLM knowledge extraction with exhaustive coverage.

    Composition: llm (LLMCaller injected), called twice independently.
    Step 2 prompt includes Step 1 analysis — fully chained.
    Conflicts are candidates only; conflict_resolution must adjudicate.

    完整覆盖设计: Step2 强制穷举, max_tokens=4096, 数学专项type扩展.
    """
    # Step 1: Analysis
    existing_block = "\n".join(f"- {s}" for s in existing_ku_summaries) or "(none)"
    step1_prompt = _STEP1_TMPL.format(source_text=source_text, existing_summaries=existing_block)
    step1_resp = await llm(
        messages=[{"role": "user", "content": step1_prompt}],
        system=_STEP1_SYSTEM,
        max_tokens=1024,
    )
    analysis = _parse_json(step1_resp) or {
        "entities": [],
        "concepts": [],
        "conflict_candidates": [],
        "structure": "",
    }

    # Step 2: KU Generation — exhaustive coverage (完整覆盖, max_tokens 2048→4096)
    step2_prompt = _STEP2_TMPL.format(
        source_text=source_text,
        analysis=json.dumps(analysis, ensure_ascii=False, indent=2),
    )
    step2_resp = await llm(
        messages=[{"role": "user", "content": step2_prompt}],
        system=_STEP2_SYSTEM,
        max_tokens=4096,  # 2048→4096: 完整覆盖需要更大输出空间
    )
    step2_data = _parse_json(step2_resp) or {}
    ku_candidates = step2_data.get("ku_candidates", [])

    return TwoStepIngestResult(
        analysis=analysis,
        ku_candidates=ku_candidates,
        conflict_candidates=analysis.get("conflict_candidates", []),
    )


def _parse_json(resp: dict) -> dict | None:
    text = ""
    for block in resp.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            text = block["text"].strip()
            break
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        val = json.loads(text)
        return val if isinstance(val, dict) else None
    except json.JSONDecodeError:
        return None
