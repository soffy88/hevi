"""oskill.ku_extract_pipeline — KU extraction pipeline from text chunks.

3O layer: oskill (≥2 oprim composition, stateless).

Internal oprim composition:
    - oprim.structural_chunk: split document into semantic sections
    - oprim.llm_extract_ku: extract KU candidate from each chunk (single LLM call per chunk)
    - oprim.ku_gate_validate: validate each extracted KU before returning
"""

from __future__ import annotations

from oprim import ku_gate_validate, llm_extract_ku, structural_chunk


def ku_extract_pipeline(
    *,
    text: str,
    project_id: str = "default",
    knowledge_type_hint: str | None = None,
    min_chunk_chars: int = 50,
    provider: str = "default",
) -> dict:
    """Extract validated KU candidates from a document.

    Returns: {candidates: list[dict], rejected: list[dict], chunks_processed: int}
    Each candidate is a validated KU. Rejected items include validation errors.
    """
    # 1. structural_chunk to split doc
    chunks = structural_chunk(text=text, min_chars=min_chunk_chars)

    candidates = []
    rejected = []
    for chunk in chunks:
        # 2. llm_extract_ku for each chunk
        ku = llm_extract_ku(
            text=chunk["content"],
            project_id=project_id,
            knowledge_type_hint=knowledge_type_hint,
            provider=provider,
        )
        ku["provenance"]["chunk_id"] = chunk["chunk_id"]

        # 3. ku_gate_validate
        validation = ku_gate_validate(ku=ku)
        if validation["valid"]:
            candidates.append(ku)
        else:
            rejected.append({"ku": ku, "errors": validation["errors"]})

    return {
        "candidates": candidates,
        "rejected": rejected,
        "chunks_processed": len(chunks),
    }
