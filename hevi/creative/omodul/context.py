"""Governed, auditable context selection for creative tasks."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from hevi.obase.creative import ContextItem, ContextManifest, ProvenanceRef


class ContextBuildError(ValueError):
    """Raised when protected context cannot fit the declared budget."""


class ContextBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_tokens: int = Field(gt=0)
    reserved_generation_tokens: int = Field(default=0, ge=0)
    priority_classes: tuple[str, ...] = ("P0", "P1", "P2", "P3")

    @property
    def input_tokens(self) -> int:
        available = self.max_tokens - self.reserved_generation_tokens
        if available <= 0:
            raise ContextBuildError("context budget leaves no input tokens")
        return available


class ContextCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: ProvenanceRef
    text: str = Field(min_length=1)
    priority: Literal["P0", "P1", "P2", "P3"] = "P2"
    protected: bool = False
    compressed_text: str | None = None


class CreativeContextCompiler:
    """Select a minimal working set without silently dropping constraints."""

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(1, (len(text) + 3) // 4)

    def compile(
        self,
        *,
        project_id: UUID,
        task: str,
        candidates: Iterable[ContextCandidate],
        budget: ContextBudget,
    ) -> ContextManifest:
        available = budget.input_tokens
        ordered = list(candidates)
        priorities = {name: index for index, name in enumerate(budget.priority_classes)}
        ordered.sort(key=lambda item: (not item.protected, priorities.get(item.priority, 99)))

        selected: list[ContextItem] = []
        excluded: list[ProvenanceRef] = []
        used = 0
        dropped: list[ProvenanceRef] = []
        for candidate in ordered:
            text = candidate.text
            compressed = False
            cost = self.estimate_tokens(text)
            if cost + used > available and candidate.compressed_text:
                text = candidate.compressed_text
                cost = self.estimate_tokens(text)
                compressed = True
            if cost + used <= available:
                selected.append(
                    ContextItem(
                        ref=candidate.ref,
                        text=text,
                        priority=candidate.priority,
                        protected=candidate.protected,
                        compressed=compressed,
                    )
                )
                used += cost
                continue
            if candidate.protected:
                raise ContextBuildError(
                    f"protected context cannot fit budget: {candidate.ref.ref_id}"
                )
            excluded.append(candidate.ref)
            dropped.append(candidate.ref)

        return ContextManifest(
            project_id=project_id,
            task=task,
            selected=tuple(selected),
            excluded=tuple(excluded),
            dropped_refs=tuple(dropped),
            truncated=bool(dropped),
            estimated_tokens=used,
        )


__all__ = [
    "ContextBudget",
    "ContextBuildError",
    "ContextCandidate",
    "CreativeContextCompiler",
]
