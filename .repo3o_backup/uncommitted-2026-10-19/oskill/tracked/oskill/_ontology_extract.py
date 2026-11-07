"""K-ONT-1: ontology_extract — generic two-pass LLM extraction framework (v4).

MAJOR v4.0.0 breaking change:
  All prompts are now REQUIRED injected parameters. The framework provides
  ONLY the two-pass orchestration mechanism (chunk → Pass1 → outline → Pass2
  → collect/validate/id-sync). Business semantics (6-class rules, grade policy,
  argument demotion, etc.) live entirely in the caller's injected prompts.

Mechanism (the only thing this element owns):
  Pass 1 (map): each chunk → llm(pass1_chunk) → aggregate → llm(pass1_outline)
  Pass 2 (extract): each chunk + outline → llm(pass2_chunk) →
          collect ku/edge/concept candidates with:
            - grade forced to "unverified" (structural invariant, not business)
            - knowledge_type validated against VALID_KNOWLEDGE_TYPES
            - positional KU without stance_holder dropped
            - sub_type coerced to NULL if not in VALID_SUB_TYPES
            - edge endpoints synced via temp_id → new_id map (defect A fix)
            - invalid relation_type discarded

The validation invariants above are STRUCTURAL (enforce the data contract of
OntologyExtractResult), not business classification — they stay in the element.
What the LLM should classify and how lives in the injected prompts.
"""

from __future__ import annotations

import json
import re

from oprim._aii_graph_types import (
    VALID_KNOWLEDGE_TYPES,
    VALID_RELATION_TYPES,
    VALID_SUB_TYPES,
    OntologyExtractResult,
)


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------
async def ontology_extract(
    *,
    source_text: str,
    llm,
    pass1_chunk_tmpl: str,
    pass1_chunk_system: str,
    pass1_outline_tmpl: str,
    pass1_outline_system: str,
    pass2_chunk_tmpl: str,
    pass2_system: str,
    chunk_size: int = 2000,
    doc_type: str = "textbook",
    source_credibility: str = "medium",
    existing_ku_summaries: list[str] | None = None,
    valid_knowledge_types: frozenset[str] | None = None,
    valid_sub_types: frozenset[str] | None = None,
    valid_relation_types: frozenset[str] | None = None,
) -> OntologyExtractResult:
    """Generic two-pass LLM ontology extraction. All prompts are REQUIRED.

    The element owns ONLY the orchestration + structural validation. All
    business classification logic must be supplied via the injected prompts.

    Prompt parameters (all REQUIRED — no built-in business defaults):
        pass1_chunk_tmpl:    Pass1 per-chunk prompt. Must contain {chunk_text}.
        pass1_chunk_system:  Pass1 per-chunk system prompt.
        pass1_outline_tmpl:  Pass1 outline synthesis prompt. Must contain
                             {doc_type}, {source_credibility}, {chunk_analyses}.
        pass1_outline_system: Pass1 outline system prompt.
        pass2_chunk_tmpl:    Pass2 KU extraction prompt. Must contain {outline},
                             {chunk_text}. (Inject classification rules here.)
        pass2_system:        Pass2 system prompt.

    Structural invariants enforced by the element (not business logic):
        - ku.grade forced to "unverified"
        - ku.knowledge_type must be in valid_knowledge_types (else → "factual")
        - positional ku without stance_holder dropped
        - ku.sub_type coerced to NULL if not in valid_sub_types (defect B)
        - edge endpoints synced via temp_id → new_id map (defect A)
        - edge.relation_type not in valid_relation_types discarded

    Vocabulary injection (backward-compatible — all default to built-in sets):
        valid_knowledge_types: override VALID_KNOWLEDGE_TYPES (Layer4 can extend)
        valid_sub_types:       override VALID_SUB_TYPES
        valid_relation_types:  override VALID_RELATION_TYPES

    Returns:
        OntologyExtractResult with ku_candidates / edge_candidates /
        concept_candidates / outline / stats.

    Example:
        >>> result = await ontology_extract(
        ...     source_text="...",
        ...     llm=llm_caller,
        ...     pass1_chunk_tmpl="Analyze: {chunk_text} ...",
        ...     pass1_chunk_system="You are an analyst...",
        ...     pass1_outline_tmpl="Synthesize {chunk_analyses} for {doc_type}/{source_credibility}...",
        ...     pass1_outline_system="You are an architect...",
        ...     pass2_chunk_tmpl="Extract KUs. Outline: {outline}. Text: {chunk_text}. Rules: ...",
        ...     pass2_system="You are a KU extractor...",
        ... )
    """
    _vkt = valid_knowledge_types or VALID_KNOWLEDGE_TYPES
    _vst = valid_sub_types or VALID_SUB_TYPES
    _vrt = valid_relation_types or VALID_RELATION_TYPES

    if not source_text.strip():
        return OntologyExtractResult(
            outline={},
            ku_candidates=[],
            edge_candidates=[],
            concept_candidates=[],
            stats={"total": 0, "by_type": {}, "explains_count": 0},
        )

    chunks = _split_chunks(source_text, chunk_size)

    # ------------------------------------------------------------------
    # Pass 1: per-chunk extraction → outline
    # ------------------------------------------------------------------
    chunk_analyses: list[dict] = []
    for chunk in chunks:
        prompt = pass1_chunk_tmpl.format(chunk_text=chunk)
        resp = await llm(
            messages=[{"role": "user", "content": prompt}],
            system=pass1_chunk_system,
            max_tokens=512,
        )
        analysis = _parse_json(resp) or {"concepts": [], "topics": [], "chapter": ""}
        chunk_analyses.append(analysis)

    outline_prompt = pass1_outline_tmpl.format(
        doc_type=doc_type,
        source_credibility=source_credibility,
        chunk_analyses=json.dumps(chunk_analyses, ensure_ascii=False, indent=2),
    )
    outline_resp = await llm(
        messages=[{"role": "user", "content": outline_prompt}],
        system=pass1_outline_system,
        max_tokens=1024,
    )
    outline = _parse_json(outline_resp) or {
        "chapters": [],
        "core_concepts": [],
        "main_thread": "",
        "stance": "",
        "doc_type": doc_type,
        "source_credibility": source_credibility,
    }

    # ------------------------------------------------------------------
    # Pass 2: per-chunk KU extraction with outline context
    # ------------------------------------------------------------------
    all_ku_candidates: list[dict] = []
    all_edge_candidates: list[dict] = []
    all_concept_candidates: list[str] = []
    outline_str = json.dumps(outline, ensure_ascii=False, indent=2)

    for chunk_idx, chunk in enumerate(chunks):
        prompt = pass2_chunk_tmpl.format(
            outline=outline_str,
            chunk_text=chunk,
        )
        resp = await llm(
            messages=[{"role": "user", "content": prompt}],
            system=pass2_system,
            max_tokens=2048,
        )
        data = _parse_json(resp) or {}

        # Collect KU candidates — build temp_id → new_id map for edge sync
        chunk_id_map: dict[str, str] = {}
        for ku in data.get("ku_candidates", []):
            if not isinstance(ku, dict):
                continue
            # Structural invariant: grade always "unverified"
            ku["grade"] = "unverified"
            # Structural: validate knowledge_type
            if ku.get("knowledge_type") not in _vkt:
                ku["knowledge_type"] = "factual"
            # Structural: positional must have stance_holder
            if ku.get("knowledge_type") == "positional" and not ku.get("stance_holder"):
                continue
            # Structural: coerce invalid sub_type to NULL (defect B)
            raw_sub = ku.get("sub_type")
            if raw_sub and raw_sub not in _vst:
                ku["sub_type"] = None
            # Reassign unique id — record temp → new mapping (defect A)
            temp_id = ku.get("id", "")
            new_id = f"ku_c{chunk_idx}_{len(all_ku_candidates)}"
            chunk_id_map[temp_id] = new_id
            ku["id"] = new_id
            all_ku_candidates.append(ku)

        # Collect edge candidates — sync endpoints via map (defect A)
        for edge in data.get("edge_candidates", []):
            if not isinstance(edge, dict):
                continue
            if edge.get("relation_type") not in _vrt:
                continue
            src = edge.get("source", "")
            dst = edge.get("target", "")
            edge["source"] = chunk_id_map.get(src, src)
            edge["target"] = chunk_id_map.get(dst, dst)
            all_edge_candidates.append(edge)

        # Collect concept candidates
        for concept in data.get("concept_candidates", []):
            if isinstance(concept, str) and concept not in all_concept_candidates:
                all_concept_candidates.append(concept)

    # ------------------------------------------------------------------
    # Build stats
    # ------------------------------------------------------------------
    by_type: dict[str, int] = {}
    for ku in all_ku_candidates:
        kt = ku.get("knowledge_type", "unknown")
        by_type[kt] = by_type.get(kt, 0) + 1
    explains_count = sum(1 for e in all_edge_candidates if e.get("relation_type") == "explains")
    stats = {
        "total": len(all_ku_candidates),
        "by_type": by_type,
        "explains_count": explains_count,
    }

    return OntologyExtractResult(
        outline=outline,
        ku_candidates=all_ku_candidates,
        edge_candidates=all_edge_candidates,
        concept_candidates=all_concept_candidates,
        stats=stats,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _split_chunks(text: str, chunk_size: int) -> list[str]:
    """Split text into chunks of approximately chunk_size characters."""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        if end < len(text):
            boundary = text.rfind("。", start, end)
            if boundary == -1:
                boundary = text.rfind(". ", start, end)
            if boundary != -1 and boundary > start:
                end = boundary + 1
        chunks.append(text[start:end].strip())
        start = end
    return [c for c in chunks if c]


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
    except (json.JSONDecodeError, ValueError):
        return None
