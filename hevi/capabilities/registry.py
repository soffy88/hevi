"""Hevi unified capability registry.

Every product line (zero, talkcraft, shortdrama, artmotion, explainer, ShotSpec
workbench, …) can resolve and invoke a capability by name through
``hevi.capabilities.get(name).render(...)``.  Capabilities must never expose a
private entry point that bypasses this registry.

See CAPABILITY_CONTRACT.md for the authoritative interface contract.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class CapabilityError(RuntimeError):
    """Raised when a capability cannot be resolved, validated or rendered.

    A capability must never return a fake success; failures are explicit.
    """


@dataclass(frozen=True)
class CapabilityResult:
    """Verified output of a capability render."""

    mp4: Path | None = None
    png: Path | None = None
    wav: Path | None = None
    duration: float | None = None
    sha256: str | None = None
    qa_report: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Capability:
    """A registerable production capability.

    ``render`` must be deterministic for a given ``seed`` and must raise
    ``CapabilityError`` on any failure instead of returning a fabricated result.
    """

    name: str
    kind: str  # shot | overlay | transition | audio | title | line
    aspects: tuple[str, ...]
    params_schema: dict[str, Any]
    cpu_cost_hint: float
    render: Callable[..., CapabilityResult]
    description: str = ""

    def __post_init__(self) -> None:
        """Enforce the shared contract at every registry render entrypoint."""
        original_render = self.render

        def validated_render(
            params: dict[str, Any],
            out_dir: str | Path,
            *,
            duration: float = 0.0,
            aspect: str = "16:9",
            seed: int = 0,
        ) -> CapabilityResult:
            clean = self.validate_params(params)
            if aspect not in self.aspects:
                raise CapabilityError(f"unsupported aspect for {self.name}: {aspect}")
            try:
                requested_duration = float(duration)
                requested_seed = int(seed)
            except (TypeError, ValueError, OverflowError) as exc:
                raise CapabilityError("duration must be finite and non-negative; seed must be an integer") from exc
            if not math.isfinite(requested_duration) or requested_duration < 0:
                raise CapabilityError("duration must be finite and non-negative")
            try:
                result = original_render(
                    clean,
                    Path(out_dir),
                    duration=requested_duration,
                    aspect=aspect,
                    seed=requested_seed,
                )
            except CapabilityError:
                raise
            except Exception as exc:
                raise CapabilityError(
                    f"{self.name} render failed: {type(exc).__name__}: {exc}"
                ) from exc
            if not isinstance(result, CapabilityResult):
                raise CapabilityError(f"{self.name} returned an invalid result type")
            for field_name in ("mp4", "png", "wav"):
                artifact = getattr(result, field_name)
                if artifact is not None and not Path(artifact).is_file():
                    raise CapabilityError(f"{self.name} artifact missing after render: {artifact}")
            return result

        object.__setattr__(self, "render", validated_render)

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate ``params`` against the declared JSON schema (jsonschema if present)."""
        if not isinstance(params, dict):
            raise CapabilityError("params must be a JSON object")
        schema = self.params_schema or {}
        # Lightweight structural check that works without jsonschema.
        required = schema.get("required", [])
        props = schema.get("properties", {})
        enum = {k: v.get("enum") for k, v in props.items() if "enum" in v}
        additional = schema.get("additionalProperties", True)
        cleaned: dict[str, Any] = {}
        for key, value in params.items():
            if key not in props and additional is False:
                raise CapabilityError(f"unknown parameter: {key}")
            cleaned[key] = value
        for key in required:
            if key not in cleaned or cleaned[key] is None:
                raise CapabilityError(f"missing required parameter: {key}")
        for key, allowed in enum.items():
            if key in cleaned and cleaned[key] not in allowed:
                raise CapabilityError(
                    f"parameter {key}={cleaned[key]!r} not in {allowed}"
                )
        # Optional jsonschema strictness when available.
        try:
            import jsonschema

            jsonschema.validate(instance=cleaned, schema=schema)
        except ImportError:
            pass
        except Exception as exc:
            message = getattr(exc, "message", str(exc))
            raise CapabilityError(f"invalid parameters for {self.name}: {message}") from exc
        return copy.deepcopy(cleaned)

    def list_aspects(self) -> tuple[str, ...]:
        return self.aspects


_REGISTRY: dict[str, Capability] = {}


def register(capability: Capability) -> Capability:
    """Register a capability by name (duplicate names raise)."""
    if capability.name in _REGISTRY:
        raise CapabilityError(f"capability already registered: {capability.name}")
    _REGISTRY[capability.name] = capability
    return capability


def get(name: str) -> Capability:
    """Resolve a capability by name; raise CapabilityError if unknown."""
    if name not in _REGISTRY:
        raise CapabilityError(f"unknown capability: {name}")
    return _REGISTRY[name]


def list(kind: str | None = None, aspect: str | None = None) -> list[Capability]:
    """List registered capabilities, optionally filtered by kind/aspect."""
    out = [c for c in _REGISTRY.values()]
    if kind is not None:
        out = [c for c in out if c.kind == kind]
    if aspect is not None:
        out = [c for c in out if aspect in c.aspects]
    return out


def names() -> list[str]:
    """All registered capability names (stable order)."""
    return sorted(_REGISTRY.keys())
