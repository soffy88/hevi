"""hevi.backlot —— 活态制片状态板后端(3O obase 风格, 差距 B7 后端部分)。

对标 OpenMontage Backlot(阶段亮灯/脚本落屏/花费上墙/contact sheet 审批/回放),
hevi 此前只有事后 verdict 与导演台 DP2, 无**运行中**的生产事件流。

本包为后端事件流 + 简单状态 API(前端板后续排期):
  - `BacklotEvent`: 一次生产事件的不可变记录(run_id/stage/event_type/payload/ts)
  - `BacklotEventLog`: JSONL 追加持久化(与 replay_trace/decision_trail 同风格,
    无 DB 依赖) + 内存尾部缓存(最近 N 条, 供状态板即时查询)
  - `backlot_status()`: run 级汇总(阶段亮灯/事件计数/最后心跳/花费估算输入)
  - 事件类型约定: stage_start / stage_done / stage_fail / shot_done / cost /
    heartbeat / note —— 消费方(流水线打点)按需 emit。

3O 归属: obase 边界(best-effort 打点, 任何失败不阻断主流水线)。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 事件类型约定(消费方可扩展; 未知类型不拒绝, 仅透传)
EVENT_STAGE_START = "stage_start"
EVENT_STAGE_DONE = "stage_done"
EVENT_STAGE_FAIL = "stage_fail"
EVENT_SHOT_DONE = "shot_done"
EVENT_COST = "cost"
EVENT_HEARTBEAT = "heartbeat"
EVENT_NOTE = "note"

# 内存尾部缓存条数(状态板即时查询窗口)
_TAIL_LIMIT = 200


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class BacklotEvent:
    """一次生产事件(不可变)。payload 必须 JSON 可序列化。"""

    run_id: str
    stage: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "stage": self.stage,
            "event_type": self.event_type,
            "payload": self.payload,
            "ts": self.ts,
        }


class BacklotEventLog:
    """JSONL 事件日志: 追加写 + 内存尾部缓存。

    - 每 run 一个文件: <root>/<run_id>.jsonl
    - 写失败仅记日志(best-effort, 不阻断主流水线)
    - events() 返回内存缓存(最近 _TAIL_LIMIT 条), 不入库重读
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._tail: dict[str, list[BacklotEvent]] = {}

    def _file_for(self, run_id: str) -> Path:
        # run_id 防路径穿越: 仅允许 [A-Za-z0-9_-], 含路径分隔符/.. /空 → 拒绝
        if not run_id or any(ch in run_id for ch in ("/", "\\", "..")):
            raise ValueError(f"invalid run_id: {run_id!r}")
        safe = "".join(c for c in run_id if c.isalnum() or c in "_-")
        if not safe:
            raise ValueError(f"invalid run_id: {run_id!r}")
        return self.root / f"{safe}.jsonl"

    def emit(self, event: BacklotEvent) -> None:
        """追加一条事件(内存缓存 + JSONL 落盘)。失败仅记日志。"""
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with self._file_for(event.run_id).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("backlot emit failed (%s): %s", event.run_id, exc)
            return
        tail = self._tail.setdefault(event.run_id, [])
        tail.append(event)
        if len(tail) > _TAIL_LIMIT:
            del tail[: len(tail) - _TAIL_LIMIT]

    def events(self, run_id: str, *, limit: int = 100) -> list[BacklotEvent]:
        """最近事件(内存缓存, 按时间序)。limit 截取末尾。"""
        tail = self._tail.get(run_id, [])
        return tail[-limit:] if limit > 0 else tail

    def count(self, run_id: str) -> int:
        return len(self._tail.get(run_id, []))

    def replay_from_disk(self, run_id: str) -> list[BacklotEvent]:
        """从 JSONL 完整回放(冷启动/审计; 与内存缓存独立)。"""
        try:
            lines = self._file_for(run_id).read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out: list[BacklotEvent] = []
        for line in lines:
            try:
                d = json.loads(line)
                out.append(
                    BacklotEvent(
                        run_id=d["run_id"],
                        stage=d["stage"],
                        event_type=d["event_type"],
                        payload=d.get("payload", {}),
                        ts=d.get("ts", ""),
                    )
                )
            except (json.JSONDecodeError, KeyError):
                continue
        return out


# ---------------------------------------------------------------------------
# 状态汇总
# ---------------------------------------------------------------------------


def backlot_status(
    log: BacklotEventLog, run_id: str
) -> dict[str, Any]:
    """run 级状态汇总(阶段亮灯/事件计数/最后心跳/花费估算输入)。

    纯派生, 不落盘; 供 GET /api/backlot/runs/{run_id}/status 消费。
    """
    events = log.events(run_id)
    stages: dict[str, str] = {}
    cost_usd = 0.0
    last_heartbeat: str | None = None
    failed = False
    for ev in events:
        if ev.event_type in (EVENT_STAGE_START, EVENT_STAGE_DONE, EVENT_STAGE_FAIL):
            stages[ev.stage] = ev.event_type
            if ev.event_type == EVENT_STAGE_FAIL:
                failed = True
        elif ev.event_type == EVENT_COST:
            cost_usd += float(ev.payload.get("usd", 0.0) or 0.0)
        elif ev.event_type == EVENT_HEARTBEAT:
            last_heartbeat = ev.ts
    return {
        "run_id": run_id,
        "event_count": len(events),
        "stages": stages,
        "cost_usd": round(cost_usd, 4),
        "last_heartbeat": last_heartbeat,
        "failed": failed,
        "updated_at": events[-1].ts if events else None,
    }


__all__ = [
    "EVENT_COST",
    "EVENT_HEARTBEAT",
    "EVENT_NOTE",
    "EVENT_SHOT_DONE",
    "EVENT_STAGE_DONE",
    "EVENT_STAGE_FAIL",
    "EVENT_STAGE_START",
    "BacklotEvent",
    "BacklotEventLog",
    "backlot_status",
]
