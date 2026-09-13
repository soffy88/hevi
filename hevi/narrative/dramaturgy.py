"""Flexible dramaturgy planning; no mandatory act structure."""

from __future__ import annotations

from dataclasses import dataclass

from hevi.narrative.models import StoryBeat, StoryBible


@dataclass(frozen=True)
class DramaturgyPlan:
    architecture: str
    premise: str
    dramatic_question: str
    protagonist_goal: str
    central_conflict: str
    stakes: str
    beats: tuple[StoryBeat, ...] = ()
    turning_points: tuple[str, ...] = ()
    climax: str = ""
    resolution: str = ""


def plan_dramaturgy(bible: StoryBible, architecture: str = "CUSTOM", beats: tuple[StoryBeat, ...] = ()) -> DramaturgyPlan:
    return DramaturgyPlan(
        architecture=architecture,
        premise=bible.premise.text if bible.premise else "",
        dramatic_question=bible.dramatic_question.text if bible.dramatic_question else "",
        protagonist_goal=beats[0].purpose if beats else "",
        central_conflict=beats[0].conflict if beats else "",
        stakes=beats[0].change if beats else "",
        beats=beats,
        turning_points=tuple(beat.id for beat in beats if beat.change),
        climax=beats[-1].payoff if beats else "",
        resolution=beats[-1].change if beats else "",
    )
