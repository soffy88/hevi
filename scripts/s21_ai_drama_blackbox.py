"""S21：ai_drama 写实 / 动漫两种风格的黑盒验证。

每种风格跑 3 个新主题，离线（offline provider，本地 SD-Turbo + Piper + ffmpeg），
用 S16 起的五维评分（spec / audio / motion / clarity / text）打分。
两种风格平均分都 >= 4 且 6 个主题都产出真实文件时，才把
``hevi/studio/data/format_gates.json`` 的 ai_drama 门打开。

用法：
    python scripts/s21_ai_drama_blackbox.py --out DIR
    python scripts/s21_ai_drama_blackbox.py --out DIR --no-update-gate
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

THEMES = [
    "凌晨四点的面包房，烤箱里多出一张没人订的订单",
    "搬家那天，旧冰箱里还留着上一个住户的夏天",
    "小区门口的修表匠，只修停在同一天的钟",
]

STYLES = ["live_action", "anime"]

GATE_PATH = Path(__file__).resolve().parent.parent / "hevi/studio/data/format_gates.json"


def _bootstrap_env() -> None:
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


def _score(path: str | None) -> dict[str, Any]:
    if not path or not Path(path).is_file():
        return {"exists": False, "score": 0.0, "pass": False}
    from scripts.s16_blackbox import score_video

    return score_video(path)


def run_one(theme: str, style: str, out: Path, *, seed: int) -> dict[str, Any]:
    from hevi.ai_drama.pipeline import Pipeline

    slug = f"{style}_{abs(hash(theme)) % 10000:04d}"
    dest = out / slug
    started = time.time()
    try:
        report = Pipeline(
            dest,
            episode_id=slug,
            prefer_provider="offline",
            seed=seed,
            render_images=True,
            lipsync=False,
        ).run({"theme": theme, "style": style})
        delivery = report.get("delivery") or {}
        video = delivery.get("video_path") or delivery.get("deliverable")
        score = _score(video)
        return {
            "theme": theme,
            "style": style,
            "status": "completed" if video else "failed",
            "video": video,
            "elapsed_s": round(time.time() - started, 1),
            "script_source": report.get("script_source"),
            "provider": (report.get("cost_plan") or {}).get("provider"),
            "nodes": {k: v.get("passed") for k, v in (report.get("nodes") or {}).items()},
            **score,
        }
    except Exception as exc:
        return {
            "theme": theme,
            "style": style,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}"[:500],
            "elapsed_s": round(time.time() - started, 1),
            "exists": False,
            "score": 0.0,
            "pass": False,
        }


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_style: dict[str, dict[str, Any]] = {}
    for style in STYLES:
        rows = [r for r in results if r["style"] == style]
        scores = [r["score"] for r in rows if r.get("exists")]
        average = round(sum(scores) / len(scores), 2) if scores else 0.0
        by_style[style] = {
            "themes": len(rows),
            "real_files": len(scores),
            "average_score": average,
            "all_exist": len(scores) == len(rows) == len(THEMES),
            "pass": len(scores) == len(rows) == len(THEMES) and average >= 4.0,
            "scores": scores,
        }
    overall = round(sum(v["average_score"] for v in by_style.values()) / len(by_style), 2)
    passed = all(v["pass"] for v in by_style.values())
    return {"by_style": by_style, "overall_average": overall, "pass": passed}


def update_gate(summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    data: dict[str, Any] = {}
    if GATE_PATH.is_file():
        try:
            data = json.loads(GATE_PATH.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
    data["ai_drama"] = {
        "open": bool(summary["pass"]),
        "reason": (
            f"S21 黑盒通过：写实 {summary['by_style']['live_action']['average_score']} / "
            f"动漫 {summary['by_style']['anime']['average_score']}（离线 SD-Turbo）"
            if summary["pass"]
            else "S21 黑盒未达 4 分（写实 "
            f"{summary['by_style']['live_action']['average_score']} / 动漫 "
            f"{summary['by_style']['anime']['average_score']}），暂不对外开放"
        ),
        "styles": summary["by_style"],
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "results": results,
    }
    GATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def markdown(summary: dict[str, Any], results: list[dict[str, Any]]) -> str:
    lines = ["# ai_drama S21 黑盒", ""]
    lines.append(f"- 总平均分：**{summary['overall_average']}** / 5")
    lines.append(f"- 结论：{'通过，可对外开放' if summary['pass'] else '未通过，形式卡片显示“即将开放”'}")
    lines += ["", "| 风格 | 真实文件 | 平均分 | 通过 |", "|---|---|---|---|"]
    for style, row in summary["by_style"].items():
        lines.append(f"| {style} | {row['real_files']}/{row['themes']} | {row['average_score']} | {'是' if row['pass'] else '否'} |")
    lines += ["", "| 风格 | 主题 | 状态 | 分数 | 耗时 | 文件 |", "|---|---|---|---|---|---|"]
    for row in results:
        lines.append(
            f"| {row['style']} | {row['theme']} | {row['status']} | {row.get('score', 0)} | "
            f"{row.get('elapsed_s', 0)}s | {row.get('video') or row.get('error', '')} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-update-gate", action="store_true")
    args = ap.parse_args()

    _bootstrap_env()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for style in STYLES:
        for index, theme in enumerate(THEMES):
            row = run_one(theme, style, out, seed=args.seed + index)
            results.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    summary = summarise(results)
    (out / "ai_drama_blackbox.json").write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out / "ai_drama_blackbox.md").write_text(markdown(summary, results), encoding="utf-8")
    if not args.no_update_gate:
        update_gate(summary, results)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
