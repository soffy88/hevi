"""Review node: titles + views in, which story type works, three next ideas out."""

from __future__ import annotations

from typing import Any

from .topics import GENRE_LIBRARY, suggest_topics


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def review_episodes(series: dict[str, Any], episodes: list[dict[str, Any]]) -> dict[str, Any]:
    by_genre: dict[str, dict[str, Any]] = {}
    for ep in episodes:
        genre = str(ep.get("genre") or "daily_anomaly")
        bucket = by_genre.setdefault(genre, {"genre": genre, "label": GENRE_LIBRARY.get(genre, {}).get("label", genre),
                                             "episodes": 0, "views": 0.0, "titles": []})
        bucket["episodes"] += 1
        bucket["views"] += _num(ep.get("views"))
        bucket["titles"].append(str(ep.get("title") or ""))
    ranked = sorted(by_genre.values(), key=lambda b: (b["views"] / max(1, b["episodes"]), b["views"]), reverse=True)
    for bucket in ranked:
        bucket["avg_views"] = round(bucket["views"] / max(1, bucket["episodes"]), 1)
    best = ranked[0] if ranked else None
    next_ideas = suggest_topics(series, n=3, genres=[best["genre"]] + [g for g in GENRE_LIBRARY if best and g != best["genre"]])["ideas"] if best else suggest_topics(series)["ideas"]
    return {
        "series_id": series.get("series_id"),
        "episodes": len(episodes),
        "by_genre": ranked,
        "best_genre": best["genre"] if best else "",
        "best_genre_label": best["label"] if best else "",
        "best_avg_views": best["avg_views"] if best else 0,
        "next_ideas": next_ideas[:3],
        "conclusion": (
            f"播放最好的是《{best['label']}》，平均 {best['avg_views']:.0f} 播放；"
            f"下一集优先延续这个类型，并把最有趣的瞬间放在前 2 秒。"
            if best else "还没有带播放量的集，先按系列默认类型做一集。"
        ),
    }


def review_markdown(report: dict[str, Any]) -> str:
    lines = ["# 复盘", "", str(report.get("conclusion") or ""), ""]
    lines += ["| 类型 | 集数 | 总播放 | 平均播放 |", "|---|---|---|---|"]
    for row in report.get("by_genre") or []:
        lines.append(f"| {row['label']} | {row['episodes']} | {row['views']:.0f} | {row['avg_views']:.0f} |")
    lines += ["", "## 下一集 3 个点子", ""]
    for idea in report.get("next_ideas") or []:
        lines.append(f"- **{idea.get('genre_label')}**：{idea.get('one_sentence')}（前 2 秒：{idea.get('hook_first_2s')}）")
    lines.append("")
    return "\n".join(lines)
