"""DirectorWorksRepository — 导演管线锁定产物落库(P0,2026-07-23)。

`director_pipeline._WORKS` 是内存字典,进程一死作品全丢(批C $15.711 产集的 locked
scene_script 就这么没的,A/B 对照做不成)。这个 repo 把内存 rec 镜像进 `director_works`
表——每次锁定/产集把五卷锁定产物 + 状态落库,成片可反查确切输入。内存字典仍是工作态主存,
DB 是持久化镜像(持久化失败不阻断产集,best-effort)。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from obase.persistence import PgPool, query, read_one, upsert_batch

# _WORKS rec 里要落库的键 → director_works 列(其余内存态键如 video_task_id 单独处理)
_VOLUME_KEYS = ("concept", "screenplay", "design_list", "world_bible", "scene_script")


def _rec_to_row(work_id: str, rec: dict[str, Any]) -> dict[str, Any]:
    """内存 _WORKS rec → director_works 行(纯函数,便于单测)。五卷取原样 dict(可为 None),
    标量字段给缺省,updated_at 每次刷新。"""
    row: dict[str, Any] = {
        "work_id": work_id,
        "user_id": rec.get("user_id"),
        "status": rec.get("status") or "",
        "locked_through": int(rec.get("locked_through", -1)),
        "visual_style": rec.get("visual_style") or "realistic",
        "material_text": rec.get("material_text") or "",
        "video_task_id": rec.get("video_task_id"),
        "updated_at": datetime.now(UTC).replace(tzinfo=None),
    }
    for k in _VOLUME_KEYS:
        row[k] = rec.get(k)
    return row


class DirectorWorksRepository:
    def __init__(self, pool: PgPool):
        self.pool = pool

    async def upsert_work(self, work_id: str, rec: dict[str, Any]) -> None:
        """按 work_id upsert 整行(存在则更新全部非主键列,不存在则插入)。冲突动作必须是
        DO UPDATE(不是 DO NOTHING)——同一个 work 从 concept 一路锁到 scene_script、再产集
        回填 video_task_id,每一步都是对同一行的更新,DO NOTHING 会把后续锁定全部丢弃。"""
        row = _rec_to_row(work_id, rec)
        await upsert_batch(
            pool=self.pool,
            table="director_works",
            rows=[row],
            conflict_columns=["work_id"],
            update_columns=[c for c in row if c != "work_id"],
        )

    async def get_work(self, work_id: str) -> dict[str, Any] | None:
        return await read_one(self.pool, table="director_works", id=work_id, id_column="work_id")

    async def get_by_task(self, video_task_id: str) -> dict[str, Any] | None:
        """从成片 task 反查产出它的 work(A/B 对照:拿到确切锁定输入)。"""
        rows = await query(
            self.pool,
            sql="SELECT * FROM director_works WHERE video_task_id = $1 LIMIT 1",
            params=[video_task_id],
        )
        return rows[0] if rows else None

    async def list_works(self, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return await query(
            self.pool,
            sql="SELECT * FROM director_works WHERE user_id = $1 ORDER BY updated_at DESC",
            params=[user_id],
            limit=limit,
        )
