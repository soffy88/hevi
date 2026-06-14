from typing import Any

# DURATION_ARCHETYPES maps user-facing duration buckets to internal rendering parameters.
# Note: "45min+" requires segmented rendering + state persistence (handled in P10.D).
DURATION_ARCHETYPES: dict[str, dict[str, Any]] = {
    "short": {"target_s": 5, "clip_s": 5, "max_clips": 1},
    "1-5min": {"target_s": 180, "clip_s": 20, "max_clips": 15},
    "5-15min": {"target_s": 600, "clip_s": 20, "max_clips": 45},
    "15-45min": {"target_s": 1800, "clip_s": 20, "max_clips": 135},
    "45min+": {"target_s": 3600, "clip_s": 20, "max_clips": 270},
}


def get_duration_config(archetype: str) -> dict[str, Any]:
    """Retrieve duration configuration for a given archetype."""
    if archetype not in DURATION_ARCHETYPES:
        raise ValueError(f"Unknown duration archetype: {archetype}")
    return DURATION_ARCHETYPES[archetype]
