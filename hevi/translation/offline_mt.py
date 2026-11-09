"""Offline neural machine translation for subtitle localization.

The production text-LLM stack is the preferred translation path (see
``hevi.production.media_workflows._translate_with_hevi_llm``).  When every
registered cloud provider is unavailable this module supplies a *free, local*
fallback built on the Argos/OpenNMT CTranslate2 models that are already on the
host.  It deliberately talks to CTranslate2 and SentencePiece directly instead
of going through ``argostranslate.translate``, because Argos' public wrapper
loads a Stanza sentence splitter that stalls on an offline machine.

Models are discovered from (in order) ``$HEVI_OFFLINE_MT_DIR`` (colon separated
directories), ``~/.local/share/argos-translate/packages`` and
``/home/soffy/.local/share/argos-translate/packages``.  A package is a
directory named ``translate-<from>_<to>-<version>`` holding ``model/`` (a
CTranslate2 model) and ``sentencepiece.model``.

The public entry point is :func:`translate_with_check`, which applies a
glossary, translates, back-translates and returns a deterministic self-check so
callers can record whether the result is trustworthy rather than assuming it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_ASCII_WORD = re.compile(r"[A-Za-z]{4,}")
_SENTINEL = "ZZG{n}ZZ"


def _norm(code: str) -> str:
    code = (code or "").strip().lower().replace("_", "-")
    if code.startswith("zh"):
        return "zh"
    if code.startswith("en"):
        return "en"
    return code.split("-")[0]


def _candidate_roots() -> list[Path]:
    roots: list[Path] = []
    env = os.environ.get("HEVI_OFFLINE_MT_DIR", "")
    roots.extend(Path(part).expanduser() for part in env.split(os.pathsep) if part.strip())
    roots.append(Path.home() / ".local" / "share" / "argos-translate" / "packages")
    roots.append(Path("/home/soffy/.local/share/argos-translate/packages"))
    roots.append(Path("/models/argos"))
    seen: set[Path] = set()
    out: list[Path] = []
    for root in roots:
        if root not in seen:
            seen.add(root)
            out.append(root)
    return out


def _find_package(from_lang: str, to_lang: str) -> Path | None:
    src, dst = _norm(from_lang), _norm(to_lang)
    pattern = re.compile(rf"^translate-{re.escape(src)}_{re.escape(dst)}-")
    for root in _candidate_roots():
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if (
                entry.is_dir()
                and pattern.match(entry.name)
                and (entry / "model" / "model.bin").is_file()
                and (entry / "sentencepiece.model").is_file()
            ):
                return entry
    return None


@dataclass
class _Direction:
    sp: Any
    translator: Any
    package: Path


@lru_cache(maxsize=8)
def _load(from_lang: str, to_lang: str) -> _Direction | None:
    package = _find_package(from_lang, to_lang)
    if package is None:
        return None
    try:
        import ctranslate2
        import sentencepiece as spm
    except Exception:  # pragma: no cover - env guard
        return None
    try:
        sp = spm.SentencePieceProcessor(model_file=str(package / "sentencepiece.model"))
        translator = ctranslate2.Translator(
            str(package / "model"), device="cpu", compute_type="int8",
            inter_threads=1, intra_threads=max(1, min(4, os.cpu_count() or 1)),
        )
    except Exception:  # pragma: no cover - corrupt model
        return None
    return _Direction(sp=sp, translator=translator, package=package)


def available(from_lang: str, to_lang: str) -> bool:
    return _load(from_lang, to_lang) is not None


def _protect(text: str, glossary: dict[str, str]) -> tuple[str, dict[str, str]]:
    placeholders: dict[str, str] = {}
    out = text
    for index, (source, target) in enumerate(glossary.items()):
        if not source or not target:
            continue
        pattern = re.compile(re.escape(source), re.IGNORECASE)
        if pattern.search(out):
            token = _SENTINEL.format(n=index)
            out = pattern.sub(token, out)
            placeholders[token] = str(target)
    return out, placeholders


def _restore(text: str, placeholders: dict[str, str]) -> str:
    out = text
    for token, target in placeholders.items():
        out = out.replace(token, target)
        out = out.replace(token.lower(), target)
    return out


def _clean(text: str) -> str:
    """Remove the SentencePiece boundary marker and tidy whitespace."""
    out = text.replace("\u2581", " ")
    out = re.sub(r"\s+", " ", out).strip()
    # CJK does not use inter-word spaces; drop spaces next to CJK characters.
    return re.sub(r"(?<=[\u3400-\u4dbf\u4e00-\u9fff])\s+|\s+(?=[\u3400-\u4dbf\u4e00-\u9fff])", "", out)


def _raw_translate(texts: list[str], from_lang: str, to_lang: str) -> list[str]:
    direction = _load(from_lang, to_lang)
    if direction is None:
        raise RuntimeError(f"offline MT model unavailable: {from_lang}->{to_lang}")
    batch = [direction.sp.encode(text, out_type=str) for text in texts]
    results = direction.translator.translate_batch(batch, beam_size=2, max_batch_size=16)
    return [_clean(direction.sp.decode(result.hypotheses[0])) for result in results]


def translate(
    texts: list[str],
    *,
    from_lang: str,
    to_lang: str,
    glossary: dict[str, str] | None = None,
) -> list[str]:
    """Translate ``texts`` offline, preserving glossary terms verbatim."""
    glossary = {str(k): str(v) for k, v in (glossary or {}).items() if k and v}
    prepared: list[str] = []
    placeholder_maps: list[dict[str, str]] = []
    for text in texts:
        protected, mapping = _protect(text or "", glossary)
        prepared.append(protected)
        placeholder_maps.append(mapping)
    if not prepared:
        return []
    translated = _raw_translate(prepared, from_lang, to_lang)
    return [_restore(item, mapping) for item, mapping in zip(translated, placeholder_maps, strict=False)]


def _char_bigrams(text: str) -> set[str]:
    clean = "".join(ch.lower() for ch in text if ch.isalnum())
    return {clean[i : i + 2] for i in range(len(clean) - 1)} or ({clean} if clean else set())


def _overlap(a: str, b: str) -> float:
    left, right = _char_bigrams(a), _char_bigrams(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def self_check(
    source: list[str],
    translated: list[str],
    *,
    back: list[str] | None,
    to_lang: str,
) -> dict[str, Any]:
    """Deterministic signals that the translation is trustworthy.

    Nothing here reads the reference translation (there is none); it checks the
    properties that catch the failure modes seen in practice: empty lines, the
    target script missing, runaway length, source words leaking through, and a
    back-translation that no longer overlaps the source.
    """
    to_norm = _norm(to_lang)
    problems: list[str] = []
    if len(translated) != len(source) or any(not item.strip() for item in translated):
        problems.append("empty_or_missing_lines")

    cjk_ratio = 0.0
    length_ratios: list[float] = []
    untranslated = 0
    for src, dst in zip(source, translated, strict=False):
        if to_norm == "zh":
            alnum = [ch for ch in dst if ch.isalnum()]
            cjk_ratio = (sum(1 for ch in alnum if _CJK.match(ch)) / len(alnum)) if alnum else 0.0
            if cjk_ratio < 0.5:
                problems.append("target_script_missing")
        if src.strip():
            length_ratios.append(len(dst) / max(1, len(src)))
            for word in _ASCII_WORD.findall(src):
                if word.lower() in dst.lower():
                    untranslated += 1

    mean_ratio = sum(length_ratios) / len(length_ratios) if length_ratios else 0.0
    # en->zh normally shrinks to 20-70% of the source length; catching extremes
    # is enough to flag a model that copied the source or hallucinated.
    if length_ratios and not (0.12 <= mean_ratio <= 1.2):
        problems.append("length_out_of_range")

    back_overlap = None
    if back is not None:
        scores = [_overlap(src, dst) for src, dst in zip(source, back, strict=False)]
        back_overlap = round(sum(scores) / len(scores), 4) if scores else 0.0
        if back_overlap < 0.12:
            problems.append("backtranslation_mismatch")

    return {
        "pass": not problems,
        "problems": sorted(set(problems)),
        "cjk_ratio": round(cjk_ratio, 4),
        "mean_length_ratio": round(mean_ratio, 4),
        "source_words_leaked": untranslated,
        "back_translation_overlap": back_overlap,
        "back_translation_available": back is not None,
    }


def translate_with_check(
    texts: list[str],
    *,
    from_lang: str,
    to_lang: str,
    glossary: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Translate, back-translate when the reverse model exists, and self-check."""
    translated = translate(texts, from_lang=from_lang, to_lang=to_lang, glossary=glossary)
    back: list[str] | None = None
    if available(to_lang, from_lang):
        try:
            back = _raw_translate(translated, to_lang, from_lang)
        except Exception:
            back = None
    check = self_check(texts, translated, back=back, to_lang=to_lang)
    return {
        "translated": translated,
        "back_translation": back,
        "check": check,
        "provider": "offline_argos_ct2",
        "from_lang": _norm(from_lang),
        "to_lang": _norm(to_lang),
    }


__all__ = ["available", "self_check", "translate", "translate_with_check"]
