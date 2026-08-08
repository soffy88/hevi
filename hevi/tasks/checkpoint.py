"""hevi.tasks.checkpoint — Task 断点续跑(对标 DramaClaw Task Center)。

失败/中断的长任务从**已完成的阶段**续跑,而非整条重跑:
checkpoint 记录 {stage, completed_shots, total_shots, config_json} 等进度锚点,
resume 时按锚点决策"从哪续/跳过什么"。纯机制:CheckpointStore(内存/可换
持久化) + 决策函数,装配层(TaskService/API)接入 repository。

resume 策略(确定性):
- status 为 failed/cancelled 且存在 checkpoint → 可续跑
- checkpoint.stage 为"装配成片"等终局阶段且已完成 → 无需续跑(已完成)
- 否则返回续跑建议: 重入队 + 携带 checkpoint(跳过已完成 shots/阶段)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

RESUMABLE_STATUSES = frozenset({"failed", "cancelled", "interrupted"})

# 终局阶段: 到达即视为"只剩收尾",续跑收益低
_TERMINAL_STAGES = frozenset({"装配成片", "合成导出", "completed"})


@dataclass
class Checkpoint:
    task_id: UUID
    stage: str = ""
    completed_shots: int = 0
    total_shots: int = 0
    progress_pct: float = 0.0
    config_json: dict[str, Any] = field(default_factory=dict)
    resumed_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": str(self.task_id),
            "stage": self.stage,
            "completed_shots": self.completed_shots,
            "total_shots": self.total_shots,
            "progress_pct": self.progress_pct,
            "resumed_count": self.resumed_count,
        }


class CheckpointStore:
    """checkpoint 存取(进程内存; 装配层可换 Redis/DB)。"""

    def __init__(self) -> None:
        self._checkpoints: dict[str, Checkpoint] = {}

    def save(self, cp: Checkpoint) -> None:
        self._checkpoints[str(cp.task_id)] = cp

    def get(self, task_id: UUID) -> Checkpoint | None:
        return self._checkpoints.get(str(task_id))

    def clear(self, task_id: UUID) -> None:
        self._checkpoints.pop(str(task_id), None)

    def list(self) -> list[Checkpoint]:
        return list(self._checkpoints.values())


def build_checkpoint_from_task(task: dict[str, Any]) -> Checkpoint | None:
    """从 repository 的 task 行构建 checkpoint(无进度锚点 → None)。"""
    if not task:
        return None
    cfg = task.get("config_json") or {}
    if isinstance(cfg, str):
        import json

        try:
            cfg = json.loads(cfg)
        except json.JSONDecodeError:
            cfg = {}
    return Checkpoint(
        task_id=UUID(str(task["task_id"])),
        stage=str(task.get("stage") or (cfg.get("stage") or "")),
        completed_shots=int(task.get("completed_shots") or 0),
        total_shots=int(task.get("total_shots") or 0),
        progress_pct=float(task.get("progress_pct") or 0.0),
        config_json=cfg if isinstance(cfg, dict) else {},
    )


def resume_decision(task: dict[str, Any], cp: Checkpoint | None) -> dict[str, Any]:
    """续跑决策: 能否续、从哪续、跳过什么。确定性,不调 LLM。"""
    status = str(task.get("status") or "")
    if status not in RESUMABLE_STATUSES:
        return {
            "resumable": False,
            "reason": f"status={status} 不可续跑(仅 {sorted(RESUMABLE_STATUSES)})",
        }
    if cp is None:
        return {"resumable": False, "reason": "无 checkpoint,建议整条重跑"}
    if cp.stage in _TERMINAL_STAGES or cp.progress_pct >= 100:
        return {"resumable": False, "reason": "已到终局阶段,无需续跑"}
    skipped = max(0, cp.completed_shots)
    return {
        "resumable": True,
        "reason": "从断点续跑",
        "stage": cp.stage,
        "completed_shots": cp.completed_shots,
        "total_shots": cp.total_shots,
        "skip_shots": skipped,  # 续跑时跳过已完成镜头
        "resumed_count": cp.resumed_count + 1,
    }
