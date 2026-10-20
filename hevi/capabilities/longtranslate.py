"""Long-text translation capability.

Registers ``text.translate_long`` (CAPABILITY_CONTRACT.md; precedent:
``hevi/capabilities/multimodel.py``):

  长文本 (字符串或文件) + 目标语言 + 可选术语表
  -> 按段落分块 (单块字符上限可配, 相邻块带上下文重叠)
  -> 逐块翻译 -> 术语一致性后检 (术语表目标词缺失报警写入报告)
  -> 译文全文 + 双语对照 (Markdown + JSON)

Core logic lives in ``hevi/longtranslate/core.py`` with an injectable
``translate_fn``; this module supplies the production Monid-backed
translator (gpt-4o-mini via blockrun, same route as
story.film_from_prompt) and maps failures to ``CapabilityError`` — never
a fake success. Tests monkeypatch ``_default_translate_fn``, so the
contract tests run offline at zero cost.

Registration is explicit: importing ``hevi.capabilities`` does not pull
this module in (the coordinator wires it into the catalogue).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_LLM_PROVIDER = "blockrun.ai"
_LLM_ENDPOINT = "/api/v1/chat/completions"
_LLM_MODEL = "gpt-4o-mini"


def _run_coro(coro):  # type: ignore[no-untyped-def]
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _default_translate_fn(
    text: str,
    *,
    target_language: str,
    glossary: dict[str, str],
    context: str,
) -> str:
    """Production translator: one Monid chat call per chunk. Patchable."""
    from hevi.audio import monid_client

    glossary_lines = "\n".join(f"- {k} -> {v}" for k, v in (glossary or {}).items())
    prompt = (
        f"把下面的文本翻译成 {target_language}。只输出译文，不要解释。\n"
        + (f"术语表 (必须严格使用右边的译法):\n{glossary_lines}\n" if glossary_lines else "")
        + (f"上文 (仅供语境参考，不要翻译):\n{context}\n" if context else "")
        + f"待翻译文本:\n{text}"
    )
    body = {
        "model": _LLM_MODEL,
        "messages": [
            {"role": "system", "content": "你是专业翻译，严格遵循术语表，只输出译文。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 3000,
        "temperature": 0.2,
    }
    output, _cost = _run_coro(
        monid_client.run_endpoint(_LLM_PROVIDER, _LLM_ENDPOINT, body=body)
    )
    try:
        return str(output["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise CapabilityError(
            "text.translate_long: LLM response has no content"
        ) from exc


# Test hook: when set, replaces the production translator entirely.
TRANSLATE_FN_OVERRIDE: Any = None


def _get_translate_fn() -> Any:
    return TRANSLATE_FN_OVERRIDE if TRANSLATE_FN_OVERRIDE is not None else _default_translate_fn


def _render_translate_long(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.longtranslate.core import LongTranslateError, translate_long

    text = params.get("text")
    input_path = params.get("input_path")
    if text is not None and input_path is not None:
        raise CapabilityError(
            "text.translate_long: pass either 'text' or 'input_path', not both"
        )
    if text is None and input_path is None:
        raise CapabilityError(
            "text.translate_long: one of 'text' or 'input_path' is required"
        )
    target_language = str(params.get("target_language") or "").strip()
    if not target_language:
        raise CapabilityError("text.translate_long: 'target_language' is required")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        report = translate_long(
            text=str(text) if text is not None else None,
            input_path=str(input_path) if input_path is not None else None,
            target_language=target_language,
            source_language=str(params.get("source_language") or "auto"),
            glossary=params.get("glossary"),
            out_dir=out_dir,
            translate_fn=_get_translate_fn(),
            max_chars=int(params.get("max_chars") or 1800),
            overlap_chars=int(params.get("overlap_chars") if params.get("overlap_chars") is not None else 200),
        )
    except CapabilityError:
        raise
    except LongTranslateError as exc:
        raise CapabilityError(f"text.translate_long: {exc}") from exc
    except Exception as exc:
        raise CapabilityError(f"text.translate_long failed: {exc}") from exc

    translated_path = out_dir / "translated.txt"
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(translated_path),
        qa={
            "target_language": target_language,
            "source_language": report.get("source_language"),
            "chunk_count": report.get("chunk_count"),
            "source_chars": report.get("source_chars"),
            "translated_chars": report.get("translated_chars"),
            "glossary_ok": report.get("glossary_ok"),
            "glossary_warnings": report.get("glossary_warnings"),
            "files": report.get("files"),
            "translated_txt": str(translated_path),
            "bilingual_md": str(out_dir / "bilingual.md"),
            "bilingual_json": str(out_dir / "bilingual.json"),
            "report_json": str(out_dir / "translation_report.json"),
        },
    )


def register_longtranslate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    registered: list[str] = []

    register(
        Capability(
            name="text.translate_long",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Source text (mutually exclusive with input_path)",
                    },
                    "input_path": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Local UTF-8 text file to translate (mutually exclusive with text)",
                    },
                    "target_language": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Target language, e.g. English / 日本語 / 简体中文",
                    },
                    "source_language": {
                        "type": "string",
                        "default": "auto",
                        "description": "Source language label recorded in the bilingual output",
                    },
                    "glossary": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Optional term map: source term -> required target term",
                    },
                    "max_chars": {
                        "type": "integer",
                        "minimum": 50,
                        "maximum": 20000,
                        "default": 1800,
                        "description": "Per-chunk character ceiling",
                    },
                    "overlap_chars": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 5000,
                        "default": 200,
                        "description": "Tail of the previous chunk passed as context (never re-translated)",
                    },
                },
                "required": ["target_language"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.5,
            render=_render_translate_long,
            description=(
                "Long-text translation pipeline: paragraph-aware chunking "
                "(configurable per-chunk character ceiling, context overlap "
                "between adjacent chunks) -> per-chunk translation -> "
                "glossary consistency post-check (missing required target "
                "terms are reported as warnings) -> full translation plus "
                "segment-by-segment bilingual output (Markdown + JSON) "
                "and a translation report in the job dir. "
                "文档级长文翻译（整篇文本→双语对照文档）；视频字幕段级译制走 hevi/production/media_workflows.video_localization_workflow（后端 voicepro_translate），两者勿混用。"
            ),
            line="longtranslate",
        )
    )
    registered.append("text.translate_long")

    return registered
