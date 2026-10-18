"""Tests for oskill.image_qa."""

from __future__ import annotations

from unittest.mock import patch

from oskill.image_qa import image_qa

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_IMAGE = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64  # minimal fake PNG bytes

_OCR_RESULT_EMPTY = {
    "text": "",
    "confidence": None,
    "language": "eng",
    "provider_used": "stub",
    "error": None,
}

_OCR_RESULT_WITH_TEXT = {
    "text": "Hello World",
    "confidence": 0.9,
    "language": "eng",
    "provider_used": "tesseract",
    "error": None,
}

_CONCEPT_RESULT = {
    "concepts": ["Vision", "Image", "Answer"],
    "count": 3,
    "provider_used": "default",
    "error": None,
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_returns_dict_with_all_required_keys():
    """Result dict must contain all six required keys."""
    with (
        patch("oskill.image_qa.ocr_detect_text", return_value=_OCR_RESULT_EMPTY),
        patch("oskill.image_qa.concept_extractor", return_value=_CONCEPT_RESULT),
    ):
        out = image_qa(image_bytes=_FAKE_IMAGE, question="What is this?")
    assert set(out.keys()) >= {
        "answer",
        "ocr_text",
        "concepts",
        "confidence",
        "provider_used",
        "error",
    }


def test_ocr_text_comes_from_ocr_detect_text():
    """ocr_text field must carry text returned by ocr_detect_text stub."""
    with (
        patch("oskill.image_qa.ocr_detect_text", return_value=_OCR_RESULT_WITH_TEXT),
        patch("oskill.image_qa.concept_extractor", return_value=_CONCEPT_RESULT),
    ):
        out = image_qa(image_bytes=_FAKE_IMAGE, question="Read the text")
    assert out["ocr_text"] == "Hello World"


def test_concepts_extracted_from_answer():
    """concepts list is populated when extract_concepts=True."""
    with (
        patch("oskill.image_qa.ocr_detect_text", return_value=_OCR_RESULT_EMPTY),
        patch("oskill.image_qa.concept_extractor", return_value=_CONCEPT_RESULT),
    ):
        out = image_qa(
            image_bytes=_FAKE_IMAGE, question="Describe the scene", extract_concepts=True
        )
    assert isinstance(out["concepts"], list)
    assert len(out["concepts"]) > 0


def test_answer_is_non_empty_string():
    """answer field must be a non-empty string (from stub)."""
    with (
        patch("oskill.image_qa.ocr_detect_text", return_value=_OCR_RESULT_EMPTY),
        patch("oskill.image_qa.concept_extractor", return_value=_CONCEPT_RESULT),
    ):
        out = image_qa(image_bytes=_FAKE_IMAGE, question="What do you see?")
    assert isinstance(out["answer"], str)
    assert len(out["answer"]) > 0


def test_error_none_on_success():
    """error is None when all oprim calls succeed."""
    with (
        patch("oskill.image_qa.ocr_detect_text", return_value=_OCR_RESULT_EMPTY),
        patch("oskill.image_qa.concept_extractor", return_value=_CONCEPT_RESULT),
    ):
        out = image_qa(image_bytes=_FAKE_IMAGE, question="Is there a cat?")
    assert out["error"] is None


def test_extract_concepts_false_returns_empty_list():
    """When extract_concepts=False, concepts must be []."""
    with (
        patch("oskill.image_qa.ocr_detect_text", return_value=_OCR_RESULT_EMPTY),
        patch("oskill.image_qa.concept_extractor", return_value=_CONCEPT_RESULT) as mock_ce,
    ):
        out = image_qa(image_bytes=_FAKE_IMAGE, question="Any text?", extract_concepts=False)
    assert out["concepts"] == []
    mock_ce.assert_not_called()


def test_image_bytes_parameter_accepted():
    """Function must accept image_bytes of any non-zero length."""
    large_bytes = b"\xff" * 1024
    with (
        patch("oskill.image_qa.ocr_detect_text", return_value=_OCR_RESULT_EMPTY),
        patch("oskill.image_qa.concept_extractor", return_value=_CONCEPT_RESULT),
    ):
        out = image_qa(image_bytes=large_bytes, question="Anything?")
    assert out["error"] is None


def test_provider_used_field_present():
    """provider_used key must be in the result dict."""
    with (
        patch("oskill.image_qa.ocr_detect_text", return_value=_OCR_RESULT_EMPTY),
        patch("oskill.image_qa.concept_extractor", return_value=_CONCEPT_RESULT),
    ):
        out = image_qa(image_bytes=_FAKE_IMAGE, question="Provider check", provider="gpt4v")
    assert "provider_used" in out
    assert out["provider_used"] == "gpt4v"


def test_ocr_error_propagates():
    """When ocr_detect_text returns an error, result carries that error."""
    err_ocr = {**_OCR_RESULT_EMPTY, "error": "ocr_failed", "provider_used": "tesseract"}
    with patch("oskill.image_qa.ocr_detect_text", return_value=err_ocr):
        out = image_qa(image_bytes=_FAKE_IMAGE, question="Will error?")
    assert out["error"] == "ocr_failed"
