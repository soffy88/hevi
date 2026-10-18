"""Layer 1+2 three-tier file classifier. Layer 3 (LLM) not implemented in Phase 1."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from oprim._logging import log
from oprim.classifier.detect_image_exif import detect_image_exif
from oprim.classifier.detect_mime import detect_mime
from oprim.classifier.detect_pdf_features import detect_pdf_features

MEDIUMS = frozenset(
    [
        "paper",
        "book",
        "markdown_note",
        "webpage",
        "podcast",
        "lecture",
        "audiobook",
        "music",
        "video_lecture",
        "interview",
        "documentary",
        "photograph",
        "diagram",
        "artwork",
        "dataset",
        "code",
        "email",
        "other",
    ]
)

# filename prefix hints: if filename starts with "{medium}--", use that medium at 0.98 confidence
_PREFIX_RE = re.compile(r"^([a-z_]+)--", re.IGNORECASE)


@dataclass
class ClassifyResult:
    medium: str | None
    confidence: float
    layer: Literal["extension", "heuristic", "llm", "needs_review"]
    reason: str
    candidates: list[tuple[str, float]] = field(default_factory=list)


def classify_inbox_file(path: Path, use_llm: bool = False) -> ClassifyResult:
    """Three-layer file classifier. Layer 3 (LLM) not implemented in Phase 1."""
    layer1 = _classify_by_extension(path)
    if layer1.confidence >= 0.85:
        log.info(
            "oskill.classify.layer1_hit",
            path=str(path),
            medium=layer1.medium,
            conf=layer1.confidence,
        )
        return layer1

    layer2 = _classify_by_heuristic(path, layer1)
    if layer2.confidence >= 0.65:
        log.info(
            "oskill.classify.layer2_hit",
            path=str(path),
            medium=layer2.medium,
            conf=layer2.confidence,
        )
        return layer2

    if use_llm:
        # Phase 10: LLM classification
        raise NotImplementedError("LLM classification not implemented in Phase 1")

    log.warning("oskill.classify.needs_review", path=str(path), candidates=layer2.candidates[:3])
    return ClassifyResult(
        medium=None,
        confidence=layer2.confidence,
        layer="needs_review",
        reason=(
            f"low confidence ({layer2.confidence:.2f}); "
            f"best: {layer2.candidates[0][0] if layer2.candidates else 'none'}"
        ),
        candidates=layer2.candidates,
    )


def _classify_by_extension(path: Path) -> ClassifyResult:
    """Layer 1: MIME detection + filename prefix hints."""
    # Prefix hint (highest priority)
    m = _PREFIX_RE.match(path.name)
    if m:
        prefix = m.group(1).lower()
        if prefix in MEDIUMS:
            return ClassifyResult(
                medium=prefix,
                confidence=0.98,
                layer="extension",
                reason=f"filename prefix hint: {prefix}",
                candidates=[(prefix, 0.98)],
            )

    # Extension-based short-circuit before MIME detection:
    # detect_mime() sees .epub as generic application/zip (EPUB is a ZIP container),
    # so the mime == "application/epub+zip" branch below never fires.
    ext = path.suffix.lower()
    if ext == ".epub":
        return ClassifyResult(
            medium="book",
            confidence=0.93,
            layer="extension",
            reason=".epub extension (detect_mime returns application/zip for EPUBs)",
            candidates=[("book", 0.93)],
        )

    # Same short-circuit for markdown: detect_mime() reports .md as text/plain,
    # which only scores markdown_note at 0.50 → falls below the 0.65 threshold →
    # medium becomes "other" → no derivative content is generated.
    if ext in {".md", ".markdown"}:
        return ClassifyResult(
            medium="markdown_note",
            confidence=0.95,
            layer="extension",
            reason=".md extension (detect_mime returns text/plain for markdown)",
            candidates=[("markdown_note", 0.95)],
        )

    mime = detect_mime(path)

    if mime.startswith("audio/"):
        ext = path.suffix.lower()
        if ext in {".mp3", ".m4a", ".wav", ".flac", ".ogg"}:
            candidates = [
                ("podcast", 0.55),
                ("lecture", 0.25),
                ("audiobook", 0.15),
                ("music", 0.05),
            ]
        else:
            candidates = [("podcast", 0.5), ("lecture", 0.3), ("audiobook", 0.15), ("music", 0.05)]
        return ClassifyResult(
            medium=None,
            confidence=0.55,
            layer="extension",
            reason=f"audio/* MIME: {mime}",
            candidates=candidates,
        )

    if mime.startswith("video/"):
        candidates = [("video_lecture", 0.5), ("interview", 0.3), ("documentary", 0.2)]
        return ClassifyResult(
            medium=None,
            confidence=0.5,
            layer="extension",
            reason=f"video/* MIME: {mime}",
            candidates=candidates,
        )

    if mime.startswith("image/"):
        candidates = [("photograph", 0.6), ("diagram", 0.3), ("artwork", 0.1)]
        return ClassifyResult(
            medium=None,
            confidence=0.6,
            layer="extension",
            reason=f"image/* MIME: {mime}",
            candidates=candidates,
        )

    if mime == "application/pdf":
        candidates = [("paper", 0.5), ("book", 0.25), ("diagram", 0.15), ("webpage", 0.1)]
        return ClassifyResult(
            medium=None,
            confidence=0.5,
            layer="extension",
            reason="application/pdf MIME",
            candidates=candidates,
        )

    if mime == "application/epub+zip":
        return ClassifyResult(
            medium="book",
            confidence=0.95,
            layer="extension",
            reason="application/epub+zip MIME",
            candidates=[("book", 0.95)],
        )

    if mime in {"text/markdown", "text/x-markdown"}:
        return ClassifyResult(
            medium="markdown_note",
            confidence=0.9,
            layer="extension",
            reason=f"{mime} MIME",
            candidates=[("markdown_note", 0.9)],
        )

    if mime == "text/html":
        return ClassifyResult(
            medium="webpage",
            confidence=0.85,
            layer="extension",
            reason="text/html MIME",
            candidates=[("webpage", 0.85)],
        )

    if mime in {"text/csv", "application/json", "application/x-ndjson"}:
        return ClassifyResult(
            medium="dataset",
            confidence=0.9,
            layer="extension",
            reason=f"{mime} MIME",
            candidates=[("dataset", 0.9)],
        )

    # Code files by extension
    code_exts = {
        ".py",
        ".js",
        ".ts",
        ".java",
        ".cpp",
        ".c",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".sh",
        ".bash",
        ".sql",
        ".yaml",
        ".yml",
        ".toml",
        ".json",
        ".xml",
    }
    if path.suffix.lower() in code_exts:
        return ClassifyResult(
            medium="code",
            confidence=0.95,
            layer="extension",
            reason=f"code extension {path.suffix}",
            candidates=[("code", 0.95)],
        )

    if mime.startswith("text/"):
        return ClassifyResult(
            medium="markdown_note",
            confidence=0.5,
            layer="extension",
            reason=f"text/* MIME fallback: {mime}",
            candidates=[("markdown_note", 0.5), ("code", 0.3), ("other", 0.2)],
        )

    return ClassifyResult(
        medium="other",
        confidence=0.3,
        layer="extension",
        reason=f"unrecognized MIME: {mime}",
        candidates=[("other", 0.3)],
    )


def _classify_by_heuristic(path: Path, layer1: ClassifyResult) -> ClassifyResult:
    """Layer 2: content-based heuristics using oprim classifiers."""
    candidates = list(layer1.candidates)
    top_medium = candidates[0][0] if candidates else "other"

    # PDF heuristics
    if any(
        m == top_medium for m, _ in candidates[:2] if m in {"paper", "book", "diagram", "webpage"}
    ):
        try:
            features = detect_pdf_features(path)
            if features.page_count > 60:
                # Long doc → book
                candidates = _boost(candidates, "book", 0.75)
            elif features.is_two_column and not features.has_cjk:
                # Two-column, non-CJK → academic paper
                candidates = _boost(candidates, "paper", 0.80)
            elif features.has_tables and features.page_count <= 20:
                # Short with tables → paper or webpage
                candidates = _boost(candidates, "paper", 0.70)
            else:
                candidates = _boost(candidates, "paper", 0.65)
        except Exception as e:
            log.warning("oskill.classify.pdf_features_failed", error=str(e))

    # Image heuristics
    elif any(
        m == top_medium for m, _ in candidates[:2] if m in {"photograph", "diagram", "artwork"}
    ):
        try:
            exif = detect_image_exif(path)
            if exif.has_exif and exif.camera_make:
                candidates = _boost(candidates, "photograph", 0.88)
            elif exif.is_screenshot_likely:
                candidates = _boost(candidates, "diagram", 0.72)
        except Exception as e:
            log.warning("oskill.classify.exif_failed", error=str(e))

    top_medium, top_conf = candidates[0]
    return ClassifyResult(
        medium=top_medium if top_conf >= 0.65 else None,
        confidence=top_conf,
        layer="heuristic",
        reason=f"heuristic classification: {top_medium} ({top_conf:.2f})",
        candidates=candidates,
    )


def _boost(
    candidates: list[tuple[str, float]], medium: str, conf: float
) -> list[tuple[str, float]]:
    """Return new candidates list with given medium boosted to conf."""
    others = [(m, s * (1 - conf)) for m, s in candidates if m != medium]
    return sorted([(medium, conf)] + others, key=lambda x: x[1], reverse=True)
