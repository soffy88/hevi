"""Long-text translation: paragraph chunking -> per-chunk translation -> glossary QA.

Clean-room, original implementation. Design:

* Split the source by paragraphs, then greedily pack paragraphs into chunks
  of at most ``max_chars`` characters (a single over-long paragraph is split
  by sentences, then hard-sliced). Adjacent chunks hand the translator a
  small overlap of the previous chunk's tail as *context only* — overlap is
  never translated twice into the output.
* Translation itself is injectable: ``translate_fn(text, *, target_language,
  glossary, context) -> str``. The capability layer supplies the production
  (Monid-backed) implementation; tests pass fakes (offline, zero cost).
* Glossary post-check: for every ``source -> target`` glossary term whose
  source appears in the source text, the target term must appear in the
  translation. Misses are reported as warnings (in the report + qa), so a
  terminology drift is visible instead of silent.

Artifacts in ``out_dir``:
  translated.txt          译文全文
  bilingual.md            双语对照 (per segment: 原文 / 译文)
  bilingual.json          双语对照 (structured pairs)
  translation_report.json 分块 / 字符数 / 术语报警台账
文档级长文翻译（整篇文本→双语对照文档）；视频字幕段级译制走 hevi/production/media_workflows.video_localization_workflow（后端 voicepro_translate），两者勿混用。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

__all__ = [
    "LongTranslateError",
    "check_glossary",
    "split_into_chunks",
    "translate_long",
]

TranslateFn = Callable[..., str]

_SEPARATOR = "\n\n"


class LongTranslateError(RuntimeError):
    """A long-translation stage failed; no fake translation is produced."""


def _split_oversize(unit: str, max_chars: int) -> list[str]:
    """Split one over-long paragraph by sentences, then hard-slice."""
    sentences = [
        s for s in re.split(r"(?<=[。！？.!?])\s*", unit) if s.strip()
    ] or [unit]
    pieces: list[str] = []
    for sentence in sentences:
        if len(sentence) <= max_chars:
            pieces.append(sentence)
        else:
            pieces.extend(
                sentence[i : i + max_chars]
                for i in range(0, len(sentence), max_chars)
            )
    return pieces


def split_into_chunks(text: str, *, max_chars: int = 1800) -> list[str]:
    """Pack ``text`` into chunks of at most ``max_chars`` characters.

    Paragraphs (blank-line separated) are the packing units; a paragraph
    longer than ``max_chars`` is first split into sentence-sized units.
    Chunk boundaries never cut a unit, and joining all chunks with a blank
    line preserves every unit exactly once.
    """
    if not isinstance(max_chars, int) or max_chars < 50:
        raise LongTranslateError("max_chars must be an integer >= 50")
    stripped = (text or "").strip()
    if not stripped:
        raise LongTranslateError("text is empty, nothing to translate")
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", stripped) if p.strip()]
    units: list[str] = []
    for para in paragraphs:
        if len(para) <= max_chars:
            units.append(para)
        else:
            units.extend(_split_oversize(para, max_chars))
    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = unit if not current else current + _SEPARATOR + unit
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = unit
    if current:
        chunks.append(current)
    return chunks


def check_glossary(
    source_text: str,
    translated_text: str,
    glossary: dict[str, str] | None,
) -> list[dict[str, str]]:
    """Return glossary warnings: source term present, target term missing."""
    warnings: list[dict[str, str]] = []
    if not glossary:
        return warnings
    source_low = source_text.lower()
    translated_low = translated_text.lower()
    for src, tgt in glossary.items():
        src_s, tgt_s = str(src).strip(), str(tgt).strip()
        if not src_s or not tgt_s:
            continue
        if src_s.lower() in source_low and tgt_s.lower() not in translated_low:
            warnings.append(
                {
                    "type": "missing_target_term",
                    "source_term": src_s,
                    "target_term": tgt_s,
                    "detail": (
                        f"glossary term {src_s!r} appears in the source but its "
                        f"required translation {tgt_s!r} is missing from the output"
                    ),
                }
            )
    return warnings


def translate_long(
    *,
    text: str | None = None,
    input_path: str | Path | None = None,
    target_language: str,
    source_language: str = "auto",
    glossary: dict[str, str] | None = None,
    out_dir: str | Path,
    translate_fn: TranslateFn | None,
    max_chars: int = 1800,
    overlap_chars: int = 200,
) -> dict[str, Any]:
    """Translate a long text in chunks; write all artifacts to ``out_dir``.

    Returns the translation report (also ``translation_report.json``).
    Raises :class:`LongTranslateError` on invalid input or a failed chunk.
    """
    if text is not None and input_path is not None:
        raise LongTranslateError("pass either text or input_path, not both")
    if input_path is not None:
        path = Path(input_path)
        if not path.is_file():
            raise LongTranslateError(f"input file not found: {path}")
        source_text = path.read_text(encoding="utf-8")
    elif text is not None:
        source_text = str(text)
    else:
        raise LongTranslateError("either text or input_path is required")
    if not source_text.strip():
        raise LongTranslateError("source text is empty, nothing to translate")
    target_language = str(target_language or "").strip()
    if not target_language:
        raise LongTranslateError("target_language is required")
    if translate_fn is None or not callable(translate_fn):
        raise LongTranslateError("translate_fn is required and must be callable")
    if glossary is not None and (
        not isinstance(glossary, dict)
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in glossary.items())
    ):
        raise LongTranslateError("glossary must be a dict of str -> str")
    if not isinstance(overlap_chars, int) or overlap_chars < 0:
        raise LongTranslateError("overlap_chars must be an integer >= 0")
    chunks = split_into_chunks(source_text, max_chars=max_chars)
    if overlap_chars >= max_chars:
        raise LongTranslateError("overlap_chars must be smaller than max_chars")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    pairs: list[dict[str, Any]] = []
    translated_chunks: list[str] = []
    previous_source = ""
    for index, chunk in enumerate(chunks):
        context = previous_source[-overlap_chars:] if overlap_chars and previous_source else ""
        try:
            translated = translate_fn(
                chunk,
                target_language=target_language,
                glossary=dict(glossary or {}),
                context=context,
            )
        except LongTranslateError:
            raise
        except Exception as exc:
            raise LongTranslateError(
                f"translation failed on chunk {index + 1}/{len(chunks)}: {exc}"
            ) from exc
        translated = str(translated or "").strip()
        if not translated:
            raise LongTranslateError(
                f"translate_fn returned an empty translation for chunk {index + 1}"
            )
        translated_chunks.append(translated)
        pairs.append(
            {"index": index, "source": chunk, "translation": translated}
        )
        previous_source = chunk

    translated_full = _SEPARATOR.join(translated_chunks)
    warnings = check_glossary(source_text, translated_full, glossary)

    files: dict[str, str] = {}

    def _write(name: str, content: str) -> str:
        path = out / name
        path.write_text(content, encoding="utf-8")
        files[name] = str(path)
        return str(path)

    _write("translated.txt", translated_full + "\n")

    bilingual = {
        "source_language": source_language,
        "target_language": target_language,
        "glossary": dict(glossary or {}),
        "pairs": pairs,
    }
    _write("bilingual.json", json.dumps(bilingual, ensure_ascii=False, indent=1))

    md_lines = [
        f"# 双语对照 ({source_language} -> {target_language})",
        "",
    ]
    for pair in pairs:
        md_lines += [
            f"## Segment {pair['index'] + 1}",
            "",
            "**原文**",
            "",
            pair["source"],
            "",
            "**译文**",
            "",
            pair["translation"],
            "",
        ]
    _write("bilingual.md", "\n".join(md_lines))

    report: dict[str, Any] = {
        "kind": "long_translation",
        "source_language": source_language,
        "target_language": target_language,
        "chunk_count": len(chunks),
        "max_chars": max_chars,
        "overlap_chars": overlap_chars,
        "source_chars": len(source_text),
        "translated_chars": len(translated_full),
        "glossary_terms": len(glossary or {}),
        "glossary_warnings": warnings,
        "glossary_ok": not warnings,
        "files": files,
        "bilingual": bilingual,
    }
    _write("translation_report.json", json.dumps(
        {k: v for k, v in report.items() if k != "bilingual"},
        ensure_ascii=False, indent=1,
    ))
    report["files"] = files
    return report
