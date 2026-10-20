"""Short-story one-stop package capability.

Registers ``story.short_package`` (CAPABILITY_CONTRACT.md; precedent:
``hevi/capabilities/multimodel.py`` / ``storyfilm.py``):

  题材/一句话创意 -> 大纲 -> 正文 -> 结构化自审 (钩子/冲突/结尾打分)
  -> 简介卖点 (标题候选 + 一句话卖点 + 简介) -> 封面环节
  (封面提示词必产; ``image.gpt_generate`` 可用时出图定稿 cover.png,
  否则降级为只产 cover_prompt.txt 并在 qa 注明)

Core logic lives in ``hevi/shortstory/core.py`` with an injectable
``llm_fn``; this module supplies the production Monid-backed LLM
(gpt-4o-mini via blockrun, same route as story.film_from_prompt) and maps
failures to ``CapabilityError`` — never a fake success. Tests monkeypatch
``_default_llm_fn`` (and ``hevi.capabilities.get`` for the cover), so the
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


def _default_llm_fn(stage: str, payload: dict[str, Any]) -> str:
    """Production LLM: one Monid chat call per stage. Patchable in tests."""
    from hevi.audio import monid_client

    prompt = str(payload.get("prompt") or "")
    if not prompt:
        raise CapabilityError(f"story.short_package: empty prompt for stage {stage!r}")
    body = {
        "model": _LLM_MODEL,
        "messages": [
            {"role": "system", "content": "你是短篇小说创作助手，严格按用户要求输出。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 3000,
        "temperature": 0.7,
    }
    output, _cost = _run_coro(
        monid_client.run_endpoint(_LLM_PROVIDER, _LLM_ENDPOINT, body=body)
    )
    try:
        return str(output["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise CapabilityError(
            f"story.short_package: LLM response has no content (stage {stage})"
        ) from exc


# Test hook: when set, replaces the production LLM entirely.
LLM_FN_OVERRIDE: Any = None


def _get_llm_fn() -> Any:
    return LLM_FN_OVERRIDE if LLM_FN_OVERRIDE is not None else _default_llm_fn


def _render_short_package(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.shortstory.core import ShortStoryError, build_short_package

    premise = str(params.get("premise") or "").strip()
    if not premise:
        raise CapabilityError("story.short_package: 'premise' is required")
    genre = str(params.get("genre") or "")
    target_words = params.get("target_words")
    generate_cover = bool(params.get("generate_cover", True))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        manifest = build_short_package(
            premise=premise,
            genre=genre,
            out_dir=out_dir,
            llm_fn=_get_llm_fn(),
            attempt_cover=generate_cover,
            target_words=int(target_words) if target_words is not None else None,
        )
    except CapabilityError:
        raise
    except ShortStoryError as exc:
        raise CapabilityError(f"story.short_package: {exc}") from exc
    except Exception as exc:
        raise CapabilityError(f"story.short_package failed: {exc}") from exc

    package_path = out_dir / "package.json"
    cover = manifest.get("cover") or {}
    cover_image = cover.get("image")
    primary = Path(cover_image) if cover_image and Path(cover_image).is_file() else package_path
    return CapabilityResult(
        png=str(primary) if primary.suffix == ".png" else None,
        duration_s=0.0,
        sha256=compute_sha256(primary),
        qa={
            "title": manifest.get("title"),
            "genre": genre,
            "word_count": manifest.get("word_count"),
            "files": manifest.get("files"),
            "review_total_score": (manifest.get("review") or {}).get("total_score"),
            "review_failed_checks": (manifest.get("review") or {}).get("failed_checks"),
            "title_candidates": (manifest.get("blurb") or {}).get("title_candidates"),
            "one_line_pitch": (manifest.get("blurb") or {}).get("one_line_pitch"),
            "cover_status": cover.get("status"),
            "cover_degraded": bool(cover.get("degraded")),
            "cover_note": cover.get("note"),
            "cover_prompt": cover.get("prompt_file"),
            "cover_image": cover_image,
            "package_json": str(package_path),
        },
    )


def register_shortstory_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    registered: list[str] = []

    register(
        Capability(
            name="story.short_package",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "premise": {
                        "type": "string",
                        "minLength": 1,
                        "description": "题材/一句话创意, e.g. 退休侦探在小镇上破获最后一案",
                    },
                    "genre": {
                        "type": "string",
                        "description": "题材/类型, e.g. 悬疑 / 科幻 / 言情",
                    },
                    "target_words": {
                        "type": "integer",
                        "minimum": 200,
                        "maximum": 50000,
                        "description": "正文目标字数 (optional guidance for the draft stage)",
                    },
                    "generate_cover": {
                        "type": "boolean",
                        "default": True,
                        "description": (
                            "Try image.gpt_generate for cover.png; on any failure the "
                            "package degrades to cover_prompt.txt only (qa notes it)"
                        ),
                    },
                },
                "required": ["premise"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.5,
            render=_render_short_package,
            description=(
                "Short-story one-stop package: premise -> outline -> draft -> "
                "structured self-review (hook/conflict/ending checklist scores) "
                "-> blurb & selling points (title candidates, one-line pitch, "
                "synopsis) -> dedicated cover step (cover prompt always; "
                "cover.png via image.gpt_generate when available, otherwise "
                "prompt-only degradation noted in qa). All artifacts land in "
                "the job dir (package.json is the ledger)."
            ),
            line="shortstory",
        )
    )
    registered.append("story.short_package")

    return registered
