"""Tests for oskill.knowledge.classify_inbox_file."""

from __future__ import annotations

from unittest.mock import patch

from oskill.knowledge.classify_inbox_file import MEDIUMS, ClassifyResult, classify_inbox_file


class TestLayer1ExtensionClassifier:
    def test_epub_file(self, tmp_path):
        """EPUB → book with high confidence."""
        f = tmp_path / "book.epub"
        f.write_bytes(b"PK\x03\x04" + b"\x00" * 100)  # zip magic
        with patch("oprim.classifier.detect_mime.magic") as mock_magic:
            mock_magic.Magic.return_value.from_file.return_value = "application/epub+zip"
            with patch(
                "oskill.knowledge.classify_inbox_file.detect_mime",
                return_value="application/epub+zip",
            ):
                result = classify_inbox_file(f)
        assert result.medium == "book"
        assert result.confidence >= 0.85
        assert result.layer == "extension"

    def test_markdown_file(self, tmp_path):
        """Markdown file → markdown_note."""
        f = tmp_path / "note.md"
        f.write_text("# Title\n\nContent")
        with patch(
            "oskill.knowledge.classify_inbox_file.detect_mime", return_value="text/markdown"
        ):
            result = classify_inbox_file(f)
        assert result.medium == "markdown_note"
        assert result.confidence >= 0.85

    def test_html_file(self, tmp_path):
        f = tmp_path / "page.html"
        f.write_text("<html><body>Content</body></html>")
        with patch("oskill.knowledge.classify_inbox_file.detect_mime", return_value="text/html"):
            result = classify_inbox_file(f)
        assert result.medium == "webpage"
        assert result.confidence >= 0.85

    def test_csv_dataset(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("col1,col2\n1,2\n")
        with patch("oskill.knowledge.classify_inbox_file.detect_mime", return_value="text/csv"):
            result = classify_inbox_file(f)
        assert result.medium == "dataset"
        assert result.confidence >= 0.85

    def test_python_code(self, tmp_path):
        f = tmp_path / "script.py"
        f.write_text("print('hello')")
        with patch(
            "oskill.knowledge.classify_inbox_file.detect_mime", return_value="text/x-python"
        ):
            result = classify_inbox_file(f)
        assert result.medium == "code"

    def test_filename_prefix_hint_podcast(self, tmp_path):
        """podcast-- prefix → podcast at 0.98."""
        f = tmp_path / "podcast--episode-42.mp3"
        f.write_bytes(b"\xff\xfb" + b"\x00" * 50)
        with patch("oskill.knowledge.classify_inbox_file.detect_mime", return_value="audio/mpeg"):
            result = classify_inbox_file(f)
        assert result.medium == "podcast"
        assert result.confidence >= 0.95
        assert result.layer == "extension"

    def test_filename_prefix_hint_lecture(self, tmp_path):
        f = tmp_path / "lecture--ai-intro.mp4"
        f.write_bytes(b"\x00\x00\x00\x18" + b"\x00" * 50)
        with patch("oskill.knowledge.classify_inbox_file.detect_mime", return_value="video/mp4"):
            result = classify_inbox_file(f)
        assert result.medium == "lecture"
        assert result.confidence >= 0.95

    def test_audio_file_low_confidence(self, tmp_path):
        """Audio without prefix → candidates list, low confidence."""
        f = tmp_path / "audio.mp3"
        f.write_bytes(b"\xff\xfb" + b"\x00" * 50)
        with patch("oskill.knowledge.classify_inbox_file.detect_mime", return_value="audio/mpeg"):
            result = classify_inbox_file(f)
        assert result.candidates
        audio_mediums = {"podcast", "lecture", "audiobook", "music"}
        assert any(m in audio_mediums for m, _ in result.candidates)

    def test_pdf_starts_with_candidates(self, tmp_path, simple_pdf):
        """PDF → multiple paper/book candidates."""
        with patch(
            "oskill.knowledge.classify_inbox_file.detect_mime", return_value="application/pdf"
        ):
            with patch("oskill.knowledge.classify_inbox_file.detect_pdf_features") as mock_feat:
                from oprim.classifier.detect_pdf_features import PDFFeatures

                mock_feat.return_value = PDFFeatures(
                    page_count=5,
                    first_page_text="test",
                    has_cjk=False,
                    is_scanned=False,
                    has_tables=False,
                    is_two_column=False,
                )
                result = classify_inbox_file(simple_pdf)
        assert result.candidates
        pdf_mediums = {"paper", "book", "diagram", "webpage"}
        assert any(m in pdf_mediums for m, _ in result.candidates)


class TestLayer2HeuristicClassifier:
    def test_pdf_two_column_paper(self, tmp_path, simple_pdf):
        """Two-column PDF → paper."""
        with patch(
            "oskill.knowledge.classify_inbox_file.detect_mime", return_value="application/pdf"
        ):
            with patch("oskill.knowledge.classify_inbox_file.detect_pdf_features") as mock_feat:
                from oprim.classifier.detect_pdf_features import PDFFeatures

                mock_feat.return_value = PDFFeatures(
                    page_count=10,
                    first_page_text="abstract",
                    has_cjk=False,
                    is_scanned=False,
                    has_tables=True,
                    is_two_column=True,
                )
                result = classify_inbox_file(simple_pdf)
        assert result.medium == "paper"
        assert result.confidence >= 0.65

    def test_pdf_long_doc_book(self, tmp_path, simple_pdf):
        """Long PDF (>60 pages) → book."""
        with patch(
            "oskill.knowledge.classify_inbox_file.detect_mime", return_value="application/pdf"
        ):
            with patch("oskill.knowledge.classify_inbox_file.detect_pdf_features") as mock_feat:
                from oprim.classifier.detect_pdf_features import PDFFeatures

                mock_feat.return_value = PDFFeatures(
                    page_count=200,
                    first_page_text="chapter 1",
                    has_cjk=False,
                    is_scanned=False,
                    has_tables=False,
                    is_two_column=False,
                )
                result = classify_inbox_file(simple_pdf)
        assert result.medium == "book"
        assert result.confidence >= 0.65

    def test_image_with_exif_camera_photograph(self, tmp_path, simple_png):
        """Image with camera EXIF → photograph."""
        with patch("oskill.knowledge.classify_inbox_file.detect_mime", return_value="image/jpeg"):
            with patch("oskill.knowledge.classify_inbox_file.detect_image_exif") as mock_exif:
                from oprim.classifier.detect_image_exif import ImageExif

                mock_exif.return_value = ImageExif(
                    has_exif=True,
                    camera_make="Apple",
                    camera_model="iPhone 14 Pro",
                    datetime_taken=None,
                    width=3024,
                    height=4032,
                    is_screenshot_likely=False,
                )
                result = classify_inbox_file(simple_png)
        assert result.medium == "photograph"
        assert result.confidence >= 0.65

    def test_image_screenshot_heuristic(self, tmp_path, screen_png):
        """Screenshot PNG → diagram."""
        with patch("oskill.knowledge.classify_inbox_file.detect_mime", return_value="image/png"):
            with patch("oskill.knowledge.classify_inbox_file.detect_image_exif") as mock_exif:
                from oprim.classifier.detect_image_exif import ImageExif

                mock_exif.return_value = ImageExif(
                    has_exif=False,
                    camera_make=None,
                    camera_model=None,
                    datetime_taken=None,
                    width=1920,
                    height=1080,
                    is_screenshot_likely=True,
                )
                result = classify_inbox_file(screen_png)
        assert result.medium == "diagram"
        assert result.confidence >= 0.65

    def test_low_confidence_returns_needs_review(self, tmp_path):
        """Unrecognized binary → needs_review."""
        f = tmp_path / "unknown.bin"
        f.write_bytes(b"\x00\x01\x02\x03" * 20)
        with patch(
            "oskill.knowledge.classify_inbox_file.detect_mime",
            return_value="application/octet-stream",
        ):
            result = classify_inbox_file(f)
        assert result.layer == "needs_review" or result.confidence < 0.65

    def test_all_results_have_required_fields(self, tmp_path, simple_pdf):
        with patch(
            "oskill.knowledge.classify_inbox_file.detect_mime", return_value="application/pdf"
        ):
            with patch("oskill.knowledge.classify_inbox_file.detect_pdf_features") as mock_feat:
                from oprim.classifier.detect_pdf_features import PDFFeatures

                mock_feat.return_value = PDFFeatures(
                    page_count=5,
                    first_page_text="text",
                    has_cjk=False,
                    is_scanned=False,
                    has_tables=False,
                    is_two_column=False,
                )
                result = classify_inbox_file(simple_pdf)
        assert isinstance(result, ClassifyResult)
        assert result.layer in {"extension", "heuristic", "llm", "needs_review"}
        assert 0.0 <= result.confidence <= 1.0
        assert isinstance(result.candidates, list)

    def test_use_llm_false_no_llm_call(self, tmp_path):
        """use_llm=False must never call LLM."""
        f = tmp_path / "unknown.bin"
        f.write_bytes(b"\x00" * 100)
        with patch(
            "oskill.knowledge.classify_inbox_file.detect_mime",
            return_value="application/octet-stream",
        ):
            result = classify_inbox_file(f, use_llm=False)
        assert result.layer != "llm"

    def test_mediums_constant_has_18_entries(self):
        assert len(MEDIUMS) == 18
