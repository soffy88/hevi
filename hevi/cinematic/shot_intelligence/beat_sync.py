"""Beat-aware planning adapter independent from any renderer."""

from __future__ import annotations

from hevi.cinematic.shot_intelligence.models import BeatCue, ShotPlan


def beat_projection(plan: ShotPlan) -> dict[str, list[dict[str, float | str]]]:
    cues = sorted(plan.beat_cues, key=lambda cue: cue.time_s)
    cuts: list[dict[str, float | str]] = [{"time_s": cue.time_s, "kind": cue.kind} for cue in cues if cue.kind in {"beat", "cut"}]
    emphasis: list[dict[str, float | str]] = [{"time_s": cue.time_s, "kind": cue.kind, "strength": cue.strength} for cue in cues if cue.strength >= 0.8]
    return {"cut_points": cuts, "emphasis_points": emphasis, "transition_points": cuts}


def cues_from_times(times: list[float]) -> tuple[BeatCue, ...]:
    return tuple(BeatCue(time_s=t) for t in times)
