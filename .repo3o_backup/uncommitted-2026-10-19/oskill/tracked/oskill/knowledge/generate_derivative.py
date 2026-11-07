"""Generate derivatives (markdown/plaintext/chapters/thumbnail) for a substrate."""

from __future__ import annotations

from pathlib import Path

from oprim._logging import log
from oprim.parser import parse_epub, parse_html, parse_pdf


async def generate_derivative(
    substrate_id: str,
    path: Path,
    medium: str,
) -> dict[str, str]:
    """Generate derivatives for a substrate.

    Returns dict with keys: markdown, plaintext, chapters (JSON str), thumbnail_path.
    Phase 1 scope: markdown, plaintext, chapters, thumbnail (PDF/image first page).
    Not in Phase 1: summary, key_quotes, entities, transcript.
    """
    result: dict[str, str] = {}

    if medium in {"paper", "book", "webpage"} and path.suffix.lower() == ".pdf":
        _parse_pdf_derivatives(path, result)

    elif medium == "book" and path.suffix.lower() in {".epub"}:
        _parse_epub_derivatives(path, result)

    elif medium == "markdown_note" and path.suffix.lower() in {".md", ".markdown"}:
        _parse_markdown_derivatives(path, result)

    elif medium == "webpage" and path.suffix.lower() in {".html", ".htm"}:
        _parse_html_derivatives(path, result)

    elif medium in {"photograph", "diagram", "artwork"}:
        result["thumbnail_path"] = str(path)  # image is its own thumbnail

    else:
        # Unsupported medium for Phase 1 parsing (audio/video/code/etc.)
        log.info(
            "oskill.generate_derivative.skipped",
            substrate_id=substrate_id,
            medium=medium,
            reason="medium not parseable in Phase 1",
        )

    log.info(
        "oskill.generate_derivative.done",
        substrate_id=substrate_id,
        medium=medium,
        keys=list(result.keys()),
    )
    return result


def _parse_pdf_derivatives(path: Path, result: dict) -> None:
    try:
        parsed = parse_pdf(path, provider="auto")
        result["markdown"] = parsed.markdown
        result["plaintext"] = parsed.plaintext
        if parsed.chapters:
            import json

            result["chapters"] = json.dumps(parsed.chapters)
    except Exception as e:
        log.warning("oskill.generate_derivative.pdf_failed", error=str(e))


def _parse_epub_derivatives(path: Path, result: dict) -> None:
    try:
        parsed = parse_epub(path)
        result["markdown"] = parsed.markdown
        result["plaintext"] = parsed.plaintext
        if parsed.chapters:
            import json

            result["chapters"] = json.dumps(parsed.chapters)
    except Exception as e:
        log.warning("oskill.generate_derivative.epub_failed", error=str(e))


def _parse_markdown_derivatives(path: Path, result: dict) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        result["markdown"] = text
        # Simple plaintext: strip markdown markers
        import re

        result["plaintext"] = re.sub(r"[#*`\[\]_]", "", text).strip()
    except Exception as e:
        log.warning("oskill.generate_derivative.md_failed", error=str(e))


def _parse_html_derivatives(path: Path, result: dict) -> None:
    try:
        content = path.read_bytes()
        parsed = parse_html(content)
        result["markdown"] = parsed.markdown
        result["plaintext"] = parsed.plaintext
    except Exception as e:
        log.warning("oskill.generate_derivative.html_failed", error=str(e))
