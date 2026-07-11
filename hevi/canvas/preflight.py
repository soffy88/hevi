"""计划级自我批判(HEVI 路线图 Phase4 #44)。

canvas 图生成后不直接执行,先跑一轮纯推理批判:预算是否超、风格是否冲突、
镜头数是否撑得起目标时长。零生成成本(只读 node.config,不调用任何生成
API/LLM),拦"计划本身有问题"这类以前只能靠事后 verdict 发现、但那时钱已经
花出去的问题。与 L3 事后裁决前后呼应:计划前反思,生成后审判,中间才是真金白银。

只做预算超支这一项**硬性拦截**(执行前就能确定性算出来,不该让钱花出去才发现
超支)。风格冲突/时长偏离是**警告**,不阻断——canvas 是自由画布,用户可能故意
让不同镜头用不同风格,没有足够依据把这类情况当错误直接拦执行。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from oprim._hevi_types import CanvasNode


class PreflightError(Exception):
    """计划级批判发现硬性问题(目前只有预算超支),执行前打回。"""


@dataclass
class PreflightIssue:
    severity: str  # "error" | "warning"
    message: str


@dataclass
class PreflightReport:
    passed: bool
    issues: list[PreflightIssue] = field(default_factory=list)
    estimated_cost_usd: float = 0.0


def _video_nodes(nodes: list[CanvasNode]) -> list[CanvasNode]:
    return [n for n in nodes if n.node_type == "video"]


def estimate_graph_cost(nodes: list[CanvasNode]) -> float:
    """按每个 video 节点的 provider + duration_s 估算全图总成本。

    复用 pricing_table(不重新维护一份价格),只处理 per_second/per_minute 两种
    既有单位;未知 provider(拼错/尚未收录)按 0 算而不是报错——预算检查的目的是
    拦"确定超支",不该因为一个节点 provider 认不出就让整个批判失败。
    """
    from hevi.cost.pricing_table import get_pricing_table

    pricing = get_pricing_table()
    total = 0.0
    for n in _video_nodes(nodes):
        cfg = n.config or {}
        provider = cfg.get("provider", "wan_local")
        duration_s = float(cfg.get("duration_s", 5.0))
        entry = pricing.get(provider)
        if not entry:
            continue
        price = float(entry.get("price_usd", 0.0))
        if entry.get("unit") == "per_minute":
            total += price * (duration_s / 60.0)
        else:  # per_second(canvas video 节点没有 per_1k_tokens 这类)
            total += price * duration_s
    return total


def check_style_conflicts(nodes: list[CanvasNode]) -> list[str]:
    """video 节点间显式设置的 style/color_grade 互相矛盾 → 警告(不阻断)。

    只看节点 config 里**显式设置**的值,没设(用默认/继承)的节点不参与比较——
    "有些镜头没显式设风格"不构成冲突,"设了但设的不一样"才算。
    """
    styles = {v for n in _video_nodes(nodes) if (v := (n.config or {}).get("style"))}
    color_grades = {v for n in _video_nodes(nodes) if (v := (n.config or {}).get("color_grade"))}
    issues: list[str] = []
    if len(styles) > 1:
        issues.append(f"video 节点间 style 设置不一致: {sorted(styles)}")
    if len(color_grades) > 1:
        issues.append(f"video 节点间 color_grade 设置不一致: {sorted(color_grades)}")
    return issues


def check_duration_budget(nodes: list[CanvasNode], *, target_duration_s: float | None) -> list[str]:
    """镜头总时长跟目标时长偏离过大(< 一半 或 > 两倍)→ 警告。

    没给 target_duration_s(调用方不关心/未知)→ 跳过,不臆造一个目标。
    """
    if target_duration_s is None or target_duration_s <= 0:
        return []
    vids = _video_nodes(nodes)
    if not vids:
        return ["没有 video 节点,无法产出成片"]
    total = sum(float((n.config or {}).get("duration_s", 5.0)) for n in vids)
    if total <= 0:
        return []
    ratio = total / target_duration_s
    if ratio < 0.5 or ratio > 2.0:
        return [
            f"镜头总时长 {total:.0f}s 与目标时长 {target_duration_s:.0f}s 偏离过大"
            f"(比例 {ratio:.2f})"
        ]
    return []


def run_preflight(
    nodes: list[CanvasNode],
    *,
    budget_usd: float | None = None,
    target_duration_s: float | None = None,
) -> PreflightReport:
    """跑完整批判,返回报告(不抛异常——`passed=False` 只表示有硬性问题,由调用方
    决定要不要拦执行;`execute_graph_with_preflight` 才会真的拦)。
    """
    issues: list[PreflightIssue] = []
    cost = estimate_graph_cost(nodes)
    if budget_usd is not None and cost > budget_usd:
        issues.append(PreflightIssue("error", f"预计成本 ${cost:.2f} 超出预算 ${budget_usd:.2f}"))
    issues.extend(PreflightIssue("warning", m) for m in check_style_conflicts(nodes))
    issues.extend(
        PreflightIssue("warning", m)
        for m in check_duration_budget(nodes, target_duration_s=target_duration_s)
    )
    passed = not any(i.severity == "error" for i in issues)
    return PreflightReport(passed=passed, issues=issues, estimated_cost_usd=cost)
