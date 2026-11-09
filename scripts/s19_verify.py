"""S19 verification: every text-LLM surface must use the primary channel.

Runs one fresh item per surface and records which channel answered, so the
report can distinguish "used the LLM" from "fell back":

  * localization_dub: real video localization (Arabic source -> Chinese) via
    ``fulfill_order``; the report must say provider=hevi_llm and not fallback.
  * localization quality: the same English transcript through opencode and the
    offline Argos MT, with the shared deterministic self-check metrics.
  * explainer: ``hevi.explainer.research._llm_research`` on a new topic.
  * ai_drama: the real script node (``Pipeline.stage_script``) on a new topic.
  * canvas: ``hevi.canvas.llm_review`` on a text node.

Usage:
    python scripts/s19_verify.py --out /data/soffy/projects/seq-1108/verify_s19
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ARABIC_SOURCE = "/data/soffy/datasets/s18_sources/Bathina_Al-Raisi_interview.ogv"
ARABIC_TOPIC = "阿拉伯语访谈：巴提纳·阿尔-拉伊西"


def _bootstrap_env() -> None:
    if os.environ.get("JWT_SECRET"):
        return
    env_file = Path(os.environ.get("HEVI_ENV_FILE", "/data/soffy/projects/hevi/.env"))
    if env_file.is_file():
        try:
            from dotenv import dotenv_values

            for key, value in dotenv_values(env_file).items():
                if value is not None:
                    os.environ.setdefault(key, value)
        except Exception:
            pass
    os.environ.setdefault("APP_ENV", "development")


def _disable_fallbacks_for_proof() -> None:
    """Prove the primary channel served the call, not an internal fallback.

    The opencode caller falls back to NIM when registered; removing NIM (and the
    other text fallbacks from the free-channel list is not possible here) makes
    a success attributable to opencode itself.
    """
    os.environ["HEVI_NIM_KEYS"] = ""
    os.environ["HEVI_NIM_KEY_FILE"] = "/nonexistent-s19"


def _register() -> None:
    from hevi.providers.registry import register_all_providers

    register_all_providers()


def _chosen_registry_name() -> str:
    from hevi.providers.llm_pick import TEXT_LLM_ORDER

    try:
        from obase.provider_registry import ProviderRegistry

        registry = ProviderRegistry.get()
        for name in TEXT_LLM_ORDER:
            try:
                if registry.llm(name) is not None:
                    return name
            except Exception:
                continue
    except Exception:
        pass
    return ""


def _run_localization(out: Path) -> dict[str, Any]:
    from hevi.studio.fulfill import fulfill_order

    dest = out / "localization"
    order = {
        "line_id": "localization_dub",
        "target": "localize_video",
        "media_path": ARABIC_SOURCE,
        "topic": ARABIC_TOPIC,
        "lang": "zh-CN",
        "dub": True,
        "bilingual": True,
        "glossary": {"Bathina Al-Raisi": "巴提纳·阿尔-拉伊西"},
    }
    started = time.time()
    try:
        result = asyncio.run(fulfill_order(order, execute=True, render=True, output_dir=dest))
    except Exception as exc:
        result = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
    report_path = dest / "video_localization_report.json"
    report = (
        json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
    )
    return {
        "status": result.get("status"),
        "reason": result.get("reason"),
        "video": result.get("result_video_path"),
        "elapsed_s": round(time.time() - started, 1),
        "translation_provider": report.get("translation_provider"),
        "translation_channel": report.get("translation_channel"),
        "translation_fallback": report.get("translation_fallback"),
        "llm_error": report.get("translation_llm_error"),
        "self_check": report.get("translation_self_check"),
        "source_language": report.get("source_language"),
        "sample": list(report.get("translations") or [])[:3]
        or list(report.get("subtitles") or [])[:3],
    }


def _run_localization_quality(out: Path) -> dict[str, Any]:
    """Same English transcript through opencode vs offline Argos, shared checks."""
    from hevi.ingest.video_transcript import fetch_transcript
    from hevi.production.media_workflows import _translate_with_hevi_llm
    from hevi.translation import offline_mt

    media = ARABIC_SOURCE  # replaced below when the English fixture exists
    english = "/data/soffy/datasets/s18_sources/Kara_Fern_Interview.webm"
    if Path(english).is_file():
        media = english
    segments = fetch_transcript(media, whisper_fallback=True, language="en")
    segments = segments[:6]
    source = [item.text for item in segments]
    llm_lines, channel = asyncio.run(
        _translate_with_hevi_llm(segments, target_language="zh-CN", glossary={})
    )
    back = None
    if offline_mt.available("zh", "en"):
        back = offline_mt._raw_translate(llm_lines, from_lang="zh", to_lang="en")
    llm_check = offline_mt.self_check(source, llm_lines, back=back, to_lang="zh")
    argos = offline_mt.translate_with_check(source, from_lang="en", to_lang="zh")

    def _cjk(lines: list[str]) -> float:
        chars = [c for c in "".join(lines) if c.isalnum()]
        if not chars:
            return 0.0
        return round(sum(1 for c in chars if "\u4e00" <= c <= "\u9fff") / len(chars), 3)

    return {
        "channel": channel,
        "source_lines": source,
        "llm": {
            "lines": llm_lines,
            "self_check": llm_check,
            "aggregate_cjk": _cjk(llm_lines),
        },
        "argos": {
            "lines": argos["translated"],
            "self_check": argos["check"],
            "aggregate_cjk": _cjk(argos["translated"]),
            "provider": argos["provider"],
        },
        "notes": (
            "Per-line target_script_missing on the LLM side comes from preserving "
            "Latin proper names (Rachel Bronta, Goldman Sachs...), by design. "
            "Compare aggregate CJK, length ratio, source-name leakage and "
            "back-translation overlap instead of the per-line pass flag."
        ),
    }


def _run_explainer(out: Path) -> dict[str, Any]:
    from hevi.explainer.research import _llm_research

    topic = "为什么深海鱼出水会瞬间变形"
    default_name = _chosen_registry_name()
    started = time.time()
    try:
        raw = asyncio.run(_llm_research(topic, "1-3"))
        keys = sorted(raw.keys())
        firms = len(raw.get("facts") or [])
        ok = bool(raw.get("research_summary") or raw.get("chapters"))
        error = None
    except Exception as exc:
        keys, firms, ok = [], 0, False
        error = f"{type(exc).__name__}: {exc}"[:300]
    return {
        "topic": topic,
        "default_llm": default_name,
        "ok": ok,
        "raw_keys": keys,
        "facts": firms,
        "error": error,
        "elapsed_s": round(time.time() - started, 1),
    }


def _run_ai_drama(out: Path) -> dict[str, Any]:
    from hevi.ai_drama.pipeline import Pipeline

    topic = "雨夜最后一班地铁"
    dest = out / "ai_drama"
    dest.mkdir(parents=True, exist_ok=True)
    pipeline = Pipeline(dest, episode_id="s19-verify")
    pipeline.state = {"input": {"theme": topic, "style": "live_action"}}
    started = time.time()
    payload = pipeline.stage_script()
    script = payload["script"]
    from hevi.ai_drama.schema import iter_dialogue

    dialogue = [line["text"] for _, _, line in iter_dialogue(script)]
    return {
        "topic": topic,
        "script_source": pipeline.report.get("script_source"),
        "llm_error": pipeline.report.get("script_llm_error"),
        "dialogue": dialogue,
        "script_path": str(dest / "script.json"),
        "elapsed_s": round(time.time() - started, 1),
    }


def _run_canvas(out: Path) -> dict[str, Any]:
    from hevi.canvas import llm_review

    built = llm_review.build()
    if built is None:
        return {"ok": False, "error": "no free LLM channel available"}
    reviewer, _rewriter, channel = built
    text = "大家好，今天我们来聊聊一个东西。它很重要。就这样。"
    started = time.time()
    verdict = reviewer(text, {})
    return {
        "channel": channel,
        "verdict": verdict,
        "elapsed_s": round(time.time() - started, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--only", choices=["localization", "quality", "explainer", "ai_drama", "canvas"],
                        action="append")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    _bootstrap_env()
    _disable_fallbacks_for_proof()
    _register()
    wanted = set(args.only or ["localization", "quality", "explainer", "ai_drama", "canvas"])
    path = out / "verify.json"
    result: dict[str, Any] = {}
    if path.is_file():
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            result = {}
    result["primary_registry_name"] = _chosen_registry_name()
    if "localization" in wanted:
        result["localization"] = _run_localization(out)
    if "quality" in wanted:
        result["localization_quality"] = _run_localization_quality(out)
    if "explainer" in wanted:
        result["explainer"] = _run_explainer(out)
    if "ai_drama" in wanted:
        result["ai_drama"] = _run_ai_drama(out)
    if "canvas" in wanted:
        result["canvas"] = _run_canvas(out)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"written": str(path), "primary": result["primary_registry_name"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
