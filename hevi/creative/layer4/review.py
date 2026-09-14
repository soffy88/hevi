"""Persistent review and approval policy."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from hevi.obase.creative import Approval, CreativeObject, NarrativeAudit


class ReviewMode(StrEnum):
    STRICT = "STRICT"
    LENIENT = "LENIENT"
    ALWAYS_REVISE = "ALWAYS_REVISE"
    MANUAL = "MANUAL"
    AUTOMATIC = "AUTOMATIC"


class ReviewWorkflow:
    def decide(
        self,
        *,
        project_id: UUID,
        target: CreativeObject,
        audit: NarrativeAudit,
        actor_id: str,
        mode: ReviewMode,
        note: str | None = None,
    ) -> Approval:
        if mode is ReviewMode.ALWAYS_REVISE:
            decision = "REVISION_REQUEST"
        elif audit.status == "FAIL" or mode is ReviewMode.STRICT:
            decision = "REJECT"
        elif audit.status == "WARN" and mode is ReviewMode.MANUAL:
            decision = "REVISION_REQUEST"
        else:
            decision = "APPROVE"
        return Approval(
            project_id=project_id,
            target_id=target.object_id,
            decision=decision,  # type: ignore[arg-type]
            actor_id=actor_id,
            note=note,
        )


__all__ = ["ReviewMode", "ReviewWorkflow"]
