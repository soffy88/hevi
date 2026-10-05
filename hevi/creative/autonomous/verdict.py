"""ProductionVerdictAuthority —— **aggregator**,不是第 N+1 个 evaluator。

裁决(2026-10-03):
    Evaluator ≠ Authority · Gate ≠ Authority · ShotVerdict ≠ Authority
    ProductionVerdictAuthority = Authority

它不实现任何评估,只把**既有** evaluator/gate 的结论 + artifact 校验结果聚合成
唯一 FINAL 判据:

    FINAL 的唯一条件 = verdict == PASS 且 artifact.validation.passed == True

不新增 QC system,不新增 QC_PASSED enum 到处传播。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from hevi.validation.artifact import ValidationResult


class VerdictOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"  # 证据不足/未跑,不是失败


@dataclass(frozen=True)
class VerdictInput:
    """一条既有结论。source 必填:无法追溯来源的结论不参与聚合。"""
    source: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class ProductionVerdict:
    outcome: VerdictOutcome
    inputs: tuple[VerdictInput, ...] = ()
    artifact_validated: bool = False
    validation_detail: str = ""

    @property
    def is_final(self) -> bool:
        return self.outcome is VerdictOutcome.PASS and self.artifact_validated

    def failing_sources(self) -> tuple[str, ...]:
        return tuple(i.source for i in self.inputs if not i.passed)


class ProductionVerdictAuthority:
    authority_id = "autonomous/production_verdict"

    def evaluate(self, *, inputs: tuple[VerdictInput, ...],
                 artifact_validation: ValidationResult | None) -> ProductionVerdict:
        for item in inputs:
            if not item.source:
                raise ValueError("VERDICT_UNTRACEABLE:every input needs a source")
        if not inputs:
            # 没有既有结论 = 证据不足 = BLOCKED,不是 PASS(呼应 P10 的 INCONCLUSIVE 纪律)
            return ProductionVerdict(VerdictOutcome.BLOCKED, (),
                                     False, "no evaluator/gate evidence supplied")
        if artifact_validation is None:
            return ProductionVerdict(VerdictOutcome.BLOCKED, inputs, False,
                                     "artifact validation missing")
        if not artifact_validation.passed:
            return ProductionVerdict(VerdictOutcome.FAIL, inputs, False,
                                     f"artifact validation failed: "
                                     f"{[c.name for c in artifact_validation.failed_checks]}")
        if any(not i.passed for i in inputs):
            return ProductionVerdict(VerdictOutcome.FAIL, inputs, True, "")
        return ProductionVerdict(VerdictOutcome.PASS, inputs, True, "")


__all__ = [
    "ProductionVerdict",
    "ProductionVerdictAuthority",
    "VerdictInput",
    "VerdictOutcome",
]