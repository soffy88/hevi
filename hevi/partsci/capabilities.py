"""Unified capability registrations for Particle Science (PARTSCI-R1)."""

from __future__ import annotations

from typing import Any
from hevi.capabilities import Capability, register
from .renderer import render_partsci_scene


def register_partsci_capabilities_once() -> None:
    register(Capability(
        name="particle_text",
        kind="shot",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "concept": {"type": "string"},
                "theme": {"type": "string"},
                "keyword": {"type": "string", "maxLength": 4},
                "narration": {"type": "string"},
                "mechanism": {"type": "string"},
                "seed": {"type": "integer"}
            },
            "required": ["concept", "keyword"]
        },
        cpu_cost_hint=1.2,
        render=render_partsci_scene,
        description="文字粒子化科普动画（确定性 Canvas 2D + 确定性 PRNG）",
        line="partsci"
    ))

    register(Capability(
        name="particle_science_scene",
        kind="shot",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "concept": {"type": "string"},
                "theme": {"type": "string"},
                "keyword": {"type": "string", "maxLength": 4},
                "narration": {"type": "string"},
                "mechanism": {"type": "string"},
                "seed": {"type": "integer"}
            },
            "required": ["concept"]
        },
        cpu_cost_hint=1.5,
        render=render_partsci_scene,
        description="儿童科普场景粒子动画（六层视差构图 + 语义配色）",
        line="partsci"
    ))

    register(Capability(
        name="parallax_layers",
        kind="shot",
        aspects=["16:9", "9:16"],
        params_schema={
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "concept": {"type": "string"},
                "theme": {"type": "string"},
                "keyword": {"type": "string", "maxLength": 4},
                "seed": {"type": "integer"}
            },
            "required": ["concept"]
        },
        cpu_cost_hint=1.0,
        render=render_partsci_scene,
        description="六层视差构图系统（远景/中远/主体/前景/粒子/字幕层）",
        line="partsci"
    ))


__all__ = ["register_partsci_capabilities_once"]
