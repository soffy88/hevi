"""hevi.freezone.candidates — Freezone 候选池机制。

画布探索产出 -> 候选(Candidate) -> 满意则提升(promote)回主线
(如挂到 Series/Episode 的 shot / 资产库)。状态机:
candidate -> promoted | rejected。纯内存,装配层可持久化。

Provenance: 每个候选记录 user_id / run_id / graph_id,支撑租户隔离与
FREEZONE_RESTART_RECOVERY。
"""

from __future__ import annotations

import builtins
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
    user_id: str = ""
    run_id: str = ""
    graph_id: str = ""

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
            "user_id": self.user_id,
            "run_id": self.run_id,
            "graph_id": self.graph_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Candidate:
        return cls(
            id=str(data.get("id") or ""),
            node_id=str(data.get("node_id") or ""),
            kind=str(data.get("kind") or ""),
            output=data.get("output"),
            score=float(data.get("score") or 0.0),
            note=str(data.get("note") or ""),
            status=str(data.get("status") or CANDIDATE),
            promote_target=str(data.get("promote_target") or ""),
            created_at=float(data.get("created_at") or 0.0),
            user_id=str(data.get("user_id") or ""),
            run_id=str(data.get("run_id") or ""),
            graph_id=str(data.get("graph_id") or ""),
        )


def _serialize(output: Any) -> Any:
    if isinstance(output, (str, int, float, bool)) or output is None:
        return output
    if isinstance(output, dict):
        return {k: _serialize(v) for k, v in output.items()}
    if isinstance(output, (list, tuple)):
        return [_serialize(v) for v in output]
    return str(output)


class CandidatePool:
    """候选池:收集画布产出,支持提升/拒绝。可按 user_id 过滤。"""

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
        user_id: str = "",
        run_id: str = "",
        graph_id: str = "",
    ) -> Candidate:
        c = Candidate(
            id=f"cand_{uuid4().hex[:12]}",
            node_id=node_id,
            kind=kind,
            output=output,
            score=score,
            note=note,
            user_id=user_id,
            run_id=run_id,
            graph_id=graph_id,
        )
        self._candidates[c.id] = c
        return c

    def promote(self, candidate_id: str, target: str, *, user_id: str = "") -> bool:
        c = self._candidates.get(candidate_id)
        if c is None or c.status != CANDIDATE:
            return False
        if user_id and c.user_id and c.user_id != user_id:
            return False
        c.status = PROMOTED
        c.promote_target = target
        return True

    def reject(self, candidate_id: str, *, user_id: str = "") -> bool:
        c = self._candidates.get(candidate_id)
        if c is None or c.status != CANDIDATE:
            return False
        if user_id and c.user_id and c.user_id != user_id:
            return False
        c.status = REJECTED
        return True

    def list(
        self, status: str | None = None, *, user_id: str | None = None
    ) -> builtins.list[Candidate]:
        items = builtins.list(self._candidates.values())
        if status is not None:
            items = [c for c in items if c.status == status]
        if user_id is not None:
            items = [c for c in items if c.user_id == user_id]
        return sorted(items, key=lambda c: c.score, reverse=True)

    def get(self, candidate_id: str) -> Candidate | None:
        return self._candidates.get(candidate_id)

    def owned_by(self, candidate_id: str, user_id: str) -> bool:
        c = self._candidates.get(candidate_id)
        return c is not None and c.user_id == user_id

    def dump(self) -> builtins.list[dict[str, Any]]:
        return [c.to_dict() for c in self._candidates.values()]

    def load_rows(self, rows: builtins.list[dict[str, Any]]) -> None:
        for row in rows:
            try:
                c = Candidate.from_dict(row)
            except (TypeError, ValueError, KeyError):
                continue
            if c.id:
                self._candidates[c.id] = c
