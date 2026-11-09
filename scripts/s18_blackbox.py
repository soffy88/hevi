"""S18 black-box validation for the three remaining internal lines.

Runs three themes per line through the real renderer and scores each output with
the same five dimensions used since S16 (``scripts/s16_blackbox.score_video``:
spec / audio / motion / clarity / text).  A line is recommended for the GA
whitelist only when its average score is >= 4 and every theme produced a real
file.

Usage:
    python scripts/s18_blackbox.py --line localization_dub --out DIR
    python scripts/s18_blackbox.py --line reference_adapt  --out DIR
    python scripts/s18_blackbox.py --line character_animation --out DIR
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any


def _bootstrap_env() -> None:
    """Load the release .env when the caller did not already export secrets."""
    if os.environ.get("JWT_SECRET"):
        return
    env_file = Path(os.environ.get("HEVI_ENV_FILE", "/data/soffy/projects/hevi-release/.env"))
    if env_file.is_file():
        try:
            from dotenv import dotenv_values

            for key, value in dotenv_values(env_file).items():
                if value is not None:
                    os.environ.setdefault(key, value)
        except Exception:
            pass
    os.environ.setdefault("APP_ENV", "development")


_bootstrap_env()

SOURCES = {
    "kara": ("/data/soffy/datasets/s18_sources/Kara_Fern_Interview.webm",
             "Kara Fern 访谈", {"Goldman Sachs": "高盛", "media": "媒体"}),
    "wikimania": ("/data/soffy/datasets/s18_sources/Wikimania_Fjmustak_lightning_talk.webm",
                  "Wikimania 闪电演讲", {"Wikimedia": "维基媒体", "software engineer": "软件工程师"}),
    "eso": ("/data/soffy/datasets/s18_sources/ESOcast_135_ALMA.webm",
            "ALMA 天文台科普", {"ALMA": "ALMA", "Universe": "宇宙"}),
}

REFERENCE_TOPICS = [
    ("城市里的树怎么降温", [
        "城市里的树，为什么能让整条街凉下来？",
        "一片树叶蒸发的水，相当于一台小空调。",
        "树荫挡住阳光，地面温度能低好几度。",
        "树冠还会把热空气往上推，形成微风。",
        "所以多种一棵树，就是给城市装一台免费的空调。",
        "下次路过树荫，记得停一秒感受它。",
    ]),
    ("为什么睡前一小时别刷手机", [
        "睡前一小时刷手机，为什么第二天特别累？",
        "屏幕的蓝光会推迟褪黑素分泌。",
        "短视频不断给你新的刺激，大脑很难关机。",
        "你以为在放松，其实注意力一直被迫工作。",
        "把手机放到另一个房间，入睡会快很多。",
        "今晚就试一次，明早你会知道差别。",
    ]),
    ("一杯手冲咖啡的关键变量", [
        "同一包豆子，为什么你冲出来总是发苦？",
        "先看水温，太高会把苦味一起带出来。",
        "再看研磨度，太细会让水流变慢、过度萃取。",
        "注水节奏要稳，别让粉层忽高忽低。",
        "最后是比例，一比十五是安全的起点。",
        "只改一个变量，你就能喝出差别。",
    ]),
]

CHARACTER_TOPICS = [
    "走路的机器人",
    "打招呼的舞者",
    "跳起来的孩子",
]


def _score(path: str | None) -> dict[str, Any]:
    if not path or not Path(path).is_file():
        return {"exists": False, "score": 0.0, "pass": False}
    from scripts.s16_blackbox import score_video

    return score_video(path)


async def _run_localization(out: Path) -> list[dict[str, Any]]:
    from hevi.providers.registry import register_all_providers

    register_all_providers()
    from hevi.studio.fulfill import fulfill_order

    results = []
    for key, (media, topic, glossary) in SOURCES.items():
        dest = out / f"localization_{key}"
        order = {
            "line_id": "localization_dub", "target": "localize_video",
            "media_path": media, "topic": topic, "lang": "zh-CN",
            "dub": True, "bilingual": True, "glossary": glossary,
        }
        try:
            result = await fulfill_order(order, execute=True, render=True, output_dir=dest)
        except Exception as exc:
            result = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
        score = _score(result.get("result_video_path"))
        report_path = dest / "video_localization_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
        results.append({
            "theme": key, "topic": topic, "status": result.get("status"),
            "reason": result.get("reason"), "video": result.get("result_video_path"),
            "provider": report.get("translation_provider"),
            "translation_self_check": report.get("translation_self_check"),
            "llm_error": report.get("translation_llm_error"),
            **score,
        })
    return results


async def _run_reference(out: Path) -> list[dict[str, Any]]:
    from hevi.studio.fulfill import fulfill_order

    results = []
    for index, (topic, lines) in enumerate(REFERENCE_TOPICS, start=1):
        dest = out / f"reference_{index}"
        order = {
            "line_id": "reference_adapt", "target": "explainer", "topic": topic,
            "script_lines": [{"text": text} for text in lines],
        }
        try:
            result = await fulfill_order(order, execute=True, render=True, output_dir=dest)
        except Exception as exc:
            result = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
        score = _score(result.get("result_video_path"))
        results.append({
            "theme": index, "topic": topic, "status": result.get("status"),
            "reason": result.get("reason"), "video": result.get("result_video_path"),
            "script_lines": len(lines), **score,
        })
    return results


async def _run_character(out: Path) -> list[dict[str, Any]]:
    from hevi.studio.fulfill import fulfill_order

    results = []
    for index, topic in enumerate(CHARACTER_TOPICS, start=1):
        dest = out / f"character_{index}"
        order = {"line_id": "character_animation", "target": "character_animation",
                 "topic": topic, "title": topic}
        try:
            result = await fulfill_order(order, execute=True, render=True, output_dir=dest)
        except Exception as exc:
            result = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
        score = _score(result.get("result_video_path"))
        results.append({
            "theme": index, "topic": topic, "status": result.get("status"),
            "reason": result.get("reason"), "video": result.get("result_video_path"),
            **score,
        })
    return results


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [item["score"] for item in results if item.get("exists")]
    average = round(sum(scores) / len(scores), 2) if scores else 0.0
    return {
        "results": results,
        "count": len(results),
        "average_score": average,
        "pass": bool(results) and len(scores) == len(results) and average >= 4.0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--line", choices=["localization_dub", "reference_adapt", "character_animation"],
                        required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.line == "localization_dub":
        results = asyncio.run(_run_localization(out))
    elif args.line == "reference_adapt":
        results = asyncio.run(_run_reference(out))
    else:
        results = asyncio.run(_run_character(out))
    report = _summary(results)
    (out / "blackbox.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
