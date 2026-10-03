"""P10c adapters: bridges to existing systems only (no re-implementation)."""

from __future__ import annotations

from hevi.cinematic.shot_intelligence.models import BeatCue


def link_beatcue(*, cue_id: str, creative_ref: str, time_s: float,
                 kind: str = "beat", strength: float = 1.0) -> BeatCue:
    """CreativeCue -> BeatCue (one of possibly many). Carries both ids."""
    return BeatCue(time_s=time_s, kind=kind, strength=strength,
                   cue_id=cue_id, creative_cue_ref=creative_ref)


def is_directed(cue: BeatCue) -> bool:
    """No creative_cue_ref = legacy: legal, but Compliance marks UNDIRECTED."""
    return bool(cue.creative_cue_ref)
