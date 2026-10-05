"""SelectionAuthority —— 声明**哪个** selection path 是 canonical 的。

S3 验收目标(裁决原文):「证明 HEVI 已经只有一个真正的 asset selection authority,
并且 autonomous path 能无歧义地调用它。」

因此本模块**只做声明与路由**,不实现打分、不实现排序:
- 生产在用的候选选择路径 = `shot_readiness.select_candidate`;
- `provider_policy` 排的是 **provider**(不同对象,不是第二个候选选择器);
- `p1_pipeline` 的 max-overall 是**未使用**的本地选择(无生产调用方)。

任何新增 selection 实现都会让 `assert_single_authority()` 失败。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from hevi.creative.autonomous.identity import RequirementBindingSet
from hevi.production.shot_readiness import (
    NO_APPLICABLE_SCORER,
    AssetCandidate,
    AssetCandidateState,
    ScorerLike,
    ShotPreparation,
    needs_human_review,
    score_candidates,
    select_candidate,
)


class SelectionPath(StrEnum):
    CANDIDATE = "candidate"      # canonical:选候选
    PROVIDER = "provider"        # 不同对象:选 provider(provider_policy 拥有)
    UNUSED_LOCAL = "unused_local"  # p1_pipeline 内 max-overall,无生产调用方


@dataclass(frozen=True)
class SelectionAuthority:
    """选择权威的声明。`candidate` 有且仅有一个。"""
    path: SelectionPath
    implementation: str
    selects: str  # "candidate" | "provider" —— 声明排的是哪个对象
    in_production_use: bool
    authority_note: str = ""


#: 全仓唯一的候选级 selection authority
CANDIDATE_SELECTION: SelectionAuthority = SelectionAuthority(
    path=SelectionPath.CANDIDATE,
    implementation="hevi.production.shot_readiness.select_candidate",
    selects="candidate", in_production_use=True,
    authority_note="唯一候选选择入口;要求 verified + confidence>=0.75 + scored_by 有来源")

#: provider 级:排的是 provider,不是候选(不同职责,不构成第二选择器)
PROVIDER_SELECTION: SelectionAuthority = SelectionAuthority(
    path=SelectionPath.PROVIDER,
    implementation="hevi.provider_policy.policy.evaluate_provider_policy",
    selects="provider", in_production_use=True,
    authority_note="选 provider;其输出被 p7 AssetDecisionAuthority 消费,不选素材候选")

#: 记录在案的非权威路径(防止有人误当 canonical)
NON_AUTHORITATIVE: tuple[SelectionAuthority, ...] = (
    SelectionAuthority(SelectionPath.UNUSED_LOCAL,
                       "hevi.production.p1_pipeline.calculate_asset_fitness + max-overall",
                       "candidate", False,
                       "题材硬编码且无生产调用方;不得被当作 canonical selection"),
)


def assert_single_authority() -> None:
    """确认候选级 authority 唯一。任何新增实现都必须在此登记为非权威。"""
    candidates = [a for a in (CANDIDATE_SELECTION, *NON_AUTHORITATIVE)
                  if a.selects == "candidate" and a.in_production_use]
    if len(candidates) != 1:
        raise AssertionError(f"MULTIPLE_CANDIDATE_AUTHORITIES:{[a.implementation for a in candidates]}")


def select(*args: object, **kwargs: object) -> object:
    """薄转发:autonomous path 只经此调用 canonical selection,不自行实现。"""
    assert_single_authority()
    return select_candidate(*args, **kwargs)  # type: ignore[arg-type]


class GenerationNotAdmitted(StrEnum):
    """generation admission 的拒绝理由。任一成立即禁止自动生成。"""

    NO_RESOLUTION = "NO_RESOLUTION"
    NO_SELECTED_CANDIDATE = "NO_SELECTED_CANDIDATE"
    UNRESOLVED = "UNRESOLVED"
    UNBOUND = "UNBOUND"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class GenerationNotAdmittedError(RuntimeError):
    """generation 被拒绝。携带机器可读理由,不携带资产引用。"""

    def __init__(self, reason: GenerationNotAdmitted, detail: str = "") -> None:
        super().__init__(f"{reason.value}:{detail}" if detail else reason.value)
        self.reason = reason


def resolve(
    preparation: ShotPreparation,
    *,
    domain: str,
    scorer_registry: Mapping[str, ScorerLike],
    bindings: RequirementBindingSet,
    required_requirement_ids: tuple[str, ...] = (),
) -> ShotResolution:
    """生产接线:候选 → canonical scorer → canonical selector → 结论。

    这是「先选、再判能否生成」的**唯一**入口。顺序不可颠倒:
    没有 SELECTED 候选就没有决议;没有决议就不允许进入生成。

    Args:
        domain: 选择所处适用域;域外 scorer 不可用(返回 NO_APPLICABLE_SCORER 决议)。
        scorer_registry: canonical scorer 注册表,由领域声明,不在本模块实现。
        bindings: shot-local asset ref → canonical requirement 的显式映射。
            local ref 只能经它查,不得直接与 requirement_id 比较(两者语义空间不同)。
        required_requirement_ids: 本镜**要求**的 canonical requirement id。

            默认空 = 现有语义(requirement 集合从候选推导)。但那样一来,一个
            完全没有候选的 requirement 只会安静缺席,不会出现在
            `unresolved_requirement_ids` —— 而 unresolved 正是 P2 acquisition
            fallback chain 的输入。生产层自行补这个集合就等于重建第二套
            resolution 语义,所以由本函数显式接受,让既有 authority 说真话。
            这不是新增 authority:`select_candidate` 仍是唯一选择实现。
    """
    assert_single_authority()
    all_required = tuple(sorted(
        set(required_requirement_ids) | {c.requirement_id for c in preparation.candidates}))
    scored_status, _ = score_candidates(
        list(preparation.candidates), domain=domain, registry=dict(scorer_registry))
    if scored_status == NO_APPLICABLE_SCORER:
        return ShotResolution(
            shot_id=preparation.shot_id,
            selected_requirement_ids=(),
            unresolved_requirement_ids=all_required,
            unbound_asset_refs=tuple(sorted(set(preparation.required_asset_refs))),
            human_review_required=True,
        )
    requirement_ids = sorted({c.requirement_id for c in preparation.candidates})
    selected: dict[str, AssetCandidate | None] = {}
    for requirement_id in requirement_ids:
        selected[requirement_id] = select_candidate(preparation, requirement_id)
    required_refs = tuple(preparation.required_asset_refs)
    unbound = bindings.unbound_local_refs(required_refs) + tuple(
        ref for ref in required_refs
        if not any(c.asset_ref == ref for c in preparation.candidates))
    # 零候选的 required requirement:没有 SELECTED,所以未解决。不静默缺席。
    unresolved = [rid for rid in all_required
                  if rid not in set(requirement_ids) or selected.get(rid) is None]
    return ShotResolution(
        preparation.shot_id,
        tuple(k for k, v in selected.items() if v is not None),
        tuple(unresolved),
        tuple(sorted(set(unbound))),
        needs_human_review(preparation),
    )


@dataclass(frozen=True)
class ShotResolution:
    """一镜的候选选择结论。任一 blocker 成立即不得进入生成。"""

    shot_id: str
    selected_requirement_ids: tuple[str, ...]
    unresolved_requirement_ids: tuple[str, ...]
    unbound_asset_refs: tuple[str, ...]
    human_review_required: bool

    @property
    def ready_for_generation(self) -> bool:
        """四条 blocker 全部不成立才允许自动生成。

        selected 为空、unresolved 非空、unbound 非空、需人工复核 —— 任一成立即 False。
        """
        return (
            bool(self.selected_requirement_ids)
            and not self.unresolved_requirement_ids
            and not self.unbound_asset_refs
            and not self.human_review_required
        )

    @property
    def blockers(self) -> tuple[GenerationNotAdmitted, ...]:
        """列出**全部**阻断理由(不只第一个),便于 report 与人工排障。"""
        reasons: list[GenerationNotAdmitted] = []
        if not self.selected_requirement_ids:
            reasons.append(GenerationNotAdmitted.NO_SELECTED_CANDIDATE)
        if self.unresolved_requirement_ids:
            reasons.append(GenerationNotAdmitted.UNRESOLVED)
        if self.unbound_asset_refs:
            reasons.append(GenerationNotAdmitted.UNBOUND)
        if self.human_review_required:
            reasons.append(GenerationNotAdmitted.HUMAN_REVIEW)
        return tuple(reasons)


def admit_generation(
    resolution: ShotResolution | None,
    candidates: Sequence[AssetCandidate],
) -> AssetCandidate:
    """generation admission seam:唯一允许「开始生成」的判定点。

    generation executor 必须经此函数拿资产,不得自行比较候选或自行评估
    ready_for_generation。返回唯一 SELECTED 候选;不满足条件则抛
    `GenerationNotAdmittedError`,不产出任何资产引用。
    """
    if resolution is None:
        raise GenerationNotAdmittedError(
            GenerationNotAdmitted.NO_RESOLUTION, "<missing ShotResolution>")
    if not resolution.ready_for_generation:
        raise GenerationNotAdmittedError(
            resolution.blockers[0],
            f"shot={resolution.shot_id} "
            f"unresolved={resolution.unresolved_requirement_ids} "
            f"unbound={resolution.unbound_asset_refs} "
            f"human_review={resolution.human_review_required}")
    selected = [c for c in candidates
                if c.requirement_id in resolution.selected_requirement_ids
                and c.state is AssetCandidateState.SELECTED]
    if len(selected) != 1:
        raise GenerationNotAdmittedError(
            GenerationNotAdmitted.NO_SELECTED_CANDIDATE,
            f"shot={resolution.shot_id} selected_count={len(selected)}")
    return selected[0]


__all__ = [
    "CANDIDATE_SELECTION",
    "NON_AUTHORITATIVE",
    "PROVIDER_SELECTION",
    "GenerationNotAdmitted",
    "GenerationNotAdmittedError",
    "SelectionAuthority",
    "SelectionPath",
    "ShotResolution",
    "admit_generation",
    "assert_single_authority",
    "resolve",
    "select",
]