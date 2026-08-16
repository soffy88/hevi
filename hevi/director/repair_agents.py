"""修复 agent 编排 —— 失败 → 诊断 → 定向修复(3O 内化 Round 3e,来源 dramaclaw agents/)。

dramaclaw 的修复 agent 家族(character_fixer / episode_fixer / content_rewriter /
global_video_optimizer / episode_optimizer / identity_planner)把"返工"从单点重试
升级为**agent 化修复编排**:按失败类别选修复 agent → 一次只改一个变量 → 尝试预算 →
收敛判定。hevi 此前只有 verdict 的返工钩子(五档),没有 agent 化编排。

本模块为 hevi 暂驻(待上游 `oskill.repair_agents`):确定性修复计划 —— 失败诊断 →
修复 agent 选择 → 修复动作(拉哪根杠杆)→ 尝试预算 → 收敛/发散判定(复用
verdict.convergence)。模型调用点留注入(修复动作的 prompt 富化由 hevi prompt 层做)。

3O 归属(待上游): `oskill.repair_agents`。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.verdict.convergence import ConvergenceLog, trend

logger = logging.getLogger(__name__)

#: 修复 agent 表:诊断类别 → (agent 名, 拉哪根杠杆, 动作模板)。
REPAIR_AGENTS: dict[str, tuple[str, str, str]] = {
    "参考图角色错配": (
        "character_fixer",
        "参考图/身份锚",
        "重选/重生成参考图,保持其余字段不变(一次只改这一个变量)",
    ),
    "光照": (
        "episode_fixer",
        "prompt_lighting",
        "按诊断类别调整光照描述,不动运镜/动作字段",
    ),
    "动作": (
        "episode_fixer",
        "action_beats",
        "拆/并动作拍点至一镜一动,或降运动期望保画质(Conservation Law)",
    ),
    "运镜": (
        "global_video_optimizer",
        "prompt_camera",
        "换机位语言/节奏预设,不动内容字段",
    ),
    "时长": (
        "episode_optimizer",
        "duration",
        "调整镜头时长/节拍,不重写内容",
    ),
    "音频": (
        "content_rewriter",
        "voice/对白",
        "改对白/配音参数,不动画面字段",
    ),
    "构图": (
        "global_video_optimizer",
        "构图/裁切",
        "fix-in-post 优先:裁切/重构图,不动生成参数",
    ),
    "安全词误触发": (
        "content_rewriter",
        "措辞",
        "改写触发词,保持语义不变",
    ),
}


@dataclass
class RepairAction:
    """一次定向修复动作。"""

    agent: str
    diagnosis: str
    lever: str
    instruction: str
    shot_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "diagnosis": self.diagnosis,
            "lever": self.lever,
            "instruction": self.instruction,
            "shot_id": self.shot_id,
        }


@dataclass
class RepairPlan:
    """一批失败的修复计划。"""

    actions: list[RepairAction] = field(default_factory=list)
    budget_used: int = 0
    budget_limit: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "actions": [a.to_dict() for a in self.actions],
            "budget_used": self.budget_used,
            "budget_limit": self.budget_limit,
        }


def plan_repair(
    failures: list[dict[str, Any]],
    *,
    budget_limit: int = 3,
) -> RepairPlan:
    """确定性:失败清单(含 diagnosis 分类)→ 按 agent 表出修复动作。

    Rules:
      - 一次只改一个变量:每个失败只拉一个杠杆(agent 表映射)。
      - 尝试预算:action 数 ≤ budget_limit;超限 → 不再出动作(降级交付信号)。
      - 未知诊断 → 一律走 content_rewriter 且注明"需先诊断根因"(retake 纪律)。
    """
    plan = RepairPlan(budget_limit=budget_limit)
    for failure in failures[:budget_limit]:
        diagnosis = failure.get("diagnosis", "") or "未知"
        shot_id = failure.get("shot_id", "")
        entry = REPAIR_AGENTS.get(diagnosis)
        if entry is None:
            plan.actions.append(
                RepairAction(
                    agent="content_rewriter",
                    diagnosis=diagnosis,
                    lever="prompt(待诊断)",
                    instruction="诊断分类未知:先定根因,再拉杠杆(一次一个变量)",
                    shot_id=shot_id,
                )
            )
        else:
            agent, lever, instruction = entry
            plan.actions.append(
                RepairAction(
                    agent=agent, diagnosis=diagnosis, lever=lever,
                    instruction=instruction, shot_id=shot_id,
                )
            )
        plan.budget_used += 1
    return plan


def repair_decision(
    plan: RepairPlan,
    convergence: ConvergenceLog,
    *,
    episode_num: int = 1,
    phase: str = "rework",
) -> dict[str, Any]:
    """修复后的决策:本轮修复是否收敛/发散/达标(复用 convergence.trend)。

    Returns:
        {"status", "actions", "budget_exhausted", "suggestion"}。
        budget 用尽且仍发散 → suggestion 指向降级交付 + 部分退款(retake 纪律)。
    """
    t = trend(convergence, episode_num=episode_num, phase=phase)
    budget_exhausted = plan.budget_used >= plan.budget_limit
    result: dict[str, Any] = {
        "status": t.get("status"),
        "actions": [a.to_dict() for a in plan.actions],
        "budget_exhausted": budget_exhausted,
        "suggestion": t.get("suggestion", ""),
    }
    if budget_exhausted and t.get("status") in ("diverging", "oscillating"):
        result["suggestion"] = (
            "尝试预算用尽且未收敛:走降级交付 + 部分退款;停止重掷(一次一个变量纪律)"
        )
    return result


def save_repair_plan(plan: RepairPlan, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def hints_from_failures(
    shot_records: list[dict[str, Any]],
    shot_ids: list[int],
    *,
    budget_limit: int = 3,
) -> dict[int, str]:
    """从镜头记录(含 selection_json.diagnosis_category)推导返工 hints。

    运行时接线:regenerate 未显式给 hints 时,按 verdict 诊断分类自动生成
    {shot_index: 修复指令}(一次一变量纪律),交给 omodul regenerate_shots 并入 prompt。
    无诊断的镜头 → 回退通用指令(不阻断重掷)。
    """
    failures: list[dict[str, Any]] = []
    for record in shot_records:
        idx = record.get("shot_index")
        if idx not in shot_ids:
            continue
        sel = record.get("selection_json") or {}
        diagnosis = sel.get("diagnosis_category") or sel.get("diagnosis") or ""
        failures.append({"shot_id": f"s{idx}", "diagnosis": diagnosis})
    plan = plan_repair(failures, budget_limit=budget_limit)
    hints: dict[int, str] = {}
    for action in plan.actions:
        try:
            idx = int(action.shot_id.lstrip("s"))
        except ValueError:
            continue
        hints[idx] = action.instruction
    return hints
