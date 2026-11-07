"""Tests for generate_derivative."""

from __future__ import annotations

from unittest.mock import patch

from oskill.knowledge.generate_derivative import generate_derivative


class TestGenerateDerivative:
    async def test_pdf_returns_markdown_and_plaintext(self, tmp_path, simple_pdf):
        result = await generate_derivative("sub01", simple_pdf, "paper")
        assert "markdown" in result
        assert "plaintext" in result
        assert len(result["markdown"]) > 0

    async def test_markdown_note(self, tmp_path, simple_md):
        result = await generate_derivative("sub02", simple_md, "markdown_note")
        assert "markdown" in result
        assert "plaintext" in result
        assert "Test Note" in result["markdown"]

    async def test_html_webpage(self, tmp_path, simple_html):
        result = await generate_derivative("sub03", simple_html, "webpage")
        assert "markdown" in result

    async def test_image_returns_thumbnail_path(self, tmp_path, simple_png):
        result = await generate_derivative("sub04", simple_png, "photograph")
        assert "thumbnail_path" in result
        assert result["thumbnail_path"] == str(simple_png)

    async def test_unsupported_medium_returns_empty(self, tmp_path, simple_txt):
        result = await generate_derivative("sub05", simple_txt, "podcast")
        assert result == {}  # audio not parseable in Phase 1

    async def test_pdf_parse_failure_logs_not_raises(self, tmp_path):
        """PDF parse failure should log warning, not raise."""
        bad_pdf = tmp_path / "bad.pdf"
        bad_pdf.write_bytes(b"not a pdf")
        result = await generate_derivative("sub06", bad_pdf, "paper")
        # Should return empty dict or partial — not raise
        assert isinstance(result, dict)

    async def test_returns_chapters_for_structured_pdf(self, tmp_path, simple_pdf):
        """If PDF has TOC, chapters should be present."""
        with patch("oskill.knowledge.generate_derivative.parse_pdf") as mock_parse:
            from oprim.parser.parse_pdf import ParsedContent

            mock_parse.return_value = ParsedContent(
                markdown="# Chapter 1\n\nContent",
                plaintext="Chapter 1 Content",
                page_count=10,
                chapters=[{"title": "Chapter 1", "page": 1}],
                parser_name="pymupdf4llm",
                parse_quality_score=0.9,
            )
            result = await generate_derivative("sub07", simple_pdf, "paper")
        assert "chapters" in result
        import json

        chapters = json.loads(result["chapters"])
        assert len(chapters) > 0
