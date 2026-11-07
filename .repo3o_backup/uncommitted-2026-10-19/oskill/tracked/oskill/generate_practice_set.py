"""Generate an interleaved practice set from a question bank.

Composes interleave_select + oprim cognitive elements.
Pure deterministic — no LLM.

Version: oskill v3.21.0
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from oskill.interleave_select import QuestionItem, interleave_select


@dataclass(frozen=True)
class PracticeSetConfig:
    """Configuration for practice set generation.

    Attributes
    ----------
    target_count : int
        Desired number of questions in the practice set.
    mastery_threshold : float
        KC mastery below which questions are included (0..1).
    max_difficulty : float
        Maximum difficulty to include (0..1). 1.0 = all difficulties.
    min_difficulty : float
        Minimum difficulty to include.
    balance_kcs : bool
        If True, attempt to balance number of questions per KC.
    seed_kc_id : str | None
        KC to avoid as the first question.
    """

    target_count: int = 10
    mastery_threshold: float = 0.8
    max_difficulty: float = 1.0
    min_difficulty: float = 0.0
    balance_kcs: bool = True
    seed_kc_id: str | None = None


@dataclass(frozen=True)
class PracticeSetResult:
    """Generated practice set.

    Attributes
    ----------
    questions : list[QuestionItem]
        Selected and interleaved questions.
    dropped_count : int
        Number of questions not included.
    kc_distribution : dict[str, int]
        Number of questions per KC.
    mastery_coverage : float
        Fraction of weak KCs covered in this set.
    """

    questions: list[QuestionItem]
    dropped_count: int
    kc_distribution: dict[str, int]
    mastery_coverage: float


def generate_practice_set(
    question_bank: Sequence[QuestionItem],
    kc_mastery: dict[str, float] | None = None,
    config: PracticeSetConfig | None = None,
) -> PracticeSetResult:
    """Generate an interleaved practice set.

    1. Filter questions by difficulty range and KC mastery threshold.
    2. Interleave with the no-adjacent-same-kc constraint.
    3. Cap at config.target_count.

    Parameters
    ----------
    question_bank : Sequence[QuestionItem]
        All available questions.
    kc_mastery : dict[str, float] | None
        Student's current KC mastery (kc_id -> 0..1).
        If provided, updates QuestionItem.mastery from this map.
    config : PracticeSetConfig | None

    Returns
    -------
    PracticeSetResult
    """
    cfg = config or PracticeSetConfig()
    mastery_map = kc_mastery or {}

    # Apply mastery from map and filter
    enriched = [
        QuestionItem(
            question_id=q.question_id,
            kc_id=q.kc_id,
            difficulty=q.difficulty,
            mastery=mastery_map.get(q.kc_id, q.mastery),
        )
        for q in question_bank
    ]

    filtered = [
        q
        for q in enriched
        if (
            q.mastery <= cfg.mastery_threshold
            and cfg.min_difficulty <= q.difficulty <= cfg.max_difficulty
        )
    ]

    if not filtered:
        return PracticeSetResult(
            questions=[],
            dropped_count=len(question_bank),
            kc_distribution={},
            mastery_coverage=0.0,
        )

    # Balance across KCs if requested
    if cfg.balance_kcs:
        from collections import defaultdict

        by_kc: dict[str, list[QuestionItem]] = defaultdict(list)
        for q in filtered:
            by_kc[q.kc_id].append(q)
        # Round-robin selection
        balanced: list[QuestionItem] = []
        kc_queues = list(by_kc.values())
        while any(kc_queues) and len(balanced) < len(filtered):
            for queue in kc_queues:
                if queue:
                    balanced.append(queue.pop(0))
        filtered = balanced

    result = interleave_select(
        filtered,
        max_count=cfg.target_count,
        seed_kc_id=cfg.seed_kc_id,
    )

    # Compute KC distribution
    kc_dist: dict[str, int] = {}
    for q in result.selected:
        kc_dist[q.kc_id] = kc_dist.get(q.kc_id, 0) + 1

    # Mastery coverage: fraction of weak KCs represented
    weak_kcs = {q.kc_id for q in enriched if q.mastery <= cfg.mastery_threshold}
    covered_kcs = {q.kc_id for q in result.selected}
    coverage = len(covered_kcs & weak_kcs) / max(len(weak_kcs), 1)

    total_dropped = len(filtered) - len(result.selected) + len(result.dropped)

    return PracticeSetResult(
        questions=result.selected,
        dropped_count=total_dropped,
        kc_distribution=kc_dist,
        mastery_coverage=coverage,
    )
