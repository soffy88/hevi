"""textbook_bridge —— 教材↔古籍交叉弧 + 双述组装（P1）。

HISTORY-TEXTBOOK-MAINLINE-CC-SPEC-001 §3.3：同一事件/课节挂双述
  mainline=教材（primary，主述）· classical=古籍（auxiliary，并陈）。

P1 落地：
  1) 七上各课 ↔ 古籍事件映射（手工标注；古籍事件以 stratum §8 契约形态提供）；
  2) 教材主述文本：查 mneme knowledge_units（该课 cluster 的 KU core 拼接）；
  3) 双述组装：复用 arc_adapter.assemble_run_request(textbook_text=教材主述)，
     古籍 account 自动降为并陈。

G1b 实装后：映射由 stratum 语料弧（edge_onto）驱动，本表退役。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── 七上各课 ↔ 古籍事件映射（P1 手工标注；G1b 由语料弧驱动）───────────
# 值 = stratum §8 契约 JSON 路径。暂无契约文件的古籍 → None。
LESSON_TO_EVENT_CONTRACT: dict[str, str | None] = {
    "夏商周的更替": None,
    "动荡的春秋时期": None,
    "战国时期的社会变化": str(
        Path(__file__).resolve().parents[3] / "stratum" / "docs" / "history"
        / "contracts" / "sample.sanjiafenjin.json"
    ),
    "百家争鸣": None,
    "秦统一中国": None,
    "秦末农民大起义": None,
    "西汉建立和文景之治": None,
    "汉武帝巩固大一统王朝": None,
    "三国鼎立": None,
}


def lesson_contract_path(lesson_title: str) -> Path | None:
    raw = LESSON_TO_EVENT_CONTRACT.get(lesson_title)
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None


def load_lesson_contract(lesson_title: str) -> dict[str, Any] | None:
    path = lesson_contract_path(lesson_title)
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("教材交叉弧契约读取失败 %s: %s", path, exc)
        return None


async def textbook_mainline_from_mneme(
    tb_id: str,
    lesson_order: int,
    *,
    db_url: str = "",
    limit_kus: int = 8,
) -> str:
    """教材主述文本：查 mneme knowledge_units（该课 cluster 的 KU core 拼接）。"""
    import asyncpg

    db_url = (
        db_url
        or os.environ.get("MNEME_DATABASE_URL", "")
        or "postgresql://postgres:WmFJJAEtVFknjCDwNmi9bu45cK3mwi4@localhost:5433/mneme"
    )
    try:
        conn = await asyncpg.connect(db_url)
    except Exception as exc:
        logger.warning("mneme 教材主述查询失败: %s", exc)
        return ""
    try:
        rows = await conn.fetch(
            """SELECT ku.name, ku.description
            FROM knowledge_units ku
            JOIN knowledge_clusters kc ON ku.cluster_id = kc.id
            WHERE ku.textbook_id = $1 AND kc.display_order = $2
            ORDER BY ku.id LIMIT $3""",
            tb_id, lesson_order, limit_kus,
        )
    finally:
        await conn.close()
    parts = [
        f"{r['name']}：{(r['description'] or '').strip()}"
        for r in rows
    ]
    return "；".join(parts) if parts else ""


async def assemble_textbook_run_request(
    lesson_title: str,
    tb_id: str,
    lesson_order: int,
    *,
    textbook_text: str = "",
    target_duration_sec: int = 120,
    aspect_ratio: str = "16:9",
) -> dict[str, Any]:
    """双述 RunRequest：教材主述 + 古籍并陈（arc_adapter 契约组装）。"""
    from hevi.history_series.arc_adapter import assemble_run_request

    main_text = textbook_text or await textbook_mainline_from_mneme(tb_id, lesson_order)
    contract = load_lesson_contract(lesson_title)
    if contract is None:
        return {
            "source_name": f"历史现场·{tb_id}·{lesson_title}",
            "raw_text": f"{main_text}（教材主述）",
            "target_duration_sec": target_duration_sec,
            "aspect_ratio": aspect_ratio,
            "layer_config": {},
        }
    req = assemble_run_request(
        contract,
        textbook_text=main_text,
        target_duration_sec=target_duration_sec,
        aspect_ratio=aspect_ratio,
    )
    req["source_name"] = f"历史现场·{tb_id}·{lesson_title}"
    return req


__all__ = ["assemble_textbook_run_request", "load_lesson_contract",
           "textbook_mainline_from_mneme"]
