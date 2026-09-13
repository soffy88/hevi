"""Deterministic rhythm-role projection, never a claim of visual semantics."""

from __future__ import annotations

from .models import RhythmRole, ShotRhythm


def rhythm_for_position(index: int, total: int, duration_ms: int) -> ShotRhythm:
    if total <= 1 or index == 0:
        role = RhythmRole.HOOK
    elif index == total - 1:
        role = RhythmRole.CLOSE
    elif index < max(2, total // 3):
        role = RhythmRole.SETUP
    elif index >= (total * 2) // 3:
        role = RhythmRole.PAYOFF
    else:
        role = RhythmRole.BUILD
    return ShotRhythm(role=role, reason=f"position={index + 1}/{total};duration_ms={duration_ms}")
