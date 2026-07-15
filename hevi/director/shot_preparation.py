"""INC-001 §A/§G/§I/§L —— 导演台「逐镜头准备台」服务层。

把 ShotListItem 已生成的资产/对白信息**确定性物化成候选**(§G,不再另调 LLM),人工确认后
才成为事实;镜头就绪状态(§A)只有 pending/ready、由候选态按固定规则**重算**(不设置);
skip_extraction 逃生阀(§I);聚合 preparation-state(§L)。

持久化走 PgPool 裸 SQL(与本路由 _persist_verdicts 一致),三张表见迁移
c7d8e9f0a1b2。纯逻辑(compute_readiness_status / candidates_from_shot / build_preparation_state)
与 SQL 分离,便于无 DB 单测。
"""

from __future__ import annotations

import uuid
from typing import Any

from hevi.director.pipeline_schemas import ShotListItem

_ASSET_DONE = ("linked", "ignored")
_DIALOGUE_DONE = ("accepted", "ignored")


# ── 纯逻辑(无 DB,可单测)──────────────────────────────────────────────────


def compute_readiness_status(
    *,
    skip_extraction: bool,
    extracted: bool,
    asset_statuses: list[str],
    dialogue_statuses: list[str],
) -> str:
    """INC-001 §A.1 就绪重算(顺序即优先级),返回 "pending" | "ready":

    1. skip_extraction = true              → ready
    2. 从未提取过                           → pending
    3. 提取过但没有任何候选                  → ready
    4. 所有资产候选 ∈ {linked, ignored}
       且 所有对白候选 ∈ {accepted, ignored} → ready
    5. 其他                                 → pending

    铁律:任一候选仍处 pending → 不能 ready。例外:提取后无对白候选不阻塞(空镜/无对白镜)。
    """
    if skip_extraction:
        return "ready"
    if not extracted:
        return "pending"
    if not asset_statuses and not dialogue_statuses:
        return "ready"
    assets_ok = all(s in _ASSET_DONE for s in asset_statuses)
    dialogue_ok = all(s in _DIALOGUE_DONE for s in dialogue_statuses)
    return "ready" if assets_ok and dialogue_ok else "pending"


def candidates_from_shot(
    shot: ShotListItem,
) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
    """从已锁定的 ShotListItem 确定性抽出(资产候选, 对白候选)——分镜阶段 LLM 已产出这些
    (character_names/scene_name/prop_names/dialogue_lines+target_name),这里只是物化成待确认
    候选,不再另调 LLM。资产候选=(type, name);对白候选=dict(index/text/speaker/target)。"""
    assets: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for name in shot.character_names:
        key = ("character", name.strip())
        if key[1] and key not in seen:
            seen.add(key)
            assets.append(key)
    if (shot.scene_name or "").strip():
        assets.append(("scene", shot.scene_name.strip()))
    for p in shot.prop_names:
        key = ("prop", p.strip())
        if key[1] and key not in seen:
            seen.add(key)
            assets.append(key)

    dialogue: list[dict[str, Any]] = []
    for i, dl in enumerate(shot.dialogue_lines):
        text = (dl.text or "").strip()
        if not text:
            continue
        dialogue.append(
            {
                "line_index": i,
                "text": text,
                "speaker_name": (dl.character_name or "").strip(),
                "target_name": (getattr(dl, "target_name", "") or "").strip(),
            }
        )
    return assets, dialogue


def build_preparation_state(
    *,
    shot: ShotListItem | None,
    readiness: dict[str, Any],
    asset_rows: list[dict[str, Any]],
    dialogue_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """INC-001 §L.1 聚合准备态。前端不再自己拼 pendingConfirmCount / 推导 shot.status。"""
    pending_assets = [r for r in asset_rows if r["candidate_status"] == "pending"]
    pending_dialogue = [r for r in dialogue_rows if r["candidate_status"] == "pending"]
    status = readiness.get("status", "pending")
    return {
        "shot_id": readiness["shot_id"],
        "shot": shot.model_dump() if shot is not None else None,
        "status": status,
        "skip_extraction": readiness.get("skip_extraction", False),
        "extracted": readiness.get("extracted", False),
        "assets_overview": asset_rows,
        "dialogue_candidates": dialogue_rows,
        "saved_dialogue_lines": [r for r in dialogue_rows if r["candidate_status"] == "accepted"],
        "pending_confirm_count": len(pending_assets) + len(pending_dialogue),
        "ready_for_generation": status == "ready",
    }


# ── SQL(PgPool 裸 SQL,与 _persist_verdicts 一致)────────────────────────────


async def ensure_readiness_row(conn: Any, work_id: str, shot_id: str) -> None:
    """分镜锁定后为每镜建就绪行(status=pending)。已存在则不动(ON CONFLICT DO NOTHING)。"""
    await conn.execute(
        "INSERT INTO shot_readiness (id, work_id, shot_id) VALUES ($1,$2,$3) "
        "ON CONFLICT (work_id, shot_id) DO NOTHING",
        uuid.uuid4(),
        work_id,
        shot_id,
    )


async def _fetch_readiness(conn: Any, work_id: str, shot_id: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        "SELECT work_id, shot_id, status, skip_extraction, extracted "
        "FROM shot_readiness WHERE work_id=$1 AND shot_id=$2",
        work_id,
        shot_id,
    )
    return dict(row) if row else None


async def _fetch_candidates(conn: Any, work_id: str, shot_id: str) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT id, candidate_type, candidate_name, candidate_status, linked_entity_id "
        "FROM shot_extracted_candidates WHERE work_id=$1 AND shot_id=$2 ORDER BY created_at",
        work_id,
        shot_id,
    )
    return [dict(r) for r in rows]


async def _fetch_dialogue(conn: Any, work_id: str, shot_id: str) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT id, line_index, text, speaker_name, target_name, candidate_status, "
        "linked_dialog_line_id FROM shot_extracted_dialogue_candidates "
        "WHERE work_id=$1 AND shot_id=$2 ORDER BY line_index",
        work_id,
        shot_id,
    )
    return [dict(r) for r in rows]


async def _recompute(conn: Any, work_id: str, shot_id: str) -> str:
    """按 §A.1 重算并写回 shot_readiness.status,返回新状态。所有 mutation 结尾都调它。"""
    readiness = await _fetch_readiness(conn, work_id, shot_id)
    if readiness is None:
        await ensure_readiness_row(conn, work_id, shot_id)
        readiness = await _fetch_readiness(conn, work_id, shot_id) or {}
    assets = await _fetch_candidates(conn, work_id, shot_id)
    dialogue = await _fetch_dialogue(conn, work_id, shot_id)
    status = compute_readiness_status(
        skip_extraction=readiness.get("skip_extraction", False),
        extracted=readiness.get("extracted", False),
        asset_statuses=[a["candidate_status"] for a in assets],
        dialogue_statuses=[d["candidate_status"] for d in dialogue],
    )
    await conn.execute(
        "UPDATE shot_readiness SET status=$3, updated_at=now() WHERE work_id=$1 AND shot_id=$2",
        work_id,
        shot_id,
        status,
    )
    return status


async def extract_shot(pool: Any, work_id: str, shot: ShotListItem) -> None:
    """§G 提取:清掉该镜旧候选 → 从 ShotListItem 物化新候选 → 标 extracted=true → 重算就绪。
    (re-extract 即替换;已确认状态会被重置,提取本就是显式重来动作。)"""
    assets, dialogue = candidates_from_shot(shot)
    async with pool.acquire() as conn:
        await ensure_readiness_row(conn, work_id, shot.shot_id)
        await conn.execute(
            "DELETE FROM shot_extracted_candidates WHERE work_id=$1 AND shot_id=$2",
            work_id,
            shot.shot_id,
        )
        await conn.execute(
            "DELETE FROM shot_extracted_dialogue_candidates WHERE work_id=$1 AND shot_id=$2",
            work_id,
            shot.shot_id,
        )
        for ctype, cname in assets:
            await conn.execute(
                "INSERT INTO shot_extracted_candidates "
                "(id, work_id, shot_id, candidate_type, candidate_name, source) "
                "VALUES ($1,$2,$3,$4,$5,'shot_list')",
                uuid.uuid4(),
                work_id,
                shot.shot_id,
                ctype,
                cname,
            )
        for d in dialogue:
            await conn.execute(
                "INSERT INTO shot_extracted_dialogue_candidates "
                "(id, work_id, shot_id, line_index, text, speaker_name, target_name, source) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,'shot_list')",
                uuid.uuid4(),
                work_id,
                shot.shot_id,
                d["line_index"],
                d["text"],
                d["speaker_name"],
                d["target_name"],
            )
        await conn.execute(
            "UPDATE shot_readiness SET extracted=true WHERE work_id=$1 AND shot_id=$2",
            work_id,
            shot.shot_id,
        )
        await _recompute(conn, work_id, shot.shot_id)


async def set_asset_candidate(
    pool: Any,
    work_id: str,
    shot_id: str,
    candidate_id: Any,
    *,
    status: str,
    linked_entity_id: str | None,
) -> str:
    """§G/§A.2 资产候选状态迁移:linked(带 linked_entity_id)/ignored/pending(回退清关联),重算。"""
    async with pool.acquire() as conn:
        if status == "linked":
            await conn.execute(
                "UPDATE shot_extracted_candidates SET candidate_status='linked', "
                "linked_entity_id=$2, confirmed_at=now() WHERE id=$1",
                candidate_id,
                linked_entity_id,
            )
        elif status == "ignored":
            await conn.execute(
                "UPDATE shot_extracted_candidates SET candidate_status='ignored', "
                "confirmed_at=now() WHERE id=$1",
                candidate_id,
            )
        else:  # pending 回退(§A.2:删除关联/替换/清空 → 候选自动回退)
            await conn.execute(
                "UPDATE shot_extracted_candidates SET candidate_status='pending', "
                "linked_entity_id=NULL, confirmed_at=NULL WHERE id=$1",
                candidate_id,
            )
        return await _recompute(conn, work_id, shot_id)


async def set_dialogue_candidate(
    pool: Any,
    work_id: str,
    shot_id: str,
    candidate_id: Any,
    *,
    status: str,
    linked_dialog_line_id: str | None,
) -> str:
    """§G 对白候选状态迁移:accepted(写入 ShotDialogLine 后带 id)/ignored/pending(回退),重算。"""
    async with pool.acquire() as conn:
        if status == "accepted":
            await conn.execute(
                "UPDATE shot_extracted_dialogue_candidates SET candidate_status='accepted', "
                "linked_dialog_line_id=$2, confirmed_at=now() WHERE id=$1",
                candidate_id,
                linked_dialog_line_id,
            )
        elif status == "ignored":
            await conn.execute(
                "UPDATE shot_extracted_dialogue_candidates SET candidate_status='ignored', "
                "confirmed_at=now() WHERE id=$1",
                candidate_id,
            )
        else:
            await conn.execute(
                "UPDATE shot_extracted_dialogue_candidates SET candidate_status='pending', "
                "linked_dialog_line_id=NULL, confirmed_at=NULL WHERE id=$1",
                candidate_id,
            )
        return await _recompute(conn, work_id, shot_id)


async def set_skip_extraction(pool: Any, work_id: str, shot_id: str, value: bool) -> str:
    """§I 逃生阀:置 skip_extraction 并重算(true → 直达 ready)。"""
    async with pool.acquire() as conn:
        await ensure_readiness_row(conn, work_id, shot_id)
        await conn.execute(
            "UPDATE shot_readiness SET skip_extraction=$3 WHERE work_id=$1 AND shot_id=$2",
            work_id,
            shot_id,
            value,
        )
        return await _recompute(conn, work_id, shot_id)


async def get_preparation_state(
    pool: Any, work_id: str, shot_id: str, shot: ShotListItem | None
) -> dict[str, Any]:
    """§L.1 聚合准备态。"""
    async with pool.acquire() as conn:
        await ensure_readiness_row(conn, work_id, shot_id)
        readiness = await _fetch_readiness(conn, work_id, shot_id) or {"shot_id": shot_id}
        assets = await _fetch_candidates(conn, work_id, shot_id)
        dialogue = await _fetch_dialogue(conn, work_id, shot_id)
    return build_preparation_state(
        shot=shot, readiness=readiness, asset_rows=assets, dialogue_rows=dialogue
    )


async def all_shots_ready(pool: Any, work_id: str, shot_ids: list[str]) -> bool:
    """整部是否可产集:每镜 readiness.status 都 ready(缺行=未准备=未就绪)。"""
    if not shot_ids:
        return False
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT shot_id, status FROM shot_readiness "
            "WHERE work_id=$1 AND shot_id = ANY($2::text[])",
            work_id,
            shot_ids,
        )
    by_id = {r["shot_id"]: r["status"] for r in rows}
    return all(by_id.get(sid) == "ready" for sid in shot_ids)


async def produce_blockers(pool: Any, work_id: str) -> list[str]:
    """§L.2 产集拦截:被用户实际动过(extracted=true)却仍 pending 的镜头 shot_id。空 = 可产集。
    只看 extracted+pending——只 GET 看过状态(extracted=false)或从未准备的旧 work 不拦(向后兼容)。"""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT shot_id FROM shot_readiness "
            "WHERE work_id=$1 AND extracted=true AND status='pending'",
            work_id,
        )
    return [r["shot_id"] for r in rows]


async def readiness_overview(pool: Any, work_id: str) -> list[dict[str, Any]]:
    """§L.1 全片就绪概览(已被准备过的镜头行);前端与 shot_list 合并出完整视图。"""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT shot_id, status, skip_extraction, extracted "
            "FROM shot_readiness WHERE work_id=$1",
            work_id,
        )
    return [dict(r) for r in rows]
