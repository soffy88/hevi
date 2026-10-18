"""
Echo-Loop 学习闭环 Skill实现（oskill 层）
============================================

组合 ≥2 个 oprim 原语形成完整学习流程。

依赖 oprim 原语：
- oprim.blind_listen_generate（盲听）
- oprim.intensive_listen_parse（精听）
- oprim.shadowing_evaluate（跟读）
- oprim.retell_evaluate（复述）

T.10 认知主线：在每个 Stage 结束后经 cognitive_update 更新 P(L)。
"""

from __future__ import annotations

from datetime import UTC, datetime

from obase.cognitive_types import KCState
from oprim.bkt import bkt_update, classify_error
from oprim.echo_loop import (
    BlindListenOutput,
    IntensiveListenOutput,
    RetellOutput,
    ShadowingOutput,
    blind_listen_generate,
    intensive_listen_parse,
    retell_evaluate,
    shadowing_evaluate,
)
from oprim.fsrs_engine import (
    fsrs_map_rating,
    fsrs_retrievability,
    fsrs_review,
)
from pydantic import BaseModel, ConfigDict

# ──────────────────────────────────────────────────────────────────────────────
# 学习循环状态
# ──────────────────────────────────────────────────────────────────────────────


class EchoLoopStage(BaseModel):
    """学习循环阶段。"""

    value: str
    completed: bool = False
    mastery_updates: int = 0


class EchoLoopResult(BaseModel):
    """完整学习循环结果。"""

    stage: EchoLoopStage
    blind_listen: BlindListenOutput | None = None
    intensive_listen: IntensiveListenOutput | None = None
    shadowing: ShadowingOutput | None = None
    retell: RetellOutput | None = None

    # 认知更新结果
    kc_state: KCState
    card_dict: dict
    effective_mastery: float  # P(L) = long_term × R

    # 元数据
    session_id: str
    timestamps: dict  # 各阶段耗时

    model_config = ConfigDict(arbitrary_types_allowed=True)


# ──────────────────────────────────────────────────────────────────────────────
# T.10 认知更新（T.6-redline：错误分类用 step_evidence 打破平局）
# ──────────────────────────────────────────────────────────────────────────────


class CognitiveUpdateInput(BaseModel):
    """认知更新输入 - 综合各阶段证据。"""

    state: KCState
    card_dict: dict
    overall_result: dict  # EchoLoopResult 的 dict 形式
    step_evidence: str | None = None  # "careless" / "dontknow" / None
    now: datetime | None = None
    min_review_interval_hours: float = 0.0


def _update_cognitive_state(
    *,
    input: CognitiveUpdateInput,
) -> dict:
    """在学习循环结束后更新认知状态。

    红线顺序（CL v5 §3）：
    1. 用旧卡片算 R
    2. forgetting-aware BKT 更新（R 衰减先验）
    3. 答错则 classify_error
    4. 步骤证据平局判定（T.6）
    5. FSRS review
    """
    now = input.now or datetime.now(UTC)

    # 获取各阶段结果
    overall = input.overall_result
    kc_state = input.state
    card_dict = input.card_dict

    # 从 retell overall_score 判断是否答对
    is_correct = overall.get("retell", {}).get("overall_score", 0.0) >= 0.6

    # 1. 算 R (遗忘因子)
    # 使用 card_dict 中的 last_review 和 difficulty
    rating_val = fsrs_retrievability(card_dict=card_dict, now=now)
    R = rating_val  # effective retrievability

    # 2. BKT 更新 (forgetting-aware)
    bkt_update(
        state=kc_state,
        is_correct=is_correct,
        retrievability=R,
        difficulty=overall.get("retell", {}).get("coverage_score", 0.5),
    )

    # 3. 错误分类
    error_type = None
    if not is_correct:
        error_type = classify_error(state=kc_state, difficulty=0.5)
        # T.6 红线：step_evidence 平局判定
        if input.step_evidence in ("careless", "dontknow") and input.step_evidence != error_type:
            cw, dw = error_weights(state=kc_state, difficulty=0.5)
            hi, lo = max(cw, dw), min(cw, dw)
            if hi > 0 and lo / hi >= 0.8:
                error_type = input.step_evidence

    # 4. FSRS 评估和更新
    rating = fsrs_map_rating(
        is_correct=is_correct,
        used_answer=False,  # 复述阶段一般不算是"使用了答案"
        struggled=overall.get("retell", {}).get("hallucinated_points", []),
        effortless=overall.get("retell", {}).get("fluency_score", 1.0) >= 0.8,
    )
    schedule_advanced = True  # 默认推进

    # T.10 浓缩练习去抖：若间隔过短，不推进调度
    last_review = card_dict.get("last_review")
    if last_review:
        try:
            last_dt = (
                datetime.fromisoformat(last_review) if isinstance(last_review, str) else last_review
            )
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=UTC)
            elapsed_h = (now - last_dt).total_seconds() / 3600.0
            if elapsed_h < 1.0:  # 小于1小时视为浓缩练习
                schedule_advanced = False
        except (ValueError, TypeError):
            pass

    if schedule_advanced:
        new_card = fsrs_review(card_dict=card_dict, rating=rating, now=now)
    else:
        new_card = card_dict

    # 5. 计算有效掌握度
    effective_mastery = (kc_state.long_term_mastery or kc_state.current()) * R

    return {
        "kc_state": kc_state,
        "card_dict": new_card,
        "error_type": error_type,
        "rating": rating.name,
        "rating_val": rating.value,
        "effective_mastery": round(effective_mastery, 4),
        "schedule_advanced": schedule_advanced,
    }


def error_weights(state: KCState, difficulty: float | None = None) -> tuple[float, float]:
    """返回两类错误权重 (careless, dontknow) 的比值，用于 T.6 平局判定。"""
    # 简化实现：返回默认权重
    # 精确计算见 vendor.oprim.errors
    return (0.6, 0.4)  # careless, dontknow 默认比例


# ──────────────────────────────────────────────────────────────────────────────
# 完整学习循环编排
# ──────────────────────────────────────────────────────────────────────────────


async def run_complete_echo_loop(
    *,
    audio_b64: str,
    transcript: str,
    student_retell: str,  # 仅在 retell 阶段需要
    reference_kc_ids: list[str],
    kc_state: KCState,
    card_dict: dict,
    student_audio_b64: str | None = None,  # 用于 shadowing
    now: datetime | None = None,
) -> EchoLoopResult:
    """
    运行完整的 Echo-Loop 学习循环。

    流程：盲听 → 精听 → 跟读 → 复述 → 认知更新

    这是 oskill 层：组合了 4 个不同的 oprim 原语。

    输入:
        audio_b64: 音频数据
        transcript: 完整文本
        student_retell: 学生复述内容
        reference_kc_ids: 关联知识点ID
        kc_state: 知识点状态 (BKT)
        card_dict: 卡片字典 (FSRS)
        student_audio_b64: 学生跟读录音（可选）
        now: 当前时间

    输出:
        EchoLoopResult: 包含各阶段输出和最终认知状态
    """
    _now = now or datetime.now(UTC)

    # T.1 盲听
    blind_result = await blind_listen_generate(
        audio_b64=audio_b64,
        transcript=transcript,
        reference_kc_ids=reference_kc_ids,
    )

    # T.2 精听
    intensive_result = await intensive_listen_parse(
        transcript=transcript,
        blind_listen_output=blind_result.model_dump() if blind_result else None,
    )

    # T.3 跟读 (如果提供了学生录音)
    shadowing_result: ShadowingOutput | None = None
    if student_audio_b64:
        shadowing_result = await shadowing_evaluate(
            reference_text=transcript,
            student_audio_b64=student_audio_b64,
        )

    # T.4 复述
    retell_result = await retell_evaluate(
        original_text=transcript,
        student_retell=student_retell or "",
        reference_kc_ids=reference_kc_ids,
    )

    # T.10 认知更新 (红线顺序)
    cognitive = _update_cognitive_state(
        input=CognitiveUpdateInput(
            state=kc_state,
            card_dict=card_dict,
            overall_result={
                "blind_listen": blind_result.model_dump() if blind_result else None,
                "intensive_listen": intensive_result.model_dump() if intensive_result else None,
                "shadowing": shadowing_result.model_dump() if shadowing_result else None,
                "retell": retell_result.model_dump() if retell_result else None,
            },
            step_evidence=retell_result.missing_key_points
            or retell_result.hallucinated_points
            and len(retell_result.missing_key_points) > 0
            and retell_result.overall_score < 0.4
            and "careless",  # 或 "dontknow"，取决于语境
            now=_now,
        )
    )

    # 构建结果
    return EchoLoopResult(
        stage=EchoLoopStage(value="completed", completed=True, mastery_updates=1),
        blind_listen=blind_result,
        intensive_listen=intensive_result,
        shadowing=shadowing_result,
        retell=retell_result,
        kc_state=cognitive["kc_state"],
        card_dict=cognitive["card_dict"],
        effective_mastery=cognitive["effective_mastery"],
        session_id=f"echo_loop_{_now.timestamp()}",
        timestamps={
            "blind_listen": 0,  # 由调度器记录
            "intensive_listen": 0,
            "shadowing": 0 if not shadowing_result else 0,
            "retell": 0,
        },
    )
