"""视觉来源路由 —— 决定某镜头用「搜索现成图」还是「Archify 生成」。

选择器是纯函数(可单测): 输入镜头文案, 输出可解释的
:class:`VisualRoute`(source=search|archify, 原因, 建议的 archify type)。

规则(确定性, 不依赖 LLM —— 与 ARCHIFY_TASK.md §1 允许的
"没有时允许用确定性规则从镜头文案生成 IR" 一致):
  - 真实物体/场景/人物/产品/动作镜头 → search
  - 结构/解释性内容(架构、流程、时序、数据流、生命周期、
    学习路线、时间线等) → archify
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: 触发 archify 的关键词(出现任一即判定为结构性内容)。
ARCHIFY_TRIGGERS: tuple[str, ...] = (
    "架构", "结构", "流程", "时序", "顺序", "数据流", "生命周期",
    "路线图", "学习路线", "时间线", "阶段", "步骤", "调用链",
    "请求链", "链路", "状态机", "状态转换", "网关", "队列",
    "管线", "分层", "拓扑",
    "architecture", "workflow", "sequence", "dataflow",
    "lifecycle", "timeline", "roadmap", "pipeline",
)

#: 触发 search 的关键词(真实物体/场景/人物/产品)。
SEARCH_TRIGGERS: tuple[str, ...] = (
    "真实", "实物", "物体", "场景", "人物", "产品", "实拍",
    "风景", "城市", "办公室", "工厂", "实验室", "服务器",
    "机房", "屏幕", "手机", "电脑", "人像", "操作", "演示",
    "特写", "产品图", "b-roll", "broll", "实拍镜头",
)

#: archify type 与触发词的映射(用于推荐 type)。
#: 注意顺序: lifecycle 优先于 architecture, 避免 "部署生命周期" 被误判为 architecture。
ARCHIFY_TYPE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "lifecycle",
        ("生命周期", "状态机", "状态转换", "重试", "回滚", "变迁"),
    ),
    (
        "architecture",
        ("架构", "结构", "组件", "服务", "拓扑", "分层", "部署", "系统"),
    ),
    (
        "workflow",
        ("流程", "步骤", "审批", "runbook", "流水线", "管线", "阶段", "过程"),
    ),
    (
        "sequence",
        ("时序", "顺序", "调用链", "请求链", "链路", "消息", "往返", "请求"),
    ),
    (
        "dataflow",
        ("数据流", "数据管线", "etl", "血缘", "传输", "流向", "流转"),
    ),
    ("timeline", ("时间线", "路线图", "学习路线", "里程碑", "roadmap", "timeline")),
)


@dataclass(frozen=True)
class VisualRoute:
    """单个镜头的视觉来源决策。"""

    source: str  # "search" | "archify"
    reason: str  # 可解释原因
    archify_type: str = ""  # 推荐的 archify type(source=archify 时)
    keywords: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "reason": self.reason,
            "archify_type": self.archify_type,
            "keywords": self.keywords,
        }


def route_visual(text: str, *, aspect: str = "9:16") -> VisualRoute:
    """根据镜头文案决定视觉来源。

    优先级: archify 触发词 > search 触发词 > 默认 search(真实物体)。
    """
    lowered = (text or "").lower()
    archify_hits = [w for w in ARCHIFY_TRIGGERS if w in lowered]
    if archify_hits:
        archify_type = _suggest_archify_type(lowered)
        return VisualRoute(
            source="archify",
            reason=(
                "文案含结构性/解释性关键词("
                + "、".join(archify_hits[:3])
                + "), 适合用 Archify 生成结构化图示"
            ),
            archify_type=archify_type,
            keywords=tuple(archify_hits),
        )
    search_hits = [w for w in SEARCH_TRIGGERS if w in lowered]
    if search_hits:
        return VisualRoute(
            source="search",
            reason=(
                "文案描述真实物体/场景(" + "、".join(search_hits[:3])
                + "), 适合检索现有素材"
            ),
            keywords=tuple(search_hits),
        )
    return VisualRoute(
        source="search",
        reason="未命中结构性关键词, 默认按真实物体镜头检索素材",
        keywords=(),
    )


def _suggest_archify_type(lowered: str) -> str:
    for archify_type, hints in ARCHIFY_TYPE_HINTS:
        if any(h in lowered for h in hints):
            return archify_type
    return "workflow"
