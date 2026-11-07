"""hevi/judge — video judge, hard checks, pairwise comparison, self-iteration."""
from __future__ import annotations

from hevi.judge.backend import (
    AgyBackend,
    GeminiCliBackend,
    LocalMetricsBackend,
    MockBackend,
    OpencodeJudgeBackend,
    select_backend,
)
from hevi.judge.calibration import calibrate
from hevi.judge.hard_checks import run_hard_checks
from hevi.judge.pairwise import run_pairwise
from hevi.judge.self_iterate import generate_zeroline, run_self_iterate
from hevi.judge.types import (
    BackendResult,
    HardCheckReport,
    HardFinding,
    IterationRecord,
    PairwiseComparison,
    PairwiseJudgement,
    SelfIterateResult,
)

__all__ = [
    "AgyBackend",
    "BackendResult",
    "GeminiCliBackend",
    "HardCheckReport",
    "HardFinding",
    "IterationRecord",
    "LocalMetricsBackend",
    "MockBackend",
    "OpencodeJudgeBackend",
    "PairwiseComparison",
    "PairwiseJudgement",
    "SelfIterateResult",
    "calibrate",
    "generate_zeroline",
    "run_hard_checks",
    "run_pairwise",
    "run_self_iterate",
    "select_backend",
]
