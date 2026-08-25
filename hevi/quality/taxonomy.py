"""Stable failure codes used by gates, repair and quality analytics."""

from __future__ import annotations

from enum import StrEnum


class FailureCode(StrEnum):
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    WARDROBE_MISMATCH = "WARDROBE_MISMATCH"
    SCENE_CONTINUITY = "SCENE_CONTINUITY"
    SCREEN_DIRECTION = "SCREEN_DIRECTION"
    EYELINE_VIOLATION = "EYELINE_VIOLATION"
    ANATOMY_ARTIFACT = "ANATOMY_ARTIFACT"
    CAMERA_CONTRACT = "CAMERA_CONTRACT"
    ACTION_MISSING = "ACTION_MISSING"
    DIALOGUE_MISSING = "DIALOGUE_MISSING"
    LIPSYNC_DRIFT = "LIPSYNC_DRIFT"
    AUDIO_QUALITY = "AUDIO_QUALITY"
    TIMING_PACING = "TIMING_PACING"
    STYLE_DRIFT = "STYLE_DRIFT"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    QUOTA_OR_BALANCE = "QUOTA_OR_BALANCE"
    DELIVERY_INTEGRITY = "DELIVERY_INTEGRITY"
    SAFETY_POLICY = "SAFETY_POLICY"
    QUALITY_CHECKER_FAILURE = "QUALITY_CHECKER_FAILURE"


_SEVERITY = {
    FailureCode.IDENTITY_MISMATCH: 5.0,
    FailureCode.WARDROBE_MISMATCH: 3.0,
    FailureCode.SCENE_CONTINUITY: 3.0,
    FailureCode.SCREEN_DIRECTION: 3.0,
    FailureCode.EYELINE_VIOLATION: 3.0,
    FailureCode.ANATOMY_ARTIFACT: 4.0,
    FailureCode.CAMERA_CONTRACT: 2.0,
    FailureCode.ACTION_MISSING: 3.0,
    FailureCode.DIALOGUE_MISSING: 4.0,
    FailureCode.LIPSYNC_DRIFT: 4.0,
    FailureCode.AUDIO_QUALITY: 2.0,
    FailureCode.TIMING_PACING: 2.0,
    FailureCode.STYLE_DRIFT: 1.0,
    FailureCode.PROVIDER_FAILURE: 4.0,
    FailureCode.QUOTA_OR_BALANCE: 5.0,
    FailureCode.DELIVERY_INTEGRITY: 5.0,
    FailureCode.SAFETY_POLICY: 5.0,
    FailureCode.QUALITY_CHECKER_FAILURE: 5.0,
}


def severity_for(code: FailureCode | str) -> float:
    try:
        normalized = code if isinstance(code, FailureCode) else FailureCode(code)
    except ValueError:
        return 3.0
    return _SEVERITY[normalized]


_ALIASES = {
    "参考图角色错配": FailureCode.IDENTITY_MISMATCH,
    "身份漂移": FailureCode.IDENTITY_MISMATCH,
    "衣着不一致": FailureCode.WARDROBE_MISMATCH,
    "场景连续性": FailureCode.SCENE_CONTINUITY,
    "越轴": FailureCode.SCREEN_DIRECTION,
    "视线": FailureCode.EYELINE_VIOLATION,
    "崩手": FailureCode.ANATOMY_ARTIFACT,
    "构图": FailureCode.CAMERA_CONTRACT,
    "动作": FailureCode.ACTION_MISSING,
    "对白缺失": FailureCode.DIALOGUE_MISSING,
    "口型漂移": FailureCode.LIPSYNC_DRIFT,
    "provider_failure": FailureCode.PROVIDER_FAILURE,
    "余额": FailureCode.QUOTA_OR_BALANCE,
    "交付完整性": FailureCode.DELIVERY_INTEGRITY,
    "质检器失败": FailureCode.QUALITY_CHECKER_FAILURE,
}


def normalize_failure(value: FailureCode | str | None) -> FailureCode:
    if isinstance(value, FailureCode):
        return value
    raw = str(value or "DELIVERY_INTEGRITY")
    try:
        return FailureCode(raw)
    except ValueError:
        for alias, code in _ALIASES.items():
            if alias in raw:
                return code
    return FailureCode.DELIVERY_INTEGRITY


__all__ = ["FailureCode", "normalize_failure", "severity_for"]
