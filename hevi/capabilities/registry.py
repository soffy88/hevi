"""Hevi unified capability registry.

Every creative capability (3D scene, hand-draw, brand film, lottie/satori/title
card, transition, effect, sfx, short-drama asset, ...) is registered here behind
one interface so any product line (zero line, talkcraft, short-drama, artmotion,
explainer, ShotSpec workbench) can invoke it by name instead of wiring its own
private entry point.

Contract (see CAPABILITY_CONTRACT.md):

  register(Capability(...))
  get(name) -> Capability
  list(kind=..., aspect=...) -> list[Capability]
  Capability.render(params, out_dir, *, duration, aspect, seed) -> CapabilityResult

A capability is reproducible for the same seed. It must raise CapabilityError on
failure and never return a fake success.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


class CapabilityError(Exception):
    """Raised when a capability render fails. Never swallow / fake success."""


@dataclass
class CapabilityResult:
    """Output evidence of a capability render."""

    mp4: str | None = None
    png: str | None = None
    wav: str | None = None
    duration_s: float | None = None
    sha256: str | None = None
    qa_report: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class Capability:
    """A single named, callable creative capability."""

    name: str
    kind: str  # shot | overlay | transition | audio | title | line
    aspects: list[str]
    params_schema: dict[str, Any]
    cpu_cost_hint: float  # approx CPU-seconds per video-second
    render: Callable[..., CapabilityResult]

    def validate_params(self, params: dict[str, Any]) -> None:
        """Lightweight JSON-schema check. Raises ValueError on violation."""
        import jsonschema  # type: ignore

        try:
            jsonschema.validate(params, self.params_schema)
        except ImportError:
            # jsonschema optional in lean environments; fall back to required-keys
            for req in self.params_schema.get("required", []):
                if req not in params:
                    raise ValueError(f"missing required param: {req}")
        except Exception as exc:  # jsonschema.ValidationError
            raise ValueError(f"invalid params for {self.name}: {exc}") from exc


_REGISTRY: dict[str, Capability] = {}


def register(cap: Capability) -> Capability:
    """Register a capability. Re-registration overwrites (last writer wins)."""
    if not isinstance(cap, Capability):
        raise TypeError("register expects a Capability")
    _REGISTRY[cap.name] = cap
    return cap


def get(name: str) -> Capability:
    if name not in _REGISTRY:
        raise KeyError(f"capability not registered: {name}")
    return _REGISTRY[name]


def list(kind: str | None = None, aspect: str | None = None) -> list[Capability]:
    out = list(_REGISTRY.values())
    if kind is not None:
        out = [c for c in out if c.kind == kind]
    if aspect is not None:
        out = [c for c in out if aspect in c.aspects]
    return out


def names() -> list[str]:
    return sorted(_REGISTRY.keys())


def clear() -> None:
    """Test helper: drop all registrations."""
    _REGISTRY.clear()
