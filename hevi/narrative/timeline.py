"""Ordered narrative timeline."""

from __future__ import annotations

from hevi.narrative.models import StoryBible, TimelineEvent


class NarrativeTimeline:
    def __init__(self, events: tuple[TimelineEvent, ...] = ()) -> None:
        self.events = tuple(sorted(events, key=lambda event: event.order))

    def validate(self) -> list[str]:
        errors: list[str] = []
        orders = [event.order for event in self.events]
        if len(orders) != len(set(orders)):
            errors.append("TEMPORAL_CONFLICT")
        return errors

    def for_bible(self, bible: StoryBible) -> NarrativeTimeline:
        return NarrativeTimeline(bible.timeline)
