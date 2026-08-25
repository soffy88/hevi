"""Turn a RepairDecision into a concrete, scoped execution patch.

The controller decides *whether* to repair and *which* action family to use.
This module is the missing execution half: it consumes that decision, never
invents a second policy, and returns a patch the director/task worker can
apply before the next attempt.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .repair_controller import RepairAction, RepairDecision


class RepairPatch(BaseModel):
    provider_id: str | None = None
    seed: int | None = None
    replace_references: bool = False
    recompile_prompt: bool = False
    regenerate_same_provider: bool = False
    scopes: list[str] = Field(default_factory=list)
    shot_indexes: list[int] = Field(default_factory=list)
    applied: list[RepairAction] = Field(default_factory=list)
    consumed: bool = False

    def config_updates(self) -> dict[str, object]:
        updates: dict[str, object] = {"repair_patch": self.model_dump(mode="json")}
        if self.provider_id:
            updates["video_provider"] = self.provider_id
        if self.seed is not None:
            updates["seed"] = self.seed
        if self.replace_references:
            updates["repair_replace_reference"] = True
        if self.recompile_prompt:
            updates["repair_recompile_prompt"] = True
        return updates


_SHOT_INDEX = re.compile(r"(\d+)")


def scopes_to_shot_indexes(scopes: list[str]) -> list[int]:
    """Extract shot indexes from constraint/evaluation scopes like ``shot:S01``."""

    indexes: list[int] = []
    seen: set[int] = set()
    for scope in scopes:
        match = _SHOT_INDEX.search(scope)
        if match is None:
            continue
        value = int(match.group(1))
        if value in seen:
            continue
        seen.add(value)
        indexes.append(value)
    return indexes


def apply_repair_decision(
    decision: RepairDecision,
    *,
    current_provider: str = "",
    fallback_candidates: list[str] | None = None,
    current_seed: int = 0,
) -> RepairPatch:
    """Compile a controller decision into the next attempt's inputs.

    ``switch_provider`` walks the persisted policy snapshot rather than a
    source-code fallback chain. Missing candidates leave ``provider_id``
    unset so the caller can fail closed or ask for a human review.
    """

    patch = RepairPatch()
    if not decision.should_repair:
        return patch
    patch.consumed = True
    for action in decision.actions:
        patch.applied.append(action)
        if action.scope:
            patch.scopes.append(action.scope)
        if action.kind == "switch_provider":
            candidates = [
                item
                for item in (fallback_candidates or [])
                if item and item != current_provider
            ]
            patch.provider_id = candidates[0] if candidates else None
        elif action.kind == "retry_new_seed":
            patch.seed = int(current_seed) + 1
        elif action.kind == "replace_reference":
            patch.replace_references = True
        elif action.kind == "recompile_prompt":
            patch.recompile_prompt = True
        elif action.kind == "regenerate_same_provider":
            patch.regenerate_same_provider = True
    patch.shot_indexes = scopes_to_shot_indexes(patch.scopes)
    return patch


__all__ = [
    "RepairPatch",
    "apply_repair_decision",
    "scopes_to_shot_indexes",
]
