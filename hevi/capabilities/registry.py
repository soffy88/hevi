"""Unified Hevi capability registry (CAPABILITY_CONTRACT v1).

Every product line (zero, talkcraft, shortdrama, artmotion, explainer,
ShotSpec工作台 ...) must call generative capabilities by name through this
registry — no private per-line entry points.  Capabilities are CPU-only,
deterministic per seed, and never fake success.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = __import__("logging").getLogger(__name__)


class CapabilityError(RuntimeError):
    """Raised by a capability when rendering truly fails — never a fake success."""


@dataclass
class CapabilityResult:
    mp4: str | None = None
    png: str | None = None
    wav: str | None = None
    duration_s: float | None = None
    sha256: str | None = None
    qa: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mp4": self.mp4,
            "png": self.png,
            "wav": self.wav,
            "duration_s": self.duration_s,
            "sha256": self.sha256,
            "qa": self.qa,
        }


@dataclass
class Capability:
    name: str
    kind: str  # shot | overlay | transition | audio | title | line
    aspects: list[str]
    params_schema: dict[str, Any]
    cpu_cost_hint: float
    render: Any  # Callable[[params, out_dir, *, duration, aspect, seed], CapabilityResult]
    description: str = ""

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            import jsonschema  # local import keeps registry dependency-light
        except ImportError as e:  # pragma: no cover
            raise CapabilityError("jsonschema is required to validate capability params") from e
        try:
            jsonschema.validate(instance=params, schema=self.params_schema)
        except Exception as e:  # jsonschema.ValidationError
            raise CapabilityError(f"参数不满足 {self.name} 的 schema: {e}") from e
        return params

    def __post_init__(self) -> None:
        raw_render = self.render

        def _wrapped(
            params: dict[str, Any],
            out_dir: str | Path,
            *,
            duration: float = 5.0,
            aspect: str = "9:16",
            seed: int = 42,
        ) -> CapabilityResult:
            self.validate_params(params)
            res = raw_render(params, Path(out_dir), duration=duration, aspect=aspect, seed=seed)
            if not isinstance(res, CapabilityResult):
                raise CapabilityError(f"{self.name} render 必须返回 CapabilityResult")
            return res

        self.render = _wrapped
        self.render_safe = _wrapped


_REGISTRY: dict[str, Capability] = {}


def register(capability: Capability) -> None:
    if not isinstance(capability, Capability):
        raise TypeError("register() expects a Capability dataclass instance")
    _REGISTRY[capability.name] = capability
    logger.info("Registered capability: %s (kind=%s aspects=%s)", capability.name, capability.kind, capability.aspects)


def get(name: str) -> Capability:
    if name not in _REGISTRY:
        raise CapabilityError(f"未注册的能力: {name}")
    return _REGISTRY[name]


def list(kind: str | None = None, aspect: str | None = None) -> list[Capability]:
    caps = [*_REGISTRY.values()]
    if kind is not None:
        caps = [c for c in caps if c.kind == kind]
    if aspect is not None:
        caps = [c for c in caps if aspect in c.aspects]
    return caps


list_caps = list


def describe() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in _REGISTRY.values():
        out.append({
            "name": c.name,
            "kind": c.kind,
            "aspects": c.aspects,
            "cpu_cost_hint": c.cpu_cost_hint,
            "params_schema": c.params_schema,
            "description": c.description,
        })
    return out
