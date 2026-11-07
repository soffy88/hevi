"""hevi/judge types."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class HardFinding:
    name: str
    severity: str
    detail: str
    metric: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HardCheckReport:
    video_path: str
    passed: bool
    findings: list[HardFinding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_path": self.video_path,
            "passed": self.passed,
            "findings": [f.to_dict() for f in self.findings],
            "metrics": self.metrics,
        }


@dataclass
class BackendResult:
    backend: str
    text: str
    raw: Any = None
    model: str = ""
    calls: int = 1
    elapsed_s: float = 0.0


@dataclass
class PairwiseJudgement:
    winner: str
    reason: str = ""
    improvements: list[str] = field(default_factory=list)
    hard_defects: dict[str, list[str]] = field(default_factory=dict)
    raw: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "winner": self.winner,
            "reason": self.reason,
            "improvements": list(self.improvements),
            "hard_defects": self.hard_defects,
        }


@dataclass
class PairwiseComparison:
    video_a: str
    video_b: str
    run_forward: PairwiseJudgement
    run_swapped: PairwiseJudgement
    winner: str
    consistent: bool
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_a": self.video_a,
            "video_b": self.video_b,
            "run_forward": self.run_forward.to_dict(),
            "run_swapped": self.run_swapped.to_dict(),
            "winner": self.winner,
            "consistent": self.consistent,
            "reason": self.reason,
        }


@dataclass
class IterationRecord:
    version: int
    video_path: str
    hard_report: HardCheckReport
    pairwise_vs_prev: PairwiseComparison | None = None
    adopted: bool = True
    changes: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "video_path": self.video_path,
            "hard_report": self.hard_report.to_dict(),
            "pairwise_vs_prev": (self.pairwise_vs_prev.to_dict() if self.pairwise_vs_prev else None),
            "adopted": self.adopted,
            "changes": list(self.changes),
            "params": self.params,
        }


@dataclass
class SelfIterateResult:
    line_id: str
    versions: list[IterationRecord] = field(default_factory=list)
    final_path: str = ""
    final_version: int = 0
    total_calls: int = 0
    total_elapsed_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_id": self.line_id,
            "versions": [v.to_dict() for v in self.versions],
            "final_path": self.final_path,
            "final_version": self.final_version,
            "total_calls": self.total_calls,
            "total_elapsed_s": self.total_elapsed_s,
        }
