"""Explicit fail-closed taxonomy for narrative operations."""

from __future__ import annotations

from typing import Literal

NarrativeErrorCode = Literal[
    "NARRATIVE_SCHEMA_INVALID", "CONTEXT_BUILD_FAILED", "CONTINUITY_CONFLICT", "STALE_REVISION",
    "REVISION_LIMIT", "LLM_TRUNCATED", "LLM_INVALID_STRUCTURE", "SOURCE_EVIDENCE_MISSING",
    "SCENE_PLAN_FAILED", "SHOT_ADAPTER_FAILED",
]

ERROR_CODES: tuple[NarrativeErrorCode, ...] = (
    "NARRATIVE_SCHEMA_INVALID", "CONTEXT_BUILD_FAILED", "CONTINUITY_CONFLICT", "STALE_REVISION",
    "REVISION_LIMIT", "LLM_TRUNCATED", "LLM_INVALID_STRUCTURE", "SOURCE_EVIDENCE_MISSING",
    "SCENE_PLAN_FAILED", "SHOT_ADAPTER_FAILED",
)


class NarrativeFailure(ValueError):
    def __init__(self, code: NarrativeErrorCode, detail: str = "") -> None:
        self.code = code
        super().__init__(f"{code}{':' + detail if detail else ''}")


def fail_closed(code: NarrativeErrorCode, detail: str = "") -> None:
    raise NarrativeFailure(code, detail)
