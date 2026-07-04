"""E3 execution presets — economy / balanced / fast.

A preset bundles the knobs a user shouldn't have to pick individually: which
video/audio provider, which quality profile, which render runtime, and the
ltx2 billing tier. Resolving a preset fills task defaults; explicitly-set task
fields still win (see resolve_preset).

  economy  — local GPU, zero cloud cost (queued, slower). Budget-first.
  balanced — cloud standard quality, cost/speed midpoint (default).
  fast     — cloud high quality, fastest turnaround, highest cost.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "DEFAULT_PRESET",
    "EXECUTION_PRESETS",
    "ExecutionPreset",
    "get_execution_preset",
    "resolve_preset",
]

RenderRuntime = Literal["generative", "code_render", "mixed"]


@dataclass(frozen=True)
class ExecutionPreset:
    name: str
    video_provider: str
    audio_provider: str
    quality_profile: str
    render_runtime: RenderRuntime
    ltx2_tier: str
    description: str


EXECUTION_PRESETS: dict[str, ExecutionPreset] = {
    "economy": ExecutionPreset(
        name="economy",
        video_provider="wan_local",
        audio_provider="edge_tts",
        quality_profile="standard",
        render_runtime="mixed",  # prefer code_render (zero-cost) where applicable
        ltx2_tier="fast",
        description="本地 GPU 零云成本,预算优先(排队较慢)",
    ),
    "balanced": ExecutionPreset(
        name="balanced",
        video_provider="ltx2_cloud",
        audio_provider="edge_tts",
        quality_profile="standard",
        render_runtime="generative",
        ltx2_tier="fast",
        description="云端标准画质,成本与速度均衡(默认)",
    ),
    "fast": ExecutionPreset(
        name="fast",
        video_provider="ltx2_cloud",
        audio_provider="edge_tts",
        quality_profile="high",
        render_runtime="generative",
        ltx2_tier="fast",
        description="云端高画质快速出片,成本最高",
    ),
}

DEFAULT_PRESET = "balanced"


def get_execution_preset(name: str = DEFAULT_PRESET) -> ExecutionPreset:
    if name not in EXECUTION_PRESETS:
        raise ValueError(
            f"Unknown execution preset: {name!r}. Valid: {sorted(EXECUTION_PRESETS)}"
        )
    return EXECUTION_PRESETS[name]


def resolve_preset(
    preset: str | None,
    *,
    video_provider: str | None = None,
    audio_provider: str | None = None,
    quality_profile: str | None = None,
) -> dict[str, str]:
    """Expand a preset into concrete task params; explicit args override the preset.

    Returns a dict with video_provider / audio_provider / quality_profile /
    render_runtime / ltx2_tier. With preset=None, only the explicitly-passed
    fields are returned (no preset defaults applied).
    """
    if preset is None:
        out: dict[str, str] = {}
        if video_provider is not None:
            out["video_provider"] = video_provider
        if audio_provider is not None:
            out["audio_provider"] = audio_provider
        if quality_profile is not None:
            out["quality_profile"] = quality_profile
        return out

    p = get_execution_preset(preset)
    return {
        "video_provider": video_provider or p.video_provider,
        "audio_provider": audio_provider or p.audio_provider,
        "quality_profile": quality_profile or p.quality_profile,
        "render_runtime": p.render_runtime,
        "ltx2_tier": p.ltx2_tier,
    }
