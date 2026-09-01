"""textbook_bridge —— 教材↔古籍交叉弧 + 双述组装 (P1)。"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

LESSON_TO_EVENT_CONTRACT: dict[str, str | None] = {
    "战国时期的社会变化": str(
        Path(__file__).resolve().parent
        / "contracts"
        / "sample.sanjiafenjin.json"
    ),
}


def lesson_contract_path(lesson_title: str) -> Path | None:
    raw = LESSON_TO_EVENT_CONTRACT.get(lesson_title)
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_file() else None


def load_lesson_contract(lesson_title: str) -> dict[str, Any] | None:
    path = lesson_contract_path(lesson_title)
    if path is None:
        return None
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning("契约读取失败 %s: %s", path, e)
        return None


async def textbook_mainline_from_mneme(
    tb_id: str,
    lesson_order: int,
    *,
    db_url: str = "",
    limit_kus: int = 8,
) -> str:
    import asyncpg

    db_url = db_url or os.environ.get(
        "MNEME_DATABASE_URL",
        "postgresql://postgres:WmFJJAEtVFknjCDwNmi9bu45cK3mwi4@localhost:5433/mneme",
    )
    try:
        conn = await asyncpg.connect(db_url)
    except Exception as e:
        logger.warning("mneme 连接失败: %s", e)
        return ""
    try:
        rows = await conn.fetch(
            """SELECT ku.name, ku.description FROM knowledge_units ku
            JOIN knowledge_clusters kc ON ku.cluster_id = kc.id
            WHERE ku.textbook_id=$1 AND kc.display_order=$2 ORDER BY ku.id LIMIT $3""",
            tb_id,
            lesson_order,
            limit_kus,
        )
    finally:
        await conn.close()
    parts = [f"{r['name']}：{(r['description'] or '').strip()}" for r in rows]
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
