"""Bounded length governance and normalization proposals."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class LengthPolicy:
    target_words: int
    soft_min: int
    soft_max: int
    hard_min: int
    hard_max: int
    max_normalize_passes: int = 2

    def __post_init__(self) -> None:
        if not (
            0
            < self.hard_min
            <= self.soft_min
            <= self.target_words
            <= self.soft_max
            <= self.hard_max
        ):
            raise ValueError("invalid length ranges")
        if self.max_normalize_passes < 1:
            raise ValueError("max_normalize_passes must be positive")


@dataclass(frozen=True)
class LengthReport:
    word_count: int
    status: str
    direction: str | None
    passes: int


class LengthModule:
    def inspect(self, text: str, policy: LengthPolicy) -> LengthReport:
        count = len(text.split())
        if count < policy.hard_min or count > policy.hard_max:
            status = "FAIL"
        elif count < policy.soft_min or count > policy.soft_max:
            status = "WARN"
        else:
            status = "PASS"
        direction = (
            "EXPAND" if count < policy.soft_min else "COMPRESS" if count > policy.soft_max else None
        )
        return LengthReport(count, status, direction, 0)

    def normalize(
        self,
        text: str,
        policy: LengthPolicy,
        *,
        generator: Callable[[str, str, int], str],
    ) -> tuple[str, LengthReport]:
        current = text
        for pass_number in range(1, policy.max_normalize_passes + 1):
            report = self.inspect(current, policy)
            if report.status == "PASS":
                return current, LengthReport(
                    report.word_count, report.status, report.direction, pass_number - 1
                )
            if report.status == "FAIL" and report.direction is None:
                raise ValueError("LENGTH_GOVERNANCE_HARD_RANGE")
            current = generator(current, report.direction or "", policy.target_words)
        final = self.inspect(current, policy)
        if final.status != "PASS":
            raise ValueError("LENGTH_GOVERNANCE_NORMALIZATION_LIMIT")
        return current, LengthReport(
            final.word_count, final.status, final.direction, policy.max_normalize_passes
        )


__all__ = ["LengthModule", "LengthPolicy", "LengthReport"]
