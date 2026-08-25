from hevi.quality import (
    FailureCode,
    GatePolicy,
    QualityEvaluation,
    QualityEvidence,
    RepairBudget,
    RepairController,
)


def _failed(code: FailureCode, scope: str = "shot:S01") -> QualityEvidence:
    return QualityEvidence(code=code, scope=scope, passed=False)


def test_gate_policy_changes_fail_closed_behavior_by_profile() -> None:
    evidence = [_failed(FailureCode.IDENTITY_MISMATCH)]

    economy = QualityEvaluation.from_evidence(evidence, GatePolicy.for_profile("economy"))
    standard = QualityEvaluation.from_evidence(evidence, GatePolicy.for_profile("standard"))

    assert economy.passed
    assert not standard.passed
    assert standard.residual_severity > 0


def test_missing_quality_checker_is_fail_closed_for_standard_and_cinema() -> None:
    evidence = [_failed(FailureCode.QUALITY_CHECKER_FAILURE)]

    economy = QualityEvaluation.from_evidence(evidence, GatePolicy.for_profile("economy"))
    standard = QualityEvaluation.from_evidence(evidence, GatePolicy.for_profile("standard"))
    cinema = QualityEvaluation.from_evidence(evidence, GatePolicy.for_profile("cinema"))

    assert economy.passed
    assert not standard.passed
    assert not cinema.passed


def test_repair_controller_returns_scoped_action_then_exhausts_budget() -> None:
    policy = GatePolicy.for_profile("standard")
    failed = QualityEvaluation.from_evidence(
        [_failed(FailureCode.IDENTITY_MISMATCH)], policy
    )
    controller = RepairController(RepairBudget(max_attempts=1))
    controller.observe(failed)

    first = controller.decide(failed)

    assert first.should_repair
    assert first.actions[0].kind == "replace_reference"
    assert first.actions[0].scope == "shot:S01"

    controller.observe(failed)
    exhausted = controller.decide(failed)
    assert not exhausted.should_repair
    assert exhausted.stop_reason == "attempt_budget_exhausted"


def test_repair_controller_stops_on_new_failure_divergence() -> None:
    policy = GatePolicy.for_profile("standard")
    controller = RepairController(RepairBudget(max_attempts=3, max_new_failure_rate=0.5))
    first = QualityEvaluation.from_evidence(
        [_failed(FailureCode.IDENTITY_MISMATCH)], policy
    )
    second = QualityEvaluation.from_evidence(
        [_failed(FailureCode.ANATOMY_ARTIFACT)], policy
    )
    controller.observe(first)
    controller.decide(first)
    controller.observe(second)

    decision = controller.decide(second)

    assert not decision.should_repair
    assert decision.stop_reason == "divergence_detected"
