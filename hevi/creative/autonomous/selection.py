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

from dataclasses import dataclass
from enum import StrEnum

from hevi.production.shot_readiness import select_candidate


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


__all__ = [
    "CANDIDATE_SELECTION",
    "NON_AUTHORITATIVE",
    "PROVIDER_SELECTION",
    "SelectionAuthority",
    "SelectionPath",
    "assert_single_authority",
    "select",
]