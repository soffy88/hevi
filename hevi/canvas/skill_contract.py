"""能力契约 —— 可编排节点的 capability 声明与校验(3O 内化 Round 3d,来源 dramaclaw freezone)。

dramaclaw Freezone 的 skill_registry 是 Workflow-as-MCP 契约的补强:每个可编排 skill
显式声明**能力集**(can_read_canvas / can_apply_canvas_patch …)+ **输入/输出规格**
(角色/基数/媒体类型),注册表据此校验"声明与用法一致"—— 防止 skill 越权或错配。

hevi/canvas 已有图执行(canvas_workflow_executor),缺这层能力契约(第一轮已标注)。
本模块为 hevi 暂驻(待上游 `obase.capability_contract`):纯数据模型 + 确定性校验。

3O 归属(待上游): `obase.capability_contract`(SkillCapabilities / 输入输出规格 / 注册表校验)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: 能力枚举(与 dramaclaw SkillCapabilities 对齐)。
CAPABILITIES: tuple[str, ...] = (
    "can_read_canvas",
    "can_read_project_state",
    "can_access_network",
    "can_propose_canvas_patch",
    "can_apply_canvas_patch",
)
#: skill 提供方 / 基数 / 媒体类型。
PROVIDERS: tuple[str, ...] = ("freezone_mainline", "agent", "tool", "workflow")
CARDINALITIES: tuple[str, ...] = ("single", "multi")
MEDIA_TYPES: tuple[str, ...] = ("image", "text", "json", "node_patch", "graph_patch")


@dataclass
class SkillCapabilities:
    """一个 skill 的能力集(全 False 默认 = 最小权限)。"""

    can_read_canvas: bool = False
    can_read_project_state: bool = False
    can_access_network: bool = False
    can_propose_canvas_patch: bool = False
    can_apply_canvas_patch: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {cap: bool(getattr(self, cap)) for cap in CAPABILITIES}


@dataclass(frozen=True)
class SkillInputSpec:
    """输入规格。"""

    role: str
    label: str
    required: bool = False
    cardinality: str = "single"
    accepts_node_types: tuple[str, ...] = ()
    accepts_media_kinds: tuple[str, ...] = ()
    has_field: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillOutputSpec:
    """输出规格。"""

    role: str
    label: str
    media_type: str  # image | text | json | node_patch | graph_patch
    node_type: str
    pushable: bool = True
    requires_apply: bool = False


@dataclass
class SkillDefinition:
    """一条可编排 skill 定义。"""

    skill_id: str
    provider: str
    capabilities: SkillCapabilities = field(default_factory=SkillCapabilities)
    inputs: list[SkillInputSpec] = field(default_factory=list)
    outputs: list[SkillOutputSpec] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "provider": self.provider,
            "capabilities": self.capabilities.to_dict(),
            "inputs": [
                {
                    "role": i.role,
                    "label": i.label,
                    "required": i.required,
                    "cardinality": i.cardinality,
                    "accepts_node_types": list(i.accepts_node_types),
                    "accepts_media_kinds": list(i.accepts_media_kinds),
                    "has_field": list(i.has_field),
                }
                for i in self.inputs
            ],
            "outputs": [
                {
                    "role": o.role,
                    "label": o.label,
                    "media_type": o.media_type,
                    "node_type": o.node_type,
                    "pushable": o.pushable,
                    "requires_apply": o.requires_apply,
                }
                for o in self.outputs
            ],
        }


def validate_skill_definition(skill: SkillDefinition) -> list[str]:
    """校验"声明与用法一致"(确定性规则):

    - provider / cardinality / media_type 必须在枚举内。
    - 能 apply canvas patch 必须能 propose(apply 是 propose 的超集)。
    - can_apply_canvas_patch 的 skill 输出必须带 node_patch/graph_patch 类型的输出
      (能改图就要声明图改产物)。
    - 要求读 canvas 的 skill 必须有至少一个输入。
    """
    issues: list[str] = []
    if skill.provider not in PROVIDERS:
        issues.append(f"unknown provider {skill.provider!r}")
    issues.extend(
        f"input {inp.role}: bad cardinality {inp.cardinality!r}"
        for inp in skill.inputs
        if inp.cardinality not in CARDINALITIES
    )
    issues.extend(
        f"output {out.role}: bad media_type {out.media_type!r}"
        for out in skill.outputs
        if out.media_type not in MEDIA_TYPES
    )
    if (
        skill.capabilities.can_apply_canvas_patch
        and not skill.capabilities.can_propose_canvas_patch
    ):
        issues.append(
            f"{skill.skill_id}: can_apply_canvas_patch 必须伴随 can_propose_canvas_patch"
        )
    patch_outputs = [
        o for o in skill.outputs if o.media_type in ("node_patch", "graph_patch")
    ]
    if skill.capabilities.can_apply_canvas_patch and not patch_outputs:
        issues.append(
            f"{skill.skill_id}: 声明可改画布但无 node_patch/graph_patch 输出"
        )
    if skill.capabilities.can_read_canvas and not skill.inputs:
        issues.append(f"{skill.skill_id}: 声明读画布但无输入规格")
    return issues


class SkillRegistry:
    """注册表:登记 + 校验 + 按能力查询。"""

    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}

    def register(self, skill: SkillDefinition) -> list[str]:
        """登记并校验;返回问题列表(空 = 登记成功)。"""
        issues = validate_skill_definition(skill)
        if not issues:
            self._skills[skill.skill_id] = skill
        return issues

    def get(self, skill_id: str) -> SkillDefinition | None:
        return self._skills.get(skill_id)

    def with_capability(self, capability: str) -> list[SkillDefinition]:
        """按能力查询(如"谁能改画布")。"""
        if capability not in CAPABILITIES:
            raise KeyError(f"unknown capability {capability!r}")
        return [
            s for s in self._skills.values() if getattr(s.capabilities, capability)
        ]
