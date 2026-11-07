"""Select and interleave questions ensuring no adjacent same kc_id.

Pure deterministic algorithm — no LLM.
Hard constraint: adjacent questions must have different kc_id.

Version: oskill v3.21.0
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class QuestionItem:
    """A question item for interleaving.

    Attributes
    ----------
    question_id : str
    kc_id : str
        Knowledge component this question targets.
    difficulty : float
        0..1, used for ordering within same kc.
    mastery : float
        Student's mastery of this KC (0..1), used for selection weighting.
    """

    question_id: str
    kc_id: str
    difficulty: float = 0.5
    mastery: float = 0.5


@dataclass(frozen=True)
class InterleaveResult:
    """Result of interleaved question selection.

    Attributes
    ----------
    selected : list[QuestionItem]
        Interleaved sequence with no adjacent same kc_id.
    dropped : list[QuestionItem]
        Items that could not be placed without violating the constraint.
    """

    selected: list[QuestionItem]
    dropped: list[QuestionItem]


def _score(item: QuestionItem) -> float:
    """Higher score = higher priority for selection."""
    return (1.0 - item.mastery) * 0.6 + item.difficulty * 0.4


def interleave_select(
    questions: Sequence[QuestionItem],
    max_count: int | None = None,
    *,
    seed_kc_id: str | None = None,
) -> InterleaveResult:
    """Select and interleave questions with no adjacent same kc_id.

    The algorithm:
    1. Sort questions by priority score (lowest mastery + appropriate difficulty first).
    2. Greedily select the next highest-priority question that doesn't share
       kc_id with the last selected item.
    3. If no valid next question exists (all remaining have the same kc_id
       as the last), move to the next best available from a different kc.

    Hard constraint guaranteed: adjacent items in `selected` always have
    different kc_id values.

    Parameters
    ----------
    questions : Sequence[QuestionItem]
    max_count : int | None
        Maximum number of items to return. None = all.
    seed_kc_id : str | None
        If provided, the first selected item must NOT have this kc_id.

    Returns
    -------
    InterleaveResult

    Raises
    ------
    ValueError
        If questions contains items with fewer than 2 distinct kc_ids
        but more than 1 item (interleaving is impossible).
    """
    if not questions:
        return InterleaveResult(selected=[], dropped=[])

    kc_ids = {q.kc_id for q in questions}
    if len(questions) > 1 and len(kc_ids) < 2:
        raise ValueError(
            f"Cannot interleave {len(questions)} questions with only 1 kc_id "
            f"({next(iter(kc_ids))}). Need at least 2 distinct kc_ids."
        )

    pool = sorted(questions, key=lambda q: -_score(q))
    selected: list[QuestionItem] = []
    dropped: list[QuestionItem] = []
    remaining = list(pool)

    last_kc: str | None = seed_kc_id

    while remaining:
        if max_count is not None and len(selected) >= max_count:
            dropped.extend(remaining)
            break

        # Find highest-priority item that doesn't repeat last_kc
        chosen = None
        chosen_idx = -1
        for i, item in enumerate(remaining):
            if item.kc_id != last_kc:
                chosen = item
                chosen_idx = i
                break

        if chosen is None:
            # All remaining items share last_kc — try from the beginning
            # (can happen with very skewed distributions)
            # Drop the first one and retry
            dropped.append(remaining.pop(0))
            continue

        selected.append(chosen)
        remaining.pop(chosen_idx)
        last_kc = chosen.kc_id

    return InterleaveResult(selected=selected, dropped=dropped)
