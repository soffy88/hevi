"""Bounded repair decisions with convergence and divergence detection."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .evaluation import QualityEvaluation, QualityEvidence
from .evidence import EvaluationEvidence
from .taxonomy import FailureCode, normalize_failure


class RepairBudget(BaseModel):
    max_attempts: int = Field(default=1, ge=0)
    max_cost_usd: float = Field(default=0.0, ge=0.0)
    min_marginal_gain: float = Field(default=0.05, ge=0.0)
    max_new_failure_rate: float = Field(default=0.5, ge=0.0, le=1.0)
    low_gain_rounds_to_stop: int = Field(default=2, ge=1)


class RepairAction(BaseModel):
    kind: Literal[
        "regenerate_same_provider",
        "retry_new_seed",
        "recompile_prompt",
        "replace_reference",
        "switch_provider",
        "local_edit",
        "rollback_revision",
        "human_review",
    ]
    scope: str
    reason: FailureCode
    expected_gain: float = 0.0


class RepairRound(BaseModel):
    attempt: int
    residual_severity: float
    residual_count: int
    actual_cost_usd: float = 0.0
    marginal_gain: float = 0.0
    new_failure_rate: float = 0.0


class RepairDecision(BaseModel):
    should_repair: bool
    stop_reason: str | None = None
    actions: list[RepairAction] = Field(default_factory=list)
    attempts_left: int = 0
    budget_left_usd: float = 0.0


_ACTION_FOR_CODE: dict[FailureCode, tuple[str, float]] = {
    FailureCode.IDENTITY_MISMATCH: ("replace_reference", 0.8),
    FailureCode.WARDROBE_MISMATCH: ("recompile_prompt", 0.5),
    FailureCode.SCENE_CONTINUITY: ("recompile_prompt", 0.5),
    FailureCode.SCREEN_DIRECTION: ("recompile_prompt", 0.4),
    FailureCode.EYELINE_VIOLATION: ("recompile_prompt", 0.4),
    FailureCode.ANATOMY_ARTIFACT: ("retry_new_seed", 0.5),
    FailureCode.CAMERA_CONTRACT: ("recompile_prompt", 0.4),
    FailureCode.ACTION_MISSING: ("retry_new_seed", 0.4),
    FailureCode.DIALOGUE_MISSING: ("recompile_prompt", 0.6),
    FailureCode.LIPSYNC_DRIFT: ("local_edit", 0.4),
    FailureCode.AUDIO_QUALITY: ("recompile_prompt", 0.5),
    FailureCode.TIMING_PACING: ("recompile_prompt", 0.3),
    FailureCode.STYLE_DRIFT: ("recompile_prompt", 0.4),
    FailureCode.PROVIDER_FAILURE: ("switch_provider", 0.8),
    FailureCode.QUOTA_OR_BALANCE: ("switch_provider", 0.7),
    FailureCode.DELIVERY_INTEGRITY: ("retry_new_seed", 0.8),
    FailureCode.SAFETY_POLICY: ("human_review", 0.0),
    FailureCode.QUALITY_CHECKER_FAILURE: ("human_review", 0.0),
}


class RepairController:
    def __init__(self, budget: RepairBudget | None = None) -> None:
        self.budget = budget or RepairBudget()
        self.rounds: list[RepairRound] = []
        self.spent_usd = 0.0
        self._last_codes: set[FailureCode] = set()

    def observe(
        self, evaluation: QualityEvaluation, *, actual_cost_usd: float = 0.0
    ) -> RepairRound:
        previous = self.rounds[-1] if self.rounds else None
        # Use evaluator_id as code for new EvaluationEvidence
        current_codes: set[FailureCode] = set()
        for item in evaluation.evidence:
            if not item.passed and item.evaluator_id:
                code = FailureCode(item.evaluator_id) if item.evaluator_id in FailureCode.__members__ else FailureCode.DELIVERY_INTEGRITY
                current_codes.add(code)
        if previous is None:
            marginal_gain = 0.0
        else:
            delta = previous.residual_severity - evaluation.residual_severity
            marginal_gain = delta / max(actual_cost_usd, 1.0)
        new_failures = current_codes - self._last_codes
        new_rate = len(new_failures) / max(len(current_codes), 1)
        round_state = RepairRound(
            attempt=len(self.rounds),
            residual_severity=evaluation.residual_severity,
            residual_count=evaluation.residual_count,
            actual_cost_usd=actual_cost_usd,
            marginal_gain=marginal_gain,
            new_failure_rate=new_rate,
        )
        self.rounds.append(round_state)
        self.spent_usd += actual_cost_usd
        self._last_codes = current_codes
        return round_state

    def decide(self, evaluation: QualityEvaluation) -> RepairDecision:
        attempts_used = max(0, len(self.rounds) - 1)
        attempts_left = max(0, self.budget.max_attempts - attempts_used)
        budget_left = max(0.0, self.budget.max_cost_usd - self.spent_usd)
        if evaluation.passed:
            return RepairDecision(
                should_repair=False,
                stop_reason="gates_passed",
                attempts_left=attempts_left,
                budget_left_usd=budget_left,
            )
        if attempts_left <= 0:
            return self._stop("attempt_budget_exhausted", attempts_left, budget_left)
        if self.spent_usd >= self.budget.max_cost_usd > 0:
            return self._stop("repair_budget_exhausted", attempts_left, budget_left)
        if (
            len(self.rounds) > 1
            and self.rounds[-1].new_failure_rate > self.budget.max_new_failure_rate
        ):
            return self._stop("divergence_detected", attempts_left, budget_left)
        low_gain = sum(
            1
            for item in self.rounds[1:]
            if item.marginal_gain < self.budget.min_marginal_gain
        )
        if low_gain >= self.budget.low_gain_rounds_to_stop:
            return self._stop("convergence_stalled", attempts_left, budget_left)

        actions: list[RepairAction] = []
        seen: set[tuple[str, str]] = set()
        for item in evaluation.evidence:
            if item.passed:
                continue
            kind, expected_gain = _ACTION_FOR_CODE.get(
                normalize_failure(item.evaluator_id), ("human_review", 0.0)
            )
            key = (kind, item.constraint_id or item.evaluator_id)
            if key in seen:
                continue
            seen.add(key)
            actions.append(
                RepairAction(
                    kind=kind,  # type: ignore[arg-type]
                    scope=item.constraint_id or item.evaluator_id,
                    reason=normalize_failure(item.evaluator_id),
                    expected_gain=expected_gain,
                )
            )
        auto_actions = {
            "regenerate_same_provider",
            "retry_new_seed",
            "recompile_prompt",
            "replace_reference",
            "switch_provider",
        }
        has_auto_action = any(item.kind in auto_actions for item in actions)
        return RepairDecision(
            should_repair=has_auto_action,
            stop_reason=(
                None
                if has_auto_action
                else ("manual_repair_required" if actions else "no_repair_action")
            ),
            actions=actions,
            attempts_left=attempts_left,
            budget_left_usd=budget_left,
        )

    @staticmethod
    def _stop(reason: str, attempts_left: int, budget_left: float) -> RepairDecision:
        return RepairDecision(
            should_repair=False,
            stop_reason=reason,
            attempts_left=attempts_left,
            budget_left_usd=budget_left,
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "budget": self.budget.model_dump(mode="json"),
            "spent_usd": self.spent_usd,
            "rounds": [item.model_dump(mode="json") for item in self.rounds],
        }


__all__ = [
    "RepairAction",
    "RepairBudget",
    "RepairController",
    "RepairDecision",
]
