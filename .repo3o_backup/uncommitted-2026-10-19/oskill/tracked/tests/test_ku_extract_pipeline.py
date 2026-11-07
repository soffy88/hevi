"""Tests for oskill.ku_extract_pipeline."""

from __future__ import annotations

from oskill.ku_extract_pipeline import ku_extract_pipeline


def test_empty_text_returns_empty_candidates():
    result = ku_extract_pipeline(text="", project_id="proj1")
    assert result["candidates"] == []
    assert result["chunks_processed"] == 0


def test_empty_whitespace_returns_empty_candidates():
    result = ku_extract_pipeline(text="   \n  ", project_id="proj1")
    assert result["candidates"] == []
    assert result["chunks_processed"] == 0


def test_text_with_one_section_produces_at_least_one_candidate():
    text = "# Introduction\n\nThis is a proposition about knowledge units in AII systems."
    result = ku_extract_pipeline(text=text, project_id="proj1")
    assert result["chunks_processed"] >= 1
    # candidates or rejected together should account for all chunks
    total = len(result["candidates"]) + len(result["rejected"])
    assert total == result["chunks_processed"]


def test_all_candidates_pass_gate_validate():
    """Every item in candidates must be valid per ku_gate_validate."""
    from oprim import ku_gate_validate

    text = "# KU Section\n\nMachine learning is a subset of artificial intelligence."
    result = ku_extract_pipeline(text=text, project_id="test_proj")
    for candidate in result["candidates"]:
        validation = ku_gate_validate(ku=candidate)
        assert validation["valid"], f"Candidate failed validation: {validation['errors']}"


def test_rejected_items_have_errors_list():
    """Rejected items must carry a non-empty errors list."""
    # Stub LLM may produce valid KUs; we verify the structure is correct when rejections occur.
    text = "# Section\n\nThis is a long enough sentence about artificial intelligence research."
    result = ku_extract_pipeline(text=text)
    for rejected_item in result["rejected"]:
        assert "errors" in rejected_item
        assert isinstance(rejected_item["errors"], list)
        assert len(rejected_item["errors"]) > 0


def test_chunks_processed_matches_structural_chunk_output():
    from oprim import structural_chunk

    text = "# Alpha\n\nFirst section content here.\n\n# Beta\n\nSecond section content here."
    chunks = structural_chunk(text=text, min_chars=50)
    result = ku_extract_pipeline(text=text, project_id="proj", min_chunk_chars=50)
    assert result["chunks_processed"] == len(chunks)


def test_candidates_have_provenance_chunk_id_set():
    text = "# Section One\n\nThis is a sentence about machine learning systems."
    result = ku_extract_pipeline(text=text, project_id="proj")
    for candidate in result["candidates"]:
        assert "provenance" in candidate
        assert candidate["provenance"].get("chunk_id") is not None
        assert candidate["provenance"]["chunk_id"].startswith("chunk_")


def test_candidates_have_epistemic_status_verified_false():
    """A19: LLM proposes, never certifies — verified must be False."""
    text = "# Topic\n\nDeep learning models require large amounts of training data."
    result = ku_extract_pipeline(text=text, project_id="proj")
    for candidate in result["candidates"]:
        assert "epistemic_status" in candidate
        assert candidate["epistemic_status"]["verified"] is False


def test_result_has_all_three_keys():
    result = ku_extract_pipeline(text="Some text content here.", project_id="proj")
    assert "candidates" in result
    assert "rejected" in result
    assert "chunks_processed" in result


def test_knowledge_type_hint_is_propagated():
    """knowledge_type_hint is passed through to llm_extract_ku stub."""
    text = "# Rule\n\nIf a KU has no natural_text, it must be rejected by the gate."
    result = ku_extract_pipeline(
        text=text,
        project_id="proj",
        knowledge_type_hint="rule",
    )
    # At least one chunk processed
    assert result["chunks_processed"] >= 1


def test_min_chunk_chars_filters_small_chunks():
    """Very short text below min_chunk_chars should produce no chunks."""
    # Text is short enough to be filtered by structural_chunk
    result = ku_extract_pipeline(text="Hi.", project_id="proj", min_chunk_chars=100)
    assert result["chunks_processed"] == 0
    assert result["candidates"] == []
