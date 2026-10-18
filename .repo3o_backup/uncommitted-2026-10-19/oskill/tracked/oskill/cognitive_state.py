"""
认知状态更新算法（BKT + FSRS 统一更新）
=========================================
3O 范式：oskill/cognitive_state.py

职责：
1. 实现 cognitive_update 纯算法（forgetting-aware BKT + FSRS）。
2. 定义算法输入输出数据结构。
"""

from __future__ import annotations

from datetime import UTC, datetime

from obase.cognitive_types import KCState
from oprim.bkt import bkt_update, classify_error
from oprim.fsrs_engine import fsrs_map_rating, fsrs_retrievability, fsrs_review
from pydantic import BaseModel


class CognitiveUpdateInput(BaseModel):
    """认知更新输入。"""

    state: KCState
    card_dict: dict
    is_correct: bool
    used_answer: bool = False
    struggled: bool = False
    effortless: bool = False
    is_interleaved: bool = False
    difficulty: float | None = None  # 题目难度 b∈[0,1]（IRT）；None 时不改变行为
    now: datetime | None = None


class CognitiveUpdateResult(BaseModel):
    """认知更新结果。"""

    state: KCState
    card_dict: dict
    error_type: str | None
    rating: str
    rating_val: int
    effective_mastery: float


def cognitive_update(*, input: CognitiveUpdateInput) -> CognitiveUpdateResult:
    """forgetting-aware BKT + FSRS 统一更新算法（纯函数）。

    Internal oprim composition:
    - oprim.fsrs_retrievability  (算 R)
    - oprim.bkt_update           (forgetting-aware 掌握度更新)
    - oprim.classify_error       (粗心/不会判定)
    - oprim.fsrs_review          (FSRS 卡片更新)
    - oprim.fsrs_map_rating      (表现→Rating)

    更新顺序（MUST，与 CLAUDE.md 红线一致）：
    1. 用旧卡片算 R
    2. forgetting-aware BKT 更新（R 衰减先验）
    3. 答错则 classify_error
    4. FSRS review
    """
    now = input.now or datetime.now(UTC)

    # 1. 算 R (遗忘因子)
    R = fsrs_retrievability(card_dict=input.card_dict, now=now)

    # 2. BKT 更新 (forgetting-aware + 难度感知)
    bkt_update(
        state=input.state,
        is_correct=input.is_correct,
        retrievability=R,
        difficulty=input.difficulty,
    )

    # 3. 错误分类
    error_type = None
    if not input.is_correct:
        error_type = classify_error(state=input.state, difficulty=input.difficulty)

    # 4. FSRS 更新
    rating = fsrs_map_rating(
        is_correct=input.is_correct,
        used_answer=input.used_answer,
        struggled=input.struggled,
        effortless=input.effortless,
    )
    new_card = fsrs_review(card_dict=input.card_dict, rating=rating, now=now)

    # TODO: 5. Recognition 更新 (等 12.1 实现)

    input.state.last_interaction_ts = now.timestamp()

    eff = (input.state.long_term_mastery or input.state.current()) * R

    return CognitiveUpdateResult(
        state=input.state,
        card_dict=new_card,
        error_type=error_type,
        rating=rating.name,
        rating_val=rating.value,
        effective_mastery=eff,
    )


__version__ = "0.3.0"
__manifest__ = {
    "version": __version__,
    "updated_at": "2026-06-13",
    "elements": [
        {"name": "cognitive_update", "layer": "oskill", "summary": "BKT+FSRS 统一更新算法"},
    ],
}
