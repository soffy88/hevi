"""hevi.freezone.candidates — Freezone 候选池机制。

画布探索产出 -> 候选(Candidate) -> 满意则提升(promote)回主线
(如挂到 Series/Episode 的 shot / 资产库)。状态机:
candidate -> promoted | rejected。纯内存,装配层可持久化。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

CANDIDATE = "candidate"
PROMOTED = "promoted"
REJECTED = "rejected"


@dataclass
class Candidate:
    id: str
    node_id: str
    kind: str
    output: Any
    score: float = 0.0
    note: str = ""
    status: str = CANDIDATE
    promote_target: str = ""  # 提升目标,如 "series:1:episode:3:shot:5"
    created_at: float = field(default_factory=lambda: 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "node_id": self.node_id,
            "kind": self.kind,
            "score": self.score,
            "note": self.note,
            "status": self.status,
            "promote_target": self.promote_target,
            "output": _serialize(self.output),
        }


def _serialize(output: Any) -> Any:
    if isinstance(output, (str, int, float, bool)) or output is None:
        return output
    if isinstance(output, dict):
        return {k: _serialize(v) for k, v in output.items()}
    if isinstance(output, (list, tuple)):
        return [_serialize(v) for v in output]
    return str(output)


class CandidatePool:
    """候选池:收集画布产出,支持提升/拒绝。"""

    def __init__(self) -> None:
        self._candidates: dict[str, Candidate] = {}

    def add(
        self,
        *,
        node_id: str,
        kind: str,
        output: Any,
        score: float = 0.0,
        note: str = "",
    ) -> Candidate:
        c = Candidate(
            id=f"cand_{uuid4().hex[:12]}",
            node_id=node_id,
            kind=kind,
            output=output,
            score=score,
            note=note,
        )
        self._candidates[c.id] = c
        return c

    def promote(self, candidate_id: str, target: str) -> bool:
        c = self._candidates.get(candidate_id)
        if c is None or c.status != CANDIDATE:
            return False
        c.status = PROMOTED
        c.promote_target = target
        return True

    def reject(self, candidate_id: str) -> bool:
        c = self._candidates.get(candidate_id)
        if c is None or c.status != CANDIDATE:
            return False
        c.status = REJECTED
        return True

    def list(self, status: str | None = None) -> list[Candidate]:
        items = list(self._candidates.values())
        if status is not None:
            items = [c for c in items if c.status == status]
        return sorted(items, key=lambda c: c.score, reverse=True)

    def get(self, candidate_id: str) -> Candidate | None:
        return self._candidates.get(candidate_id)
