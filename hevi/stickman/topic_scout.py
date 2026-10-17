"""stickman.topic_scout —— 选题侦测与“少发高爆”打分器。

输入对标频道数据（CSV 文本/文件或结构化 dict），基于频道发布频率与播放爆发倍率，
计算“少发高爆”得分并排序。全量本地离线运算，不依赖外部网络与付费 API。
"""

from __future__ import annotations

import csv
import io
import math
from pathlib import Path
from typing import Any


def _parse_int(val: Any, default: int = 0) -> int:
    if val is None or val == "":
        return default
    try:
        # Handles potential comma formatting like "10,000" or scientific float string
        s = str(val).replace(",", "").strip()
        return int(float(s))
    except (ValueError, TypeError):
        return default


def _parse_float(val: Any, default: float = 0.0) -> float:
    if val is None or val == "":
        return default
    try:
        s = str(val).replace(",", "").strip()
        return float(s)
    except (ValueError, TypeError):
        return default


def parse_topic_records(data: str | Path | list[dict[str, Any]]) -> list[dict[str, Any]]:
    """解析输入数据为标准的记录列表。"""
    if isinstance(data, list):
        return data

    if isinstance(data, Path) or (isinstance(data, str) and "\n" not in data and Path(data).is_file()):
        content = Path(data).read_text(encoding="utf-8")
    else:
        content = str(data)

    records: list[dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(content.strip()))
    for row in reader:
        records.append(dict(row))
    return records


def calculate_viral_score(
    views: int,
    subscribers: int,
    monthly_uploads: float,
    likes: int = 0,
    comments: int = 0,
) -> dict[str, Any]:
    """计算单条视频/选题的“少发高爆”综合得分。

    核心逻辑：
    1. 爆发倍率 (viral_ratio): 播放量相比粉丝基数的倍率。基础基数保底 100。
    2. 少发加权 (freq_multiplier): 月更新量越低（精耕细作），加权越高；
       如月更 1-2 条赋予最高 2.5~3.0x 杠杆，日更/高频量产则平抑加权。
    3. 互动加权 (engagement_bonus): 点赞与评论互动率修正，封顶 +50%。
    """
    subs = max(subscribers, 100)
    viral_ratio = views / subs

    # 少发加权：10 / (monthly_uploads + 2)
    # 月更 1 条 -> 3.33 (capped at 3.0)
    # 月更 3 条 -> 2.0
    # 月更 8 条 -> 1.0
    # 月更 25 条 -> 0.37
    freq_weight = max(0.2, min(3.0, 10.0 / (max(monthly_uploads, 0.5) + 2.0)))

    eng_rate = (likes + comments * 3) / max(views, 1)
    eng_multiplier = 1.0 + min(eng_rate * 5.0, 0.5)

    final_score = round(viral_ratio * freq_weight * eng_multiplier, 2)

    if final_score >= 20.0:
        tag = "极少发特大爆款"
    elif final_score >= 8.0:
        tag = "少发高爆"
    elif final_score >= 2.5:
        tag = "潜力黑马"
    else:
        tag = "常规平销"

    return {
        "score": final_score,
        "viral_ratio": round(viral_ratio, 2),
        "freq_weight": round(freq_weight, 2),
        "eng_multiplier": round(eng_multiplier, 2),
        "tag": tag,
    }


def scout_topics(
    data: str | Path | list[dict[str, Any]],
    *,
    min_views: int = 0,
    top_n: int | None = None,
) -> list[dict[str, Any]]:
    """选题侦测与排序。返回按少发高爆得分降序排列的榜单。"""
    raw_records = parse_topic_records(data)
    results: list[dict[str, Any]] = []

    for item in raw_records:
        channel = str(item.get("channel_name") or item.get("channel") or item.get("creator") or "未知频道").strip()
        title = str(item.get("title") or item.get("topic") or item.get("topic_title") or "未命名选题").strip()
        views = _parse_int(item.get("views") or item.get("view_count"))
        if views < min_views:
            continue

        subs = _parse_int(item.get("subscribers") or item.get("subscriber_count") or item.get("fans") or 1000)
        monthly_uploads = _parse_float(
            item.get("monthly_uploads")
            or item.get("video_count_monthly")
            or item.get("frequency")
            or 4.0
        )
        likes = _parse_int(item.get("likes") or item.get("like_count"))
        comments = _parse_int(item.get("comments") or item.get("comment_count"))

        score_info = calculate_viral_score(
            views=views,
            subscribers=subs,
            monthly_uploads=monthly_uploads,
            likes=likes,
            comments=comments,
        )

        results.append({
            "title": title,
            "channel_name": channel,
            "views": views,
            "subscribers": subs,
            "monthly_uploads": monthly_uploads,
            "likes": likes,
            "comments": comments,
            "score": score_info["score"],
            "viral_ratio": score_info["viral_ratio"],
            "freq_weight": score_info["freq_weight"],
            "tag": score_info["tag"],
        })

    # 按得分倒序排序
    results.sort(key=lambda r: r["score"], reverse=True)

    for rank, entry in enumerate(results, start=1):
        entry["rank"] = rank

    if top_n is not None and top_n > 0:
        results = results[:top_n]

    return results
