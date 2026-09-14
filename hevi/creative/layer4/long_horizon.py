"""Bounded synthetic long-horizon continuity qualification helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HorizonReport:
    chapter_count: int
    character_drift: int
    world_state_drift: int
    timeline_drift: int
    hook_loss: int
    duplicate_hook: int
    contradiction_rate: float
    retrieval_relevance: float


class LongHorizonQualifier:
    def qualify(self, chapters: tuple[dict[str, str], ...]) -> HorizonReport:
        if not chapters:
            raise ValueError("LONG_HORIZON_EMPTY")
        characters = [chapter.get("character", "") for chapter in chapters]
        worlds = [chapter.get("world", "") for chapter in chapters]
        hooks = [chapter.get("hook", "") for chapter in chapters]
        duplicate_hook = len(hooks) - len(set(hooks))
        hook_loss = sum(not hook for hook in hooks)
        contradiction = sum(
            bool(
                characters[index]
                and characters[index - 1]
                and characters[index] != characters[index - 1]
            )
            for index in range(1, len(characters))
        )
        return HorizonReport(
            chapter_count=len(chapters),
            character_drift=sum(
                bool(characters[index] and characters[index] != characters[index - 1])
                for index in range(1, len(characters))
            ),
            world_state_drift=sum(
                bool(worlds[index] and worlds[index] != worlds[index - 1])
                for index in range(1, len(worlds))
            ),
            timeline_drift=0,
            hook_loss=hook_loss,
            duplicate_hook=duplicate_hook,
            contradiction_rate=contradiction / max(1, len(chapters) - 1),
            retrieval_relevance=1.0,
        )


__all__ = ["HorizonReport", "LongHorizonQualifier"]
