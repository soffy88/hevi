"""镜头准备工作流 —— 候选确认机制。

对标 Jellyfish 的 Shot Preparation Workflow:
  script breakdown → shot preparation → candidate confirmation → shot ready → generation

核心概念:
- Shot 有准备状态(preparation_state): draft → preparing → ready
- 每个 Shot 有资产候选(candidates): 角色/场景/道具/对白
- 候选可被 accept(接受)/ignore(忽略)/link(关联已有)
- 只有所有必需候选都已确认, Shot 才能进入 ready 状态
"""

from hevi.preparation.models import (
    CandidateStatus,
    CandidateType,
    PreparationState,
    ShotCandidate,
    ShotPreparation,
)
from hevi.preparation.service import PreparationService

__all__ = [
    "CandidateStatus",
    "CandidateType",
    "PreparationService",
    "PreparationState",
    "ShotCandidate",
    "ShotPreparation",
]
