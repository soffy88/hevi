"""hevi L3 裁决层 —— shot_scorecard(评分卡)+ 帧抽取 + 成片终检。3O manifest §C4。

3O 内化 Phase A: 失败模式注册表 / replay trace / 摄入侧帧去重(dramaclaw + claude-video)。
3O 内化 Phase B: 判例式审美准则(video-shotcraft)。
3O 内化 Phase D: 收敛循环(dramaclaw)。
3O 内化 Round 3: 成片独立终检协议(video-shotcraft final-review)。
"""

from hevi.verdict.aesthetic_canon import (
    SEED_CANON,
    AestheticCanon,
    CanonRule,
    build_self_check_report,
    default_canon,
    validate_canon,
)
from hevi.verdict.convergence import ConvergenceLog, ConvergenceRound, trend
from hevi.verdict.failure_registry import (
    SEED_FAILURE_MODES,
    FailureHits,
    FailureMode,
    FailureRegistry,
    default_registry,
)
from hevi.verdict.final_review import (
    FINAL_REVIEW_CHECKS,
    REVIEW_INPUTS,
    FinalReviewResult,
    render_review_report,
    run_final_review,
    save_review_result,
)
from hevi.verdict.frame_extract import FrameExtractError, extract_representative_frame
from hevi.verdict.replay_trace import (
    ReplayTraceError,
    TraceHandle,
    begin_trace,
    finalize,
    load_traces,
    record_gate,
    record_prompt_and_response,
    summary,
)
from hevi.verdict.scorecard import (
    Scorecard,
    check_relationship_consistency,
    coarse_diagnosis,
    make_scorecard_consistency_fn,
    shot_scorecard,
)

__all__ = [
    "FINAL_REVIEW_CHECKS",
    "REVIEW_INPUTS",
    "SEED_CANON",
    "SEED_FAILURE_MODES",
    "AestheticCanon",
    "CanonRule",
    "ConvergenceLog",
    "ConvergenceRound",
    "FailureHits",
    "FailureMode",
    "FailureRegistry",
    "FinalReviewResult",
    "FrameExtractError",
    "ReplayTraceError",
    "Scorecard",
    "TraceHandle",
    "begin_trace",
    "build_self_check_report",
    "check_relationship_consistency",
    "coarse_diagnosis",
    "default_canon",
    "default_registry",
    "extract_representative_frame",
    "finalize",
    "load_traces",
    "make_scorecard_consistency_fn",
    "record_gate",
    "record_prompt_and_response",
    "render_review_report",
    "run_final_review",
    "save_review_result",
    "shot_scorecard",
    "summary",
    "trend",
    "validate_canon",
]
