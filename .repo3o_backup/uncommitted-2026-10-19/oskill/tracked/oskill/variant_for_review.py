"""复习变式生成 (oskill_variant_for_review)

职责：复习时按知识点出变式题而非原题（变式检索 > 普通间隔重复）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from oprim.generate_variant import VariantInput, VariantItem, generate_variant


@dataclass(frozen=True)
class ReviewVariantInput:
    student_id: str
    kc_id: str
    original_question: str  # 到期的那道原题
    original_answer: str
    variant_type: str = "same_structure"


async def variant_for_review(
    inp: ReviewVariantInput, *, caller: Any, model: str = "claude-sonnet-4-6"
) -> VariantItem:
    """为复习生成变式。"""

    # 直接调用 generate_variant
    v_inp = VariantInput(
        original_question=inp.original_question,
        original_answer=inp.original_answer,
        kc_ids=[inp.kc_id],
        variant_type=inp.variant_type,
    )

    result = await generate_variant(v_inp, caller=caller, model=model)

    # 如果生成失败，降级逻辑通常由调用方处理（比如返回原题）
    # 这里只负责调用生成原子
    return result


__version__ = "0.1.0"
