"""Profile-specific fail-open/fail-closed quality gate policy."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .taxonomy import FailureCode, normalize_failure


class GatePolicy(BaseModel):
    profile: Literal["economy", "standard", "cinema"] = "standard"
    identity_floor: float = Field(default=0.75, ge=0.0, le=1.0)
    required_failures: set[FailureCode] = Field(default_factory=set)
    advisory_failures: set[FailureCode] = Field(default_factory=set)
    artifact_required: bool = True
    allow_checker_failure: bool = False

    @classmethod
    def for_profile(cls, profile: str = "standard") -> GatePolicy:
        profile = profile if profile in {"economy", "standard", "cinema"} else "standard"
        if profile == "economy":
            required = {
                FailureCode.DELIVERY_INTEGRITY,
                FailureCode.SAFETY_POLICY,
            }
            advisory = {
                FailureCode.IDENTITY_MISMATCH,
                FailureCode.ANATOMY_ARTIFACT,
                FailureCode.SCENE_CONTINUITY,
                FailureCode.QUALITY_CHECKER_FAILURE,
            }
            floor = 0.60
        elif profile == "cinema":
            required = set(FailureCode)
            advisory = set()
            floor = 0.85
        else:
            required = {
                FailureCode.DELIVERY_INTEGRITY,
                FailureCode.IDENTITY_MISMATCH,
                FailureCode.SCENE_CONTINUITY,
                FailureCode.EYELINE_VIOLATION,
                FailureCode.DIALOGUE_MISSING,
                FailureCode.ANATOMY_ARTIFACT,
                FailureCode.CAMERA_CONTRACT,
                FailureCode.ACTION_MISSING,
                FailureCode.SAFETY_POLICY,
                FailureCode.QUALITY_CHECKER_FAILURE,
            }
            advisory = {
                FailureCode.WARDROBE_MISMATCH,
                FailureCode.ANATOMY_ARTIFACT,
                FailureCode.STYLE_DRIFT,
            }
            floor = 0.75
        return cls(
            profile=profile,  # type: ignore[arg-type]
            identity_floor=floor,
            required_failures=required,
            advisory_failures=advisory,
        )

    def blocks(self, code: FailureCode | str) -> bool:
        return normalize_failure(code) in self.required_failures


__all__ = ["GatePolicy"]
