"""Local OCR based subtitle readability gate.

Uses the pre-installed ``rapidocr_onnxruntime`` (shared venv) to read the
burned-in caption from a frame and compare it with the expected narration.  No
network access, no new dependency.

3O Pillar: oprim.comicnarr_subtitle_ocr
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

import numpy as np

_OCR_ENGINE = None
_PUNCT_RE = re.compile(r"[\s，。！？、；：…,.!?;:\"'“”‘’（）()\[\]【】—\-]+")


def _get_ocr():
    """Lazily construct the shared RapidOCR engine (heavy import)."""
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def normalize_text(text: str) -> str:
    """Strip whitespace / punctuation for tolerant comparison."""
    return _PUNCT_RE.sub("", text or "")


def ocr_text(image: np.ndarray | str | Path) -> str:
    """Return the concatenated OCR text of an image (BGR array or path)."""
    engine = _get_ocr()
    result, _elapse = engine(image)
    if not result:
        return ""
    parts = [str(item[1]) for item in result if len(item) >= 2 and item[1]]
    return "".join(parts)


def text_similarity(a: str, b: str) -> float:
    """Character-level similarity ratio in [0, 1] on normalized text."""
    na, nb = normalize_text(a), normalize_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def subtitle_region(frame_bgr: np.ndarray, top_frac: float = 0.60) -> np.ndarray:
    """Crop the lower part of a frame where burned subtitles live."""
    h = frame_bgr.shape[0]
    return frame_bgr[int(h * top_frac) : h, :]


def measure_subtitle_readability(
    frame_bgr: np.ndarray,
    expected_narration: str,
    *,
    top_frac: float = 0.60,
) -> dict:
    """OCR the subtitle band of a frame and score it against the narration."""
    crop = subtitle_region(frame_bgr, top_frac=top_frac)
    text = ocr_text(crop)
    sim = text_similarity(text, expected_narration)
    exp_norm = normalize_text(expected_narration)
    coverage = len(normalize_text(text)) / max(1, len(exp_norm))
    return {
        "ocr_text": text,
        "expected": expected_narration,
        "similarity": round(sim, 4),
        "coverage": round(min(coverage, 1.0), 4),
        "readable": sim >= 0.6 and coverage >= 0.6,
    }


__all__ = [
    "measure_subtitle_readability",
    "normalize_text",
    "ocr_text",
    "subtitle_region",
    "text_similarity",
]
