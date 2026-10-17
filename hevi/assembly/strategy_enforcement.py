"""策略确认执行层（增强 require_strategy_confirmation）。

对标 video-use 的 strategy confirmation flow：
  - 确认流程追踪（pending → proposed → confirmed → executed）
  - 确认历史日志
  - 强制确认检查（在关键操作前自动调用）
  - 确认超时/跳过检测
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from hevi.assembly.edit_craft import EditCraftError, EditDecisionList

logger = logging.getLogger(__name__)


class ConfirmationStatus(str, Enum):
    PENDING = "pending"
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    EXECUTED = "executed"
    REJECTED = "rejected"
    SKIPPED = "skipped"


@dataclass
class StrategyProposal:
    """策略提案（在确认前展示给用户）。"""

    summary: str  # 策略摘要
    rationale: str  # 为什么选这个策略
    alternatives: list[str] = field(default_factory=list)  # 备选策略
    risks: list[str] = field(default_factory=list)  # 风险/注意事项
    proposed_at: str = ""

    def __post_init__(self):
        if not self.proposed_at:
            self.proposed_at = datetime.now(tz=None).isoformat(timespec="seconds")


@dataclass
class ConfirmationRecord:
    """确认记录。"""

    status: ConfirmationStatus = ConfirmationStatus.PENDING
    proposal: StrategyProposal | None = None
    confirmed_at: str = ""
    confirmed_by: str = ""  # "user" | "auto" | "timeout"
    rejection_reason: str = ""
    skip_warning: str = ""

    def confirm(self, by: str = "user") -> None:
        self.status = ConfirmationStatus.CONFIRMED
        self.confirmed_at = datetime.now(tz=None).isoformat(timespec="seconds")
        self.confirmed_by = by

    def reject(self, reason: str = "") -> None:
        self.status = ConfirmationStatus.REJECTED
        self.rejection_reason = reason

    def mark_executed(self) -> None:
        self.status = ConfirmationStatus.EXECUTED

    def skip(self, warning: str = "") -> None:
        self.status = ConfirmationStatus.SKIPPED
        self.skip_warning = warning
        logger.warning("strategy confirmation SKIPPED: %s", warning)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "proposal": {
                "summary": self.proposal.summary,
                "rationale": self.proposal.rationale,
                "alternatives": self.proposal.alternatives,
                "risks": self.proposal.risks,
            } if self.proposal else None,
            "confirmed_at": self.confirmed_at,
            "confirmed_by": self.confirmed_by,
            "rejection_reason": self.rejection_reason,
            "skip_warning": self.skip_warning,
        }


# ── 策略门控器 ────────────────────────────────────────────────────────


class StrategyGate:
    """策略确认门控器（在渲染管线中使用）。

    用法：
        gate = StrategyGate()
        gate.propose(StrategyProposal(summary="...", rationale="..."))
        # ... 展示给用户 ...
        gate.confirm(by="user")
        gate.enforce()  # 在 render_edl 前调用
        # ... 执行渲染 ...
        gate.mark_executed()
    """

    def __init__(self):
        self._record = ConfirmationRecord()
        self._history: list[ConfirmationRecord] = []

    @property
    def status(self) -> ConfirmationStatus:
        return self._record.status

    @property
    def is_confirmed(self) -> bool:
        return self._record.status in (
            ConfirmationStatus.CONFIRMED,
            ConfirmationStatus.EXECUTED,
        )

    def propose(self, proposal: StrategyProposal) -> None:
        """提出策略提案。"""
        self._record = ConfirmationRecord(
            status=ConfirmationStatus.PROPOSED,
            proposal=proposal,
        )
        logger.info("strategy proposed: %s", proposal.summary)

    def confirm(self, by: str = "user") -> None:
        """确认策略。"""
        if self._record.status == ConfirmationStatus.PENDING:
            raise EditCraftError("cannot confirm: no proposal made yet")
        self._record.confirm(by)
        logger.info("strategy confirmed by %s", by)

    def reject(self, reason: str = "") -> None:
        """拒绝策略。"""
        self._record.reject(reason)
        self._history.append(self._record)
        self._record = ConfirmationRecord()  # 重置为 pending
        logger.info("strategy rejected: %s", reason)

    def skip(self, warning: str = "") -> None:
        """跳过确认（不推荐，会记录警告）。"""
        self._record.skip(warning)

    def enforce(self, *, allow_skip: bool = False) -> None:
        """强制检查：未确认则拒绝执行。

        Args:
            allow_skip: 是否允许跳过（默认 False，严格模式）
        """
        if self._record.status == ConfirmationStatus.SKIPPED:
            if not allow_skip:
                raise EditCraftError(
                    f"策略确认被跳过但 allow_skip=False: {self._record.skip_warning}"
                )
            logger.warning("enforcing with skip: %s", self._record.skip_warning)
            return

        if not self.is_confirmed:
            raise EditCraftError(
                f"策略未确认 (status={self._record.status.value})："
                "禁止执行剪辑。请先 propose → confirm"
            )

    def mark_executed(self) -> None:
        """标记已执行。"""
        self._record.mark_executed()
        self._history.append(self._record)
        self._record = ConfirmationRecord()

    def get_record(self) -> ConfirmationRecord:
        """获取当前确认记录。"""
        return self._record

    def get_history(self) -> list[dict[str, Any]]:
        """获取确认历史。"""
        return [r.to_dict() for r in self._history]


# ── 便捷函数 ──────────────────────────────────────────────────────────


def check_edl_strategy(edl: EditDecisionList | dict, gate: StrategyGate | None = None) -> None:
    """检查 EDL 的策略确认状态（兼容旧 EDL + 新 StrategyGate）。

    优先使用 gate（如果有），否则回退到 EDL.strategy_confirmed。
    """
    if gate:
        gate.enforce()
        return

    # 回退：检查 EDL 自身的 strategy_confirmed 字段
    from hevi.assembly.edit_craft import require_strategy_confirmation
    require_strategy_confirmation(edl)
