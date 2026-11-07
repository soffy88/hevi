"""hevi.preflight —— 生成前三件套：门禁＋编译器＋通过率统计。

目标：生成 prompt 一次能过，失败不烧钱。门禁与编译全程本地离线，
不登录谷歌、不调 Flow/Gemini API；烧 credits 的动作永远在门禁之后、
由人工（或已批准的提案）触发。

用法：
    from hevi.preflight import Beat, run_gate, compile_beat, PassRateLedger
    report = run_gate(beat, "veo_fast", ledger={"monthly_remaining": 970,
                                                "daily_remaining": 50})
    report.blocked  # True → 不许发
"""

from __future__ import annotations

from hevi.preflight.beats import (
    FAILURE_CATEGORIES,
    MODEL_SPECS,
    Beat,
    CharacterRef,
    DialogueLine,
    ModelSpec,
    get_model_spec,
)
from hevi.preflight.budget import budget_gate, estimate_cost
from hevi.preflight.compiler import CompiledPrompt, compile_beat, compile_beat_json
from hevi.preflight.dialogue_fit import CLEAR_CPS, HARD_CPS, count_speech_chars, fit_dialogue
from hevi.preflight.findings import Finding, GateReport
from hevi.preflight.first_frame import check_first_frame, contact_sheet
from hevi.preflight.gate import run_batch, run_gate
from hevi.preflight.passrate import FIX_SUGGESTIONS, PassRateLedger
from hevi.preflight.prompt_audit import MODERN_BLACKLIST, audit_prompt

__all__ = [
    "Beat", "CharacterRef", "DialogueLine", "ModelSpec", "MODEL_SPECS",
    "FAILURE_CATEGORIES", "get_model_spec",
    "Finding", "GateReport",
    "audit_prompt", "MODERN_BLACKLIST",
    "check_first_frame", "contact_sheet",
    "count_speech_chars", "fit_dialogue", "CLEAR_CPS", "HARD_CPS",
    "estimate_cost", "budget_gate",
    "CompiledPrompt", "compile_beat", "compile_beat_json",
    "run_gate", "run_batch",
    "PassRateLedger", "FIX_SUGGESTIONS",
]
