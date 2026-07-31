"""镜头准备数据模型。

PreparationState: 镜头准备状态机
  draft → preparing → ready
  - draft: 刚创建,未开始准备
  - preparing: 正在准备,候选已提取
  - ready: 所有必需候选已确认,可以生成

CandidateStatus: 候选状态
  pending → accepted | ignored | linked
  - pending: 待确认
  - accepted: 已接受(使用此候选)
  - ignored: 已忽略(跳过此候选)
  - linked: 已关联到已有资产

CandidateType: 候选类型
  character / scene / prop / costume / dialogue
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PreparationState(str, Enum):
    """镜头准备状态。"""

    DRAFT = "draft"
    PREPARING = "preparing"
    READY = "ready"


class CandidateStatus(str, Enum):
    """候选状态。"""

    PENDING = "pending"
    ACCEPTED = "accepted"
    IGNORED = "ignored"
    LINKED = "linked"


class CandidateType(str, Enum):
    """候选类型。"""

    CHARACTER = "character"
    SCENE = "scene"
    PROP = "prop"
    COSTUME = "costume"
    DIALOGUE = "dialogue"


@dataclass
class ShotCandidate:
    """单个候选项。"""

    id: str
    candidate_type: CandidateType
    name: str  # 候选名称(角色名/场景名/道具名/对白文本)
    confidence: float = 0.0  # 提取置信度 0-1
    status: CandidateStatus = CandidateStatus.PENDING
    linked_id: str | None = None  # 关联到已有资产的 ID
    metadata: dict[str, Any] = field(default_factory=dict)

    def accept(self) -> None:
        self.status = CandidateStatus.ACCEPTED

    def ignore(self) -> None:
        self.status = CandidateStatus.IGNORED

    def link(self, asset_id: str) -> None:
        self.linked_id = asset_id
        self.status = CandidateStatus.LINKED


@dataclass
class ShotPreparation:
    """镜头准备记录。"""

    shot_id: str
    task_id: str
    state: PreparationState = PreparationState.DRAFT
    candidates: list[ShotCandidate] = field(default_factory=list)
    shot_title: str = ""
    shot_summary: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def pending_candidates(self) -> list[ShotCandidate]:
        return [c for c in self.candidates if c.status == CandidateStatus.PENDING]

    @property
    def accepted_candidates(self) -> list[ShotCandidate]:
        return [
            c
            for c in self.candidates
            if c.status in (CandidateStatus.ACCEPTED, CandidateStatus.LINKED)
        ]

    def get_candidates_by_type(self, ctype: CandidateType) -> list[ShotCandidate]:
        return [c for c in self.candidates if c.candidate_type == ctype]

    def is_ready(self) -> bool:
        """检查是否所有必需候选都已确认。

        规则:
        - 至少一个角色候选已确认(如果有角色候选)
        - 至少一个场景候选已确认(如果有场景候选)
        - 对白/道具/服装可选
        """
        char_candidates = self.get_candidates_by_type(CandidateType.CHARACTER)
        if char_candidates and not any(
            c.status in (CandidateStatus.ACCEPTED, CandidateStatus.LINKED)
            for c in char_candidates
        ):
            return False

        scene_candidates = self.get_candidates_by_type(CandidateType.SCENE)
        if scene_candidates and not any(
            c.status in (CandidateStatus.ACCEPTED, CandidateStatus.LINKED)
            for c in scene_candidates
        ):
            return False

        return True

    def check_ready(self) -> PreparationState:
        """更新准备状态。"""
        if self.state == PreparationState.DRAFT:
            return self.state
        if self.is_ready():
            self.state = PreparationState.READY
        return self.state

    def add_candidate(self, candidate: ShotCandidate) -> None:
        self.candidates.append(candidate)
        if self.state == PreparationState.DRAFT:
            self.state = PreparationState.PREPARING

    def to_dict(self) -> dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "task_id": self.task_id,
            "state": self.state.value,
            "shot_title": self.shot_title,
            "shot_summary": self.shot_summary,
            "candidates": [
                {
                    "id": c.id,
                    "type": c.candidate_type.value,
                    "name": c.name,
                    "confidence": c.confidence,
                    "status": c.status.value,
                    "linked_id": c.linked_id,
                    "metadata": c.metadata,
                }
                for c in self.candidates
            ],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ShotPreparation:
        candidates = []
        for cd in data.get("candidates", []):
            candidates.append(
                ShotCandidate(
                    id=cd["id"],
                    candidate_type=CandidateType(cd["type"]),
                    name=cd["name"],
                    confidence=cd.get("confidence", 0.0),
                    status=CandidateStatus(cd.get("status", "pending")),
                    linked_id=cd.get("linked_id"),
                    metadata=cd.get("metadata", {}),
                )
            )
        return cls(
            shot_id=data["shot_id"],
            task_id=data["task_id"],
            state=PreparationState(data.get("state", "draft")),
            candidates=candidates,
            shot_title=data.get("shot_title", ""),
            shot_summary=data.get("shot_summary", ""),
            metadata=data.get("metadata", {}),
        )
