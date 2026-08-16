"""运行时持久化 —— SQLite 统一存储(3O 内化 Round 3g)。

此前 replay_trace / convergence / promotion 都是 JSON/内存(重启即失)。这里用
stdlib sqlite3(无新依赖)做统一落库:
  - replay_traces:导演决策痕迹(可回放)
  - convergence_rounds:返工轮次
  - promotion_pools:候选/主线快照(JSON blob)
  - failure_hits:失败模式命中统计

全部同步小表,测试用 tmp 库;写失败不阻断主链(best-effort 与 replay_trace 同纪律)。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS replay_traces (
    trace_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS convergence_rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_num INTEGER, phase TEXT, round_num INTEGER,
    residual_count INTEGER, fixed_count INTEGER, new_failures TEXT,
    UNIQUE(episode_num, phase, round_num)
);
CREATE TABLE IF NOT EXISTS promotion_pools (
    project_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS failure_hits (
    code TEXT PRIMARY KEY,
    hits INTEGER NOT NULL DEFAULT 0
);
"""


class RuntimeStore:
    """统一 SQLite 存储。"""

    def __init__(self, db_path: str | Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ── replay_traces ──
    def save_replay(self, data: dict[str, Any]) -> None:
        trace_id = data.get("trace_id", "")
        self._conn.execute(
            "INSERT OR REPLACE INTO replay_traces (trace_id, data) VALUES (?, ?)",
            (trace_id, json.dumps(data, ensure_ascii=False)),
        )
        self._conn.commit()

    def list_replays(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT data FROM replay_traces ORDER BY rowid DESC LIMIT ?", (limit,)
        ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def count_replays(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM replay_traces").fetchone()[0])

    # ── convergence_rounds ──
    def save_convergence_round(
        self, *, episode_num: int, phase: str, round_num: int,
        residual_count: int, fixed_count: int, new_failures: list[str] | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO convergence_rounds "
            "(episode_num, phase, round_num, residual_count, fixed_count, new_failures) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (episode_num, phase, round_num, residual_count, fixed_count,
             json.dumps(new_failures or [], ensure_ascii=False)),
        )
        self._conn.commit()

    def list_rounds(self, *, episode_num: int | None = None) -> list[dict[str, Any]]:
        if episode_num is None:
            rows = self._conn.execute(
                "SELECT * FROM convergence_rounds ORDER BY episode_num, round_num"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM convergence_rounds WHERE episode_num = ? ORDER BY round_num",
                (episode_num,),
            ).fetchall()
        return [
            {
                "episode_num": r[1], "phase": r[2], "round_num": r[3],
                "residual_count": r[4], "fixed_count": r[5],
                "new_failures": json.loads(r[6] or "[]"),
            }
            for r in rows
        ]

    # ── promotion_pools ──
    def save_promotion_pool(self, project_id: str, pool_data: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO promotion_pools (project_id, data) VALUES (?, ?)",
            (project_id, json.dumps(pool_data, ensure_ascii=False)),
        )
        self._conn.commit()

    def load_promotion_pool(self, project_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT data FROM promotion_pools WHERE project_id = ?", (project_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    # ── failure_hits ──
    def bump_failure_hit(self, code: str) -> None:
        self._conn.execute(
            "INSERT INTO failure_hits (code, hits) VALUES (?, 1) "
            "ON CONFLICT(code) DO UPDATE SET hits = hits + 1",
            (code,),
        )
        self._conn.commit()

    def failure_hits(self) -> dict[str, int]:
        return dict(self._conn.execute("SELECT code, hits FROM failure_hits"))
