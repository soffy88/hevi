"""镜头准备工作流服务。

管理 Shot 的准备生命周期:
  提取候选 → 确认/忽略 → 关联资产 → 标记 ready → 触发生成
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from hevi.preparation.models import (
    CandidateStatus,
    CandidateType,
    PreparationState,
    ShotCandidate,
    ShotPreparation,
)

logger = logging.getLogger(__name__)


class PreparationService:
    """镜头准备工作流服务。

    内存存储(同 shortdrama._RUNS 模式),生产环境可换 DB 持久化。
    """

    def __init__(self) -> None:
        self._preparations: dict[str, ShotPreparation] = {}  # shot_id → ShotPreparation
        self._task_shots: dict[str, list[str]] = {}  # task_id → [shot_id, ...]

    def create_preparation(
        self,
        *,
        task_id: str,
        shot_id: str | None = None,
        shot_title: str = "",
        shot_summary: str = "",
    ) -> ShotPreparation:
        """创建镜头准备记录。"""
        shot_id = shot_id or f"shot_{uuid.uuid4().hex[:8]}"
        prep = ShotPreparation(
            shot_id=shot_id,
            task_id=task_id,
            shot_title=shot_title,
            shot_summary=shot_summary,
        )
        self._preparations[shot_id] = prep
        self._task_shots.setdefault(task_id, []).append(shot_id)
        logger.info("Created preparation for shot %s (task %s)", shot_id, task_id)
        return prep

    def get_preparation(self, shot_id: str) -> ShotPreparation | None:
        return self._preparations.get(shot_id)

    def list_preparations(self, task_id: str) -> list[ShotPreparation]:
        shot_ids = self._task_shots.get(task_id, [])
        return [self._preparations[sid] for sid in shot_ids if sid in self._preparations]

    def add_candidates(
        self,
        shot_id: str,
        candidates: list[dict[str, Any]],
    ) -> list[ShotCandidate]:
        """批量添加候选。

        candidates: [{"type": "character", "name": "张三", "confidence": 0.9}, ...]
        """
        prep = self._preparations.get(shot_id)
        if prep is None:
            raise ValueError(f"Shot {shot_id} not found")

        added: list[ShotCandidate] = []
        for cd in candidates:
            candidate = ShotCandidate(
                id=f"cand_{uuid.uuid4().hex[:8]}",
                candidate_type=CandidateType(cd["type"]),
                name=cd["name"],
                confidence=cd.get("confidence", 0.0),
                metadata=cd.get("metadata", {}),
            )
            prep.add_candidate(candidate)
            added.append(candidate)

        logger.info("Added %d candidates to shot %s", len(added), shot_id)
        return added

    def accept_candidate(self, shot_id: str, candidate_id: str) -> ShotCandidate | None:
        """接受候选。"""
        prep = self._preparations.get(shot_id)
        if prep is None:
            return None
        for c in prep.candidates:
            if c.id == candidate_id:
                c.accept()
                prep.check_ready()
                logger.info("Accepted candidate %s in shot %s", candidate_id, shot_id)
                return c
        return None

    def ignore_candidate(self, shot_id: str, candidate_id: str) -> ShotCandidate | None:
        """忽略候选。"""
        prep = self._preparations.get(shot_id)
        if prep is None:
            return None
        for c in prep.candidates:
            if c.id == candidate_id:
                c.ignore()
                prep.check_ready()
                logger.info("Ignored candidate %s in shot %s", candidate_id, shot_id)
                return c
        return None

    def link_candidate(
        self, shot_id: str, candidate_id: str, asset_id: str
    ) -> ShotCandidate | None:
        """关联候选到已有资产。"""
        prep = self._preparations.get(shot_id)
        if prep is None:
            return None
        for c in prep.candidates:
            if c.id == candidate_id:
                c.link(asset_id)
                prep.check_ready()
                logger.info(
                    "Linked candidate %s → asset %s in shot %s",
                    candidate_id,
                    asset_id,
                    shot_id,
                )
                return c
        return None

    def refresh_candidates(
        self, shot_id: str, new_candidates: list[dict[str, Any]]
    ) -> list[ShotCandidate]:
        """刷新候选:清除已忽略的,保留已接受的,添加新的。"""
        prep = self._preparations.get(shot_id)
        if prep is None:
            raise ValueError(f"Shot {shot_id} not found")

        # 保留已接受/已关联的
        kept = [
            c
            for c in prep.candidates
            if c.status in (CandidateStatus.ACCEPTED, CandidateStatus.LINKED)
        ]
        prep.candidates = kept

        # 添加新候选
        return self.add_candidates(shot_id, new_candidates)

    def mark_ready(self, shot_id: str) -> bool:
        """手动标记 ready(覆盖自动检查)。"""
        prep = self._preparations.get(shot_id)
        if prep is None:
            return False
        prep.state = PreparationState.READY
        logger.info("Shot %s marked ready", shot_id)
        return True

    def get_ready_shots(self, task_id: str) -> list[str]:
        """获取任务下所有 ready 状态的镜头。"""
        preps = self.list_preparations(task_id)
        return [p.shot_id for p in preps if p.state == PreparationState.READY]

    def get_stats(self, task_id: str) -> dict[str, Any]:
        """任务准备统计。"""
        preps = self.list_preparations(task_id)
        states: dict[str, int] = {"draft": 0, "preparing": 0, "ready": 0}
        total_candidates = 0
        pending_candidates = 0
        for p in preps:
            states[p.state.value] = states.get(p.state.value, 0) + 1
            total_candidates += len(p.candidates)
            pending_candidates += len(p.pending_candidates)

        return {
            "task_id": task_id,
            "total_shots": len(preps),
            "states": states,
            "total_candidates": total_candidates,
            "pending_candidates": pending_candidates,
        }
