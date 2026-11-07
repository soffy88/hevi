"""Tests for K-ONT-1: ontology_extract."""

from __future__ import annotations

import json

import pytest
from oprim._aii_graph_types import (
    VALID_KNOWLEDGE_TYPES,
    VALID_RELATION_TYPES,
    OntologyExtractResult,
)

from oskill._ontology_extract import ontology_extract

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _llm_sequence(*responses):
    """Mock LLM that returns responses in sequence (then repeats last)."""
    idx = [0]

    async def llm(*, messages, system=None, max_tokens=512, **kw):
        i = min(idx[0], len(responses) - 1)
        idx[0] += 1
        text = json.dumps(responses[i]) if isinstance(responses[i], (dict, list)) else responses[i]
        return {"content": [{"type": "text", "text": text}], "usage": {}}

    return llm


def _const_llm(response):
    """Mock LLM returning the same response for every call."""

    async def llm(*, messages, system=None, max_tokens=512, **kw):
        text = json.dumps(response) if isinstance(response, (dict, list)) else response
        return {"content": [{"type": "text", "text": text}], "usage": {}}

    return llm


# Dummy prompts for tests (v4: prompts are required injected params)
_P1_CHUNK = "Analyze chunk: {chunk_text}"
_P1_CHUNK_SYS = "You are an analyst. JSON only."
_P1_OUTLINE = "Synthesize {chunk_analyses} doc={doc_type} cred={source_credibility}"
_P1_OUTLINE_SYS = "You are an architect. JSON only."
_P2_CHUNK = "Extract KUs. Outline: {outline}. Text: {chunk_text}"
_P2_SYS = "You are a KU extractor. JSON only."


async def _extract(**kwargs):
    """Wrap ontology_extract with dummy prompts so tests inject only what they vary."""
    defaults = dict(
        pass1_chunk_tmpl=_P1_CHUNK,
        pass1_chunk_system=_P1_CHUNK_SYS,
        pass1_outline_tmpl=_P1_OUTLINE,
        pass1_outline_system=_P1_OUTLINE_SYS,
        pass2_chunk_tmpl=_P2_CHUNK,
        pass2_system=_P2_SYS,
    )
    defaults.update(kwargs)
    return await ontology_extract(**defaults)


_CHUNK_ANALYSIS = {"concepts": ["gravity"], "topics": ["physics"], "chapter": "Ch1"}
_OUTLINE = {
    "chapters": ["Ch1"],
    "core_concepts": ["gravity"],
    "main_thread": "Newtonian mechanics",
    "stance": "objective",
    "doc_type": "textbook",
    "source_credibility": "high",
}
_KU_FACTUAL = {
    "ku_candidates": [
        {
            "id": "t1",
            "title": "Newton's Law",
            "content": "F=ma",
            "knowledge_type": "factual",
            "grade": "unverified",
            "sub_type": None,
            "stance_holder": None,
            "example": None,
            "concepts": ["force"],
        }
    ],
    "edge_candidates": [],
    "concept_candidates": ["force"],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOntologyExtract:
    async def test_returns_ontology_extract_result(self):
        llm = _llm_sequence(_CHUNK_ANALYSIS, _OUTLINE, _KU_FACTUAL)
        result = await _extract(
            source_text="Force equals mass times acceleration.",
            llm=llm,
        )
        assert isinstance(result, OntologyExtractResult)
        assert isinstance(result.outline, dict)
        assert isinstance(result.ku_candidates, list)
        assert isinstance(result.edge_candidates, list)
        assert isinstance(result.stats, dict)

    async def test_grade_always_unverified(self):
        # LLM tries to set grade="verified" — must be overridden
        ku_with_bad_grade = {
            "ku_candidates": [
                {
                    "id": "t1",
                    "title": "T",
                    "content": "C",
                    "knowledge_type": "factual",
                    "grade": "verified",
                    "sub_type": None,
                    "stance_holder": None,
                    "example": None,
                    "concepts": [],
                }
            ],
            "edge_candidates": [],
            "concept_candidates": [],
        }
        llm = _llm_sequence(_CHUNK_ANALYSIS, _OUTLINE, ku_with_bad_grade)
        result = await _extract(source_text="Some text.", llm=llm)
        for ku in result.ku_candidates:
            assert ku["grade"] == "unverified", f"grade must be unverified, got {ku['grade']!r}"

    async def test_invalid_relation_type_discarded(self):
        ku_data = {
            "ku_candidates": [],
            "edge_candidates": [
                {"source": "a", "target": "b", "relation_type": "invalid_type"},
                {"source": "a", "target": "b", "relation_type": "explains"},  # valid
            ],
            "concept_candidates": [],
        }
        llm = _llm_sequence(_CHUNK_ANALYSIS, _OUTLINE, ku_data)
        result = await _extract(source_text="Some text.", llm=llm)
        for edge in result.edge_candidates:
            assert edge["relation_type"] in VALID_RELATION_TYPES

    async def test_positional_without_stance_holder_dropped(self):
        ku_data = {
            "ku_candidates": [
                # positional without stance_holder → dropped
                {
                    "id": "t1",
                    "title": "Opinion",
                    "content": "...",
                    "knowledge_type": "positional",
                    "grade": "unverified",
                    "sub_type": None,
                    "stance_holder": None,
                    "example": None,
                    "concepts": [],
                },
                # positional WITH stance_holder → kept
                {
                    "id": "t2",
                    "title": "Stance",
                    "content": "...",
                    "knowledge_type": "positional",
                    "grade": "unverified",
                    "sub_type": None,
                    "stance_holder": "Author X",
                    "example": None,
                    "concepts": [],
                },
            ],
            "edge_candidates": [],
            "concept_candidates": [],
        }
        llm = _llm_sequence(_CHUNK_ANALYSIS, _OUTLINE, ku_data)
        result = await _extract(source_text="Author X argues that...", llm=llm)
        # Only the one with stance_holder should survive
        positional = [k for k in result.ku_candidates if k.get("knowledge_type") == "positional"]
        for ku in positional:
            assert ku.get("stance_holder"), "positional KU must have stance_holder"

    async def test_explanatory_ku_with_explains_edge(self):
        ku_data = {
            "ku_candidates": [
                {
                    "id": "t1",
                    "title": "Why gravity works",
                    "content": "Curvature of spacetime",
                    "knowledge_type": "explanatory",
                    "grade": "unverified",
                    "sub_type": None,
                    "stance_holder": None,
                    "example": None,
                    "concepts": ["gravity"],
                },
            ],
            "edge_candidates": [
                {"source": "t1", "target": "gravity", "relation_type": "explains"},
            ],
            "concept_candidates": [],
        }
        llm = _llm_sequence(_CHUNK_ANALYSIS, _OUTLINE, ku_data)
        result = await _extract(source_text="Gravity is explained by curvature.", llm=llm)
        explains_edges = [e for e in result.edge_candidates if e["relation_type"] == "explains"]
        assert len(explains_edges) >= 1
        assert result.stats["explains_count"] >= 1

    async def test_empty_text_returns_empty_result(self):
        llm = _const_llm({})
        result = await _extract(source_text="", llm=llm)
        assert result.ku_candidates == []
        assert result.edge_candidates == []
        assert result.stats["total"] == 0

    async def test_stats_by_type_counts_correctly(self):
        ku_data = {
            "ku_candidates": [
                {
                    "id": "t1",
                    "title": "A",
                    "content": "x",
                    "knowledge_type": "factual",
                    "grade": "unverified",
                    "sub_type": None,
                    "stance_holder": None,
                    "example": None,
                    "concepts": [],
                },
                {
                    "id": "t2",
                    "title": "B",
                    "content": "y",
                    "knowledge_type": "explanatory",
                    "grade": "unverified",
                    "sub_type": None,
                    "stance_holder": None,
                    "example": None,
                    "concepts": [],
                },
                {
                    "id": "t3",
                    "title": "C",
                    "content": "z",
                    "knowledge_type": "factual",
                    "grade": "unverified",
                    "sub_type": None,
                    "stance_holder": None,
                    "example": None,
                    "concepts": [],
                },
            ],
            "edge_candidates": [],
            "concept_candidates": [],
        }
        llm = _llm_sequence(_CHUNK_ANALYSIS, _OUTLINE, ku_data)
        result = await _extract(source_text="Some text.", llm=llm)
        assert result.stats["total"] == 3
        assert result.stats["by_type"].get("factual") == 2
        assert result.stats["by_type"].get("explanatory") == 1

    async def test_outline_contains_doc_type(self):
        llm = _llm_sequence(_CHUNK_ANALYSIS, _OUTLINE, _KU_FACTUAL)
        result = await _extract(source_text="Some text.", llm=llm, doc_type="textbook")
        assert result.outline is not None

    async def test_six_class_knowledge_types_accepted(self):
        six_kus = {
            "ku_candidates": [
                {
                    "id": f"t{i}",
                    "title": f"KU-{kt}",
                    "content": "...",
                    "knowledge_type": kt,
                    "grade": "unverified",
                    "sub_type": "principle" if kt == "conceptual" else None,
                    "stance_holder": "Someone" if kt == "positional" else None,
                    "example": None,
                    "concepts": [],
                }
                for i, kt in enumerate(
                    [
                        "factual",
                        "conceptual",
                        "positional",
                        "procedural",
                        "explanatory",
                        "metacognitive",
                    ]
                )
            ],
            "edge_candidates": [],
            "concept_candidates": [],
        }
        llm = _llm_sequence(_CHUNK_ANALYSIS, _OUTLINE, six_kus)
        result = await _extract(source_text="Some text.", llm=llm)
        found_types = {ku["knowledge_type"] for ku in result.ku_candidates}
        # all six types present
        assert found_types == VALID_KNOWLEDGE_TYPES

    async def test_grade_mandate_ci_assertion(self):
        # This test functions as the CI mandate: grade != "verified" after extraction
        ku_data = {
            "ku_candidates": [
                {
                    "id": "t1",
                    "title": "T",
                    "content": "C",
                    "knowledge_type": "factual",
                    "grade": "high",
                    "sub_type": None,
                    "stance_holder": None,
                    "example": None,
                    "concepts": [],
                }
            ],
            "edge_candidates": [],
            "concept_candidates": [],
        }
        llm = _llm_sequence(_CHUNK_ANALYSIS, _OUTLINE, ku_data)
        result = await _extract(source_text="Text.", llm=llm)
        for ku in result.ku_candidates:
            assert ku["grade"] == "unverified"
            assert ku["grade"] != "verified"

    async def test_concept_candidates_aggregated(self):
        ku_data = {
            "ku_candidates": [],
            "edge_candidates": [],
            "concept_candidates": ["alpha", "beta"],
        }
        llm = _llm_sequence(_CHUNK_ANALYSIS, _OUTLINE, ku_data)
        result = await _extract(source_text="alpha and beta are concepts.", llm=llm)
        assert "alpha" in result.concept_candidates
        assert "beta" in result.concept_candidates

    async def test_defect_b_invalid_subtype_coerced_to_null(self):
        # LLM returns invalid sub_type "definition" → must coerce to None, KU kept
        ku_data = {
            "ku_candidates": [
                {
                    "id": "t1",
                    "title": "Supply",
                    "content": "...",
                    "knowledge_type": "conceptual",
                    "grade": "unverified",
                    "sub_type": "definition",
                    "stance_holder": None,
                    "example": None,
                    "concepts": [],
                }
            ],
            "edge_candidates": [],
            "concept_candidates": [],
        }
        llm = _llm_sequence(_CHUNK_ANALYSIS, _OUTLINE, ku_data)
        result = await _extract(source_text="Supply is...", llm=llm)
        assert len(result.ku_candidates) == 1  # not dropped
        assert result.ku_candidates[0]["sub_type"] is None  # coerced

    async def test_defect_b_valid_subtype_kept(self):
        ku_data = {
            "ku_candidates": [
                {
                    "id": "t1",
                    "title": "Types",
                    "content": "...",
                    "knowledge_type": "conceptual",
                    "grade": "unverified",
                    "sub_type": "classification",
                    "stance_holder": None,
                    "example": None,
                    "concepts": [],
                }
            ],
            "edge_candidates": [],
            "concept_candidates": [],
        }
        llm = _llm_sequence(_CHUNK_ANALYSIS, _OUTLINE, ku_data)
        result = await _extract(source_text="Types of...", llm=llm)
        assert result.ku_candidates[0]["sub_type"] == "classification"

    async def test_defect_a_edge_endpoints_synced(self):
        # edge uses temp ids → must be rewritten to ku_c* ids
        ku_data = {
            "ku_candidates": [
                {
                    "id": "temp_1",
                    "title": "A",
                    "content": "...",
                    "knowledge_type": "conceptual",
                    "grade": "unverified",
                    "sub_type": None,
                    "stance_holder": None,
                    "example": None,
                    "concepts": [],
                },
                {
                    "id": "temp_2",
                    "title": "B",
                    "content": "...",
                    "knowledge_type": "explanatory",
                    "grade": "unverified",
                    "sub_type": None,
                    "stance_holder": None,
                    "example": None,
                    "concepts": [],
                },
            ],
            "edge_candidates": [
                {"source": "temp_2", "target": "temp_1", "relation_type": "explains"}
            ],
            "concept_candidates": [],
        }
        llm = _llm_sequence(_CHUNK_ANALYSIS, _OUTLINE, ku_data)
        result = await _extract(source_text="A and why B.", llm=llm)
        ku_ids = {ku["id"] for ku in result.ku_candidates}
        assert len(result.edge_candidates) == 1
        edge = result.edge_candidates[0]
        # endpoints must hit real KU ids, not temp_*
        assert edge["source"] in ku_ids
        assert edge["target"] in ku_ids
        assert not edge["source"].startswith("temp_")
        assert not edge["target"].startswith("temp_")

    async def test_prompts_are_required(self):
        # v4 breaking change: missing prompt params → TypeError
        llm = _const_llm(_KU_FACTUAL)
        with pytest.raises(TypeError):
            await ontology_extract(source_text="x", llm=llm)

    async def test_valid_types_injectable(self):
        # Custom vocab: "rationale" accepted; "explanatory" not in set → remapped to "factual"
        custom_vkt = frozenset(
            ["factual", "conceptual", "rationale", "positional", "procedural", "metacognitive"]
        )
        ku_data = {
            "ku_candidates": [
                {
                    "id": "t1",
                    "title": "Why X",
                    "content": "reason",
                    "knowledge_type": "rationale",
                    "grade": "unverified",
                    "sub_type": None,
                    "stance_holder": None,
                    "example": None,
                    "concepts": [],
                },
                {
                    "id": "t2",
                    "title": "Fact Y",
                    "content": "fact",
                    "knowledge_type": "explanatory",
                    "grade": "unverified",
                    "sub_type": None,
                    "stance_holder": None,
                    "example": None,
                    "concepts": [],
                },
            ],
            "edge_candidates": [],
            "concept_candidates": [],
        }
        llm = _llm_sequence(_CHUNK_ANALYSIS, _OUTLINE, ku_data)
        result = await _extract(
            source_text="Some text.",
            llm=llm,
            valid_knowledge_types=custom_vkt,
        )
        types = {ku["knowledge_type"] for ku in result.ku_candidates}
        # "rationale" passes through — it's in the custom vocab
        assert "rationale" in types
        # "explanatory" not in custom vocab → remapped to "factual"
        assert "explanatory" not in types
        assert "factual" in types
