"""候选提升双轨 —— 探索候选 → 主线锁定(3O 内化 Round 3e,来源 dramaclaw promotion 服务)。

dramaclaw 的 character_promotion_service / prop_promotion_service:探索画布/图池里生成的
候选(不是主线产物),经评分/审核后**提升(promote)为主线资产**,或**驳回(reject)并记原因**;
主线与探索双轨并存,只有提升才进主线。这正是 HEVI-ARCH"资产供应链:检索优先生成兜底"
的消费侧 —— hevi 此前只有"生成即锁定",没有"候选→评审→提升"的双轨。

本模块为 hevi 暂驻(待上游 `oskill.candidate_promotion`):
  - PromotionPool:每资产类型(character/prop/scene)的候选池 + 提升/驳回台账。
  - promote 门:评分过线 + 审计一致(与已锁定主线资产无冲突)才提升;
    驳回必记原因(可回填失败注册表)。
  - 确定性可测;评分来源注入(如 sketch 闸门 / 人工 / VLM)。
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ASSET_KINDS: tuple[str, ...] = ("character", "prop", "scene", "voice", "stylepack")

#: 提升门:评分阈值 + 与主线冲突检查的确定性规则。
PROMOTE_FLOOR = 0.7


@dataclass
class PromotionCandidate:
    """池中一个候选。"""

    candidate_id: str
    kind: str
    name: str
    source: str  # freezone | pool | generated | uploaded
    score: float = 0.0
    score_note: str = ""
    payload: dict[str, Any] = field(default_factory=dict)  # 资产引用/路径/参数
    promoted: bool = False
    rejected_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "kind": self.kind,
            "name": self.name,
            "source": self.source,
            "score": self.score,
            "score_note": self.score_note,
            "payload": self.payload,
            "promoted": self.promoted,
            "rejected_reason": self.rejected_reason,
        }


@dataclass
class LockedAsset:
    """主线已锁定资产(提升的目的地,冲突检查用)。"""

    kind: str
    name: str
    asset_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


class PromotionPool:
    """候选池 + 提升/驳回台账 + 主线资产注册表。"""

    def __init__(
        self,
        candidates: list[PromotionCandidate] | None = None,
        locked: list[LockedAsset] | None = None,
    ) -> None:
        self._candidates: list[PromotionCandidate] = list(candidates or [])
        self._locked: list[LockedAsset] = list(locked or [])

    # ── 候选侧 ──
    def add_candidate(self, candidate: PromotionCandidate) -> None:
        if candidate.kind not in ASSET_KINDS:
            raise ValueError(f"unknown kind {candidate.kind!r}; expected one of {ASSET_KINDS}")
        self._candidates.append(candidate)

    @property
    def candidates(self) -> list[PromotionCandidate]:
        return list(self._candidates)

    def by_kind(self, kind: str) -> list[PromotionCandidate]:
        return [c for c in self._candidates if c.kind == kind]

    # ── 主线侧 ──
    def lock_asset(self, asset: LockedAsset) -> None:
        self._locked.append(asset)

    @property
    def locked(self) -> list[LockedAsset]:
        return list(self._locked)

    def _conflict(self, kind: str, name: str) -> LockedAsset | None:
        """同名同类型的主线资产 = 冲突(提升会重复/漂移)。"""
        for asset in self._locked:
            if asset.kind == kind and asset.name == name:
                return asset
        return None

    # ── 提升/驳回 ──
    def promote(
        self,
        candidate_id: str,
        *,
        score_floor: float = PROMOTE_FLOOR,
    ) -> tuple[LockedAsset | None, list[str]]:
        """提升候选为主线资产;返回 (锁定资产, 问题列表)。

        门:存在 → 未提升过 → 评分过线 → 无同名冲突。任一不过 → 返回 None + 问题。
        """
        cand = next((c for c in self._candidates if c.candidate_id == candidate_id), None)
        if cand is None:
            return None, ["candidate not found"]
        if cand.promoted:
            return None, ["already promoted"]
        issues: list[str] = []
        if cand.score < score_floor:
            issues.append(f"score {cand.score:.2f} < floor {score_floor}")
        conflict = self._conflict(cand.kind, cand.name)
        if conflict is not None:
            issues.append(f"conflict with locked {conflict.asset_id}({cand.kind}:{cand.name})")
        if issues:
            return None, issues
        asset = LockedAsset(
            kind=cand.kind, name=cand.name,
            asset_id=f"asset-{uuid.uuid4().hex[:10]}",
            metadata=dict(cand.payload),
        )
        self._locked.append(asset)
        cand.promoted = True
        return asset, []

    def reject(self, candidate_id: str, reason: str) -> bool:
        """驳回候选并记原因(原因可回填失败注册表)。"""
        cand = next((c for c in self._candidates if c.candidate_id == candidate_id), None)
        if cand is None:
            return False
        cand.rejected_reason = reason
        return True

    # ── 持久化 ──
    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "candidates": [c.to_dict() for c in self._candidates],
                    "locked": [
                        {
                            "kind": a.kind,
                            "name": a.name,
                            "asset_id": a.asset_id,
                            "metadata": a.metadata,
                        }
                        for a in self._locked
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> PromotionPool:
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text(encoding="utf-8"))
        return cls(
            candidates=[
                PromotionCandidate(
                    candidate_id=item["candidate_id"],
                    kind=item["kind"],
                    name=item["name"],
                    source=item["source"],
                    score=item["score"],
                    score_note=item.get("score_note", ""),
                    payload=dict(item.get("payload", {})),
                    promoted=item.get("promoted", False),
                    rejected_reason=item.get("rejected_reason", ""),
                )
                for item in raw.get("candidates", [])
            ],
            locked=[
                LockedAsset(
                    kind=item["kind"], name=item["name"],
                    asset_id=item["asset_id"], metadata=dict(item.get("metadata", {})),
                )
                for item in raw.get("locked", [])
            ],
        )


#: 评分器注入:kind → callable(payload) -> (score, note);用于图池/sketch 候选等。
Scorers = dict[str, Callable[[dict[str, Any]], tuple[float, str]]]


def score_and_promote_batch(
    pool: PromotionPool,
    *,
    scorers: Scorers,
    score_floor: float = PROMOTE_FLOOR,
) -> list[dict[str, Any]]:
    """批量:对未评分的候选评分 → 过线自动提升,不过线留池待审。

    Returns:
        [{"candidate_id", "kind", "name", "score", "promoted", "issues"}] 逐项结果。
    """
    results: list[dict[str, Any]] = []
    for cand in pool.candidates:
        if cand.score == 0.0 and cand.kind in scorers:
            cand.score, cand.score_note = scorers[cand.kind](cand.payload)
        asset, issues = pool.promote(cand.candidate_id, score_floor=score_floor)
        results.append(
            {
                "candidate_id": cand.candidate_id,
                "kind": cand.kind,
                "name": cand.name,
                "score": cand.score,
                "promoted": asset is not None,
                "issues": issues,
            }
        )
    return results
