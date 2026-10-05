"""RequirementBinding —— 纯身份映射 adapter(不评分、不排序、不选、不覆盖)。

裁决(2026-10-03):
    canonical requirement identity = `p7.AssetRequirement.requirement_id`。
    `shot_readiness` 保留自己的语义字段,但**必须**经显式映射到 p7 identity,
    **禁止**直接比较两个不同 namespace。

为什么必须显式:`shot_readiness.py:202` 曾把 `requirement_id` 与
`required_asset_refs`(**asset_ref 列表**)直接比较。那不是类型报错 ——
两边都是 str,比较能跑,结果是「静默的假/真」。与 S2 的两个陷阱同类。

本模块只做一件事:local ref ↔ canonical p7 id 的双向映射与校验。
"""

from __future__ import annotations

from dataclasses import dataclass

from hevi.production.p7.asset_requirement import AssetRequirement


class RequirementIdentityError(ValueError):
    code: str = "REQUIREMENT_IDENTITY_MISMATCH"


@dataclass(frozen=True)
class RequirementBinding:
    """一条 local identity 到 canonical p7 requirement 的绑定。

    `local_ref` 是 shot_readiness 侧的资产引用(如 "ev.png");
    `requirement_id` 是 canonical p7 identity(如 "VIDEO/SCENE")。
    **两者不是同一个 namespace**,必须经本类显式连接。
    """

    local_ref: str
    requirement: AssetRequirement

    @property
    def requirement_id(self) -> str:
        return self.requirement.requirement_id

    def validate(self) -> None:
        if not self.local_ref:
            raise RequirementIdentityError("BINDING_WITHOUT_LOCAL_REF")
        if not self.requirement.requirement_id:
            raise RequirementIdentityError("BINDING_WITHOUT_REQUIREMENT_ID")

    def covers(self, candidate_requirement_id: str) -> bool:
        """该绑定是否覆盖此 canonical id。

        刻意**不接受** local_ref 作为 candidate 侧输入 —— 那正是静默误判的来源。
        """
        self.validate()
        return candidate_requirement_id == self.requirement.requirement_id


class RequirementBindingSet:
    """一批绑定。查找只认 canonical id。"""

    def __init__(self, bindings: tuple[RequirementBinding, ...] = ()) -> None:
        for binding in bindings:
            binding.validate()
        self._bindings = bindings

    def __len__(self) -> int:
        return len(self._bindings)

    @property
    def local_refs(self) -> tuple[str, ...]:
        return tuple(b.local_ref for b in self._bindings)

    @property
    def requirement_ids(self) -> tuple[str, ...]:
        return tuple(b.requirement_id for b in self._bindings)

    def for_requirement(self, requirement_id: str) -> RequirementBinding | None:
        for binding in self._bindings:
            if binding.covers(requirement_id):
                return binding
        return None

    def for_local_ref(self, local_ref: str) -> RequirementBinding | None:
        """local ref → canonical id 的**唯一**合法方向(显式)。"""
        for binding in self._bindings:
            if binding.local_ref == local_ref:
                return binding
        return None

    def unbound_local_refs(self, local_refs: tuple[str, ...]) -> tuple[str, ...]:
        """没有任何 canonical 绑定的 local ref —— 必须显式暴露,不静默忽略。"""
        known = set(self.local_refs)
        return tuple(ref for ref in local_refs if ref not in known)


__all__ = [
    "RequirementBinding",
    "RequirementBindingSet",
    "RequirementIdentityError",
]