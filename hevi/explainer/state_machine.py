"""Explainer State Machine & Voice Approval Gate.

状态机:
  script → voice_approved → plan → render

硬规则（WEVIDEO_TASK.md §2）:
1. 配音确认闸：未确认（voice_approved != True）严禁进入 plan 和 render 阶段；
2. 回退机制：可随时从任一步回退修改；
3. 增量重算：脚本发生局部修改时，仅重算受影响的分段音频和对齐，复用未修改分段缓存。
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hevi.explainer.script import OralScript, compute_script_diff, edit_section
from hevi.explainer.voice import (
    DEFAULT_ZH_VOICE,
    VoiceoverPackage,
    build_voiceover_package,
)

logger = logging.getLogger(__name__)


class PipelineState(str, enum.Enum):
    SCRIPT = "script"
    VOICE_APPROVED = "voice_approved"
    PLAN = "plan"
    RENDER = "render"


class StateTransitionError(RuntimeError):
    """状态机非法流转异常。"""


class ApprovalRequiredError(RuntimeError):
    """未通过配音确认闸拦截异常。"""


@dataclass
class ExplainerProject:
    project_id: str
    script: OralScript
    state: PipelineState = PipelineState.SCRIPT
    voice_approved: bool = False
    voice_id: str = DEFAULT_ZH_VOICE
    speed: float = 1.0
    voiceover_package: VoiceoverPackage | None = None
    visual_plan_data: dict[str, Any] | None = None
    render_result_data: dict[str, Any] | None = None
    state_history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.state_history:
            self._record_history("init", f"Project initialized at state {self.state.value}")

    def _record_history(self, action: str, detail: str) -> None:
        self.state_history.append(
            {
                "state": self.state.value,
                "voice_approved": self.voice_approved,
                "action": action,
                "detail": detail,
            }
        )

    def synthesize_voice(self, out_dir: Path | str, voice_id: str | None = None, speed: float | None = None) -> VoiceoverPackage:
        """合成/更新配音包（支持增量重算）。"""
        if voice_id is not None:
            self.voice_id = voice_id
        if speed is not None:
            self.speed = speed

        pkg = build_voiceover_package(
            script=self.script,
            out_dir=Path(out_dir),
            voice=self.voice_id,
            speed=self.speed,
            cached_package=self.voiceover_package,
        )
        self.voiceover_package = pkg
        self._record_history("synthesize_voice", f"Voice synthesized with voice={self.voice_id}")
        return pkg

    def approve_voice(self) -> None:
        """配音确认闸：审核批准配音，解锁进入 plan 阶段。"""
        if self.voiceover_package is None:
            raise StateTransitionError("Cannot approve voice: voiceover has not been synthesized yet.")

        self.voice_approved = True
        self.state = PipelineState.VOICE_APPROVED
        self._record_history("approve_voice", "Voice approved by user/gate.")

    def advance_to_plan(self, plan_data: dict[str, Any]) -> None:
        """推进至视觉规划阶段（受配音确认闸门禁约束）。"""
        if not self.voice_approved or self.state not in (
            PipelineState.VOICE_APPROVED,
            PipelineState.PLAN,
            PipelineState.RENDER,
        ):
            raise ApprovalRequiredError(
                f"Cannot advance to 'plan': voice has not been approved! (current state={self.state.value}, voice_approved={self.voice_approved})"
            )

        self.visual_plan_data = plan_data
        self.state = PipelineState.PLAN
        self._record_history("advance_to_plan", "Visual plan registered.")

    def advance_to_render(self, render_data: dict[str, Any]) -> None:
        """推进至渲染完成阶段（必须先有 approved 状态和 visual plan）。"""
        if not self.voice_approved:
            raise ApprovalRequiredError("Cannot render: voice has not been approved!")
        if self.visual_plan_data is None:
            raise StateTransitionError("Cannot render: visual plan has not been generated!")

        self.render_result_data = render_data
        self.state = PipelineState.RENDER
        self._record_history("advance_to_render", "Render completed.")

    def rollback_to(self, target_state: PipelineState | str) -> None:
        """回退至指定上游状态并撤销下游确认。"""
        target = PipelineState(target_state)

        if target == PipelineState.SCRIPT:
            self.state = PipelineState.SCRIPT
            self.voice_approved = False
            self.visual_plan_data = None
            self.render_result_data = None
            self._record_history("rollback_to_script", "Rolled back to script; voice approval revoked.")
        elif target == PipelineState.VOICE_APPROVED:
            if not self.voiceover_package:
                raise StateTransitionError("Cannot rollback to voice_approved: no voiceover exists.")
            self.state = PipelineState.VOICE_APPROVED
            self.voice_approved = True
            self.visual_plan_data = None
            self.render_result_data = None
            self._record_history("rollback_to_voice_approved", "Rolled back to voice_approved; downstream plans cleared.")
        elif target == PipelineState.PLAN:
            if not self.voice_approved or not self.visual_plan_data:
                raise StateTransitionError("Cannot rollback to plan: visual plan does not exist or voice unapproved.")
            self.state = PipelineState.PLAN
            self.render_result_data = None
            self._record_history("rollback_to_plan", "Rolled back to plan; render result cleared.")
        else:
            raise StateTransitionError(f"Unsupported rollback target: {target}")

    def update_script_section(
        self,
        section_index: int,
        out_dir: Path | str,
        *,
        new_oral_text: str | None = None,
        new_key_terms: list[str] | None = None,
        new_visual_intent: str | None = None,
    ) -> dict[str, Any]:
        """修改文稿某段：触发增量对比、版本递增、重置确认闸，仅重算脏段。"""
        old_script = self.script
        new_script = edit_section(
            old_script,
            section_index,
            new_oral_text=new_oral_text,
            new_key_terms=new_key_terms,
            new_visual_intent=new_visual_intent,
        )
        diff = compute_script_diff(old_script, new_script)
        self.script = new_script

        # 修改剧本后，自动回退到 SCRIPT 状态并撤销配音确认
        self.rollback_to(PipelineState.SCRIPT)

        # 仅对脏段进行增量重算
        if self.voiceover_package is not None:
            self.synthesize_voice(out_dir=out_dir)

        return diff

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "state": self.state.value,
            "voice_approved": self.voice_approved,
            "voice_id": self.voice_id,
            "speed": self.speed,
            "script": self.script.to_dict(),
            "voiceover": self.voiceover_package.to_dict() if self.voiceover_package else None,
            "has_visual_plan": self.visual_plan_data is not None,
            "has_render_result": self.render_result_data is not None,
            "state_history": self.state_history,
        }
