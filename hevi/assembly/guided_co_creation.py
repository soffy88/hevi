"""引导式共创 —— 分级确认状态机(3O 内化 Phase C,来源 video-shotcraft guided-free-creation)。

shotcraft 的三模式 UX 里,共同创作模式每轮只问 1–3 个最能减少返工的问题,在
产品简报/需求决策/视觉方向/镜头映射/最终分镜处暂停等用户确认;用户说"你全权
决定"时切自主模式。这里是该交互的确定性状态机(可测):
  - 阶段推进:每阶段带确认问题列表,未确认 → 停在 checkpoint
  - 确认(checkpoint)后进入下一阶段
  - 任一阶段用户授权全权 → 跳自主模式(跳过剩余 checkpoint)

3O 归属(待上游): `omodul.guided_co_creation`(三件套签名)。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: 确认节点:阶段 → (1–3 个问题)。顺序即分镜确认流程。
CHECKPOINTS: dict[str, tuple[str, ...]] = {
    "product_brief": ("产品定位与目标受众?", "必须展示的功能?", "时长/画幅/语言约束?"),
    "requirements": ("关键需求决策有哪些?", "数据口径(公开/虚构/脱敏)?"),
    "visual_direction": ("视觉方向选哪个?", "参考片/参考图有吗?"),
    "shot_mapping": ("功能到镜头映射确认?", "指定镜头卡?"),
    "final_storyboard": ("最终分镜确认(镜头顺序/时长/字幕/转场/SFX)?",),
}


@dataclass
class CoCreationState:
    """共创状态:当前阶段 + 各阶段确认情况 + 模式。"""

    current_stage: str = "product_brief"
    confirmed: set[str] = field(default_factory=set)
    autonomous: bool = False  # 用户授权全权 → 自主模式

    def pending_questions(self) -> list[str]:
        """当前阶段待确认问题(1–3 个)。"""
        if self.autonomous or self.current_stage not in CHECKPOINTS:
            return []
        if self.current_stage in self.confirmed:
            return []
        return list(CHECKPOINTS[self.current_stage])

    def confirm(self, stage: str | None = None) -> str:
        """确认当前(或指定)阶段,推进到下一未确认阶段。"""
        stage = stage or self.current_stage
        self.confirmed.add(stage)
        for next_stage in CHECKPOINTS:
            if next_stage not in self.confirmed:
                self.current_stage = next_stage
                return next_stage
        return ""  # 全部分镜确认 → 进入制作

    def delegate(self) -> None:
        """用户授权全权:跳过剩余 checkpoint。"""
        self.autonomous = True

    @property
    def done(self) -> bool:
        return self.autonomous or all(s in self.confirmed for s in CHECKPOINTS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_stage": self.current_stage,
            "confirmed": sorted(self.confirmed),
            "autonomous": self.autonomous,
            "done": self.done,
        }


def next_questions(state: CoCreationState) -> list[str]:
    """给 UI/agent 的当前问题(空 = 无待确认)。"""
    return state.pending_questions()


async def guided_co_creation_workflow(
    config: CoCreationState,
    input_data: dict[str, Any],
    output_dir: Path,
    *,
    on_step: Any = None,
) -> dict[str, Any]:
    """三件套签名包装:推进到下一个 checkpoint,返回待确认问题。

    Args:
        config: 当前共创状态。
        input_data: {"confirm": bool, "delegate": bool, "stage": str|None}。
        output_dir: 状态落盘目录。

    Returns:
        {"status": "completed"|"failed", "questions": [...], "state": {...}}
    """
    _enabled_pillars = {"report", "cost", "decision_trail"}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        if input_data.get("delegate"):
            config.delegate()
        elif input_data.get("confirm"):
            config.confirm(stage=input_data.get("stage"))
        state_path = output_dir / "co_creation_state.json"
        state_path.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {
            "status": "completed",
            "questions": next_questions(config),
            "state": config.to_dict(),
            "report_path": str(state_path),
        }
    except Exception as e:
        logger.exception("guided_co_creation_workflow failed")
        return {"status": "failed", "error": str(e)}
