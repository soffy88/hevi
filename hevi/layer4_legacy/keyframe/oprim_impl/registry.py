"""Keyframe engine registry and resolution.

3O Pillar: oprim.keyframe_registry
"""

from __future__ import annotations

import os
from typing import Any

from hevi.layer4_legacy.keyframe.oprim_impl.cloud_stub_engine import CloudStubKeyframeEngine
from hevi.layer4_legacy.keyframe.oprim_impl.contracts import KeyframeEngine
from hevi.layer4_legacy.keyframe.oprim_impl.fake_engine import FakeKeyframeEngine
from hevi.layer4_legacy.keyframe.oprim_impl.sdturbo_engine import (
    SDTurboCPUEngine,
    SDXLTurboCPUEngine,
)

_REGISTRY: dict[str, type[KeyframeEngine] | KeyframeEngine] = {
    "sdturbo_cpu": SDTurboCPUEngine,
    "cloud_stub": CloudStubKeyframeEngine,
    "fake": FakeKeyframeEngine,
    "sdxlturbo_cpu": SDXLTurboCPUEngine,
}


def register_engine(name: str, *, engine: type[KeyframeEngine] | KeyframeEngine) -> None:
    """Register a custom keyframe engine."""
    _REGISTRY[name] = engine


def get_engine(name: str) -> KeyframeEngine:
    """Instantiate or retrieve the registered engine by name."""
    if name not in _REGISTRY:
        raise KeyError(f"Unknown keyframe engine: '{name}'. Available: {list(_REGISTRY.keys())}")
    target = _REGISTRY[name]
    if isinstance(target, type):
        if hasattr(target, "get_instance"):
            return target.get_instance()  # type: ignore[no-any-return]
        return target()
    return target


def resolve_keyframe_engine(config: Any = None) -> KeyframeEngine:
    """Resolve keyframe engine from config, environment, or default ('sdturbo_cpu').

    Args:
        config: Optional string engine name or dict with 'engine' key.
    """
    engine_name: str | None = None
    if isinstance(config, str):
        engine_name = config
    elif isinstance(config, dict):
        engine_name = config.get("engine") or config.get("keyframe_engine")
    elif hasattr(config, "engine"):
        engine_name = getattr(config, "engine")

    if not engine_name:
        engine_name = os.environ.get("HEVI_KEYFRAME_ENGINE", "sdturbo_cpu")

    return get_engine(engine_name)
