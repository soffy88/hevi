"""hevi.freezone — Freezone 无限画布(对标 DramaClaw Freezone)。

主线流水线之外的"自由探索"双轨:节点画布拖入资产生成图/视频/音频,
满意候选提升回主线。机制(graph/candidates)与装配(service)分离。
"""

from hevi.freezone.candidates import (
    CANDIDATE,
    PROMOTED,
    REJECTED,
    Candidate,
    CandidatePool,
)
from hevi.freezone.graph import (
    FreezoneGraph,
    GraphCycleError,
    NodeResult,
    NodeSpec,
)
from hevi.freezone.service import (
    FreezoneRun,
    FreezoneService,
)

__all__ = [
    "CANDIDATE",
    "PROMOTED",
    "REJECTED",
    "Candidate",
    "CandidatePool",
    "FreezoneGraph",
    "FreezoneRun",
    "FreezoneService",
    "GraphCycleError",
    "NodeResult",
    "NodeSpec",
]
