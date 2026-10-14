"""Hevi unified capability registry per CAPABILITY_CONTRACT.md.

Allows any line (zero line, talkcraft, short drama, artmotion, explainer, ShotSpec)
to discover and invoke capabilities by name without private entry points.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..manga.common import sha256_file


class CapabilityError(RuntimeError):
    """Raised when capability parameters fail validation or rendering fails."""


@dataclass
class CapabilityResult:
    """Outcome of invoking Capability.render()."""

    mp4: str | None = None
    png: str | None = None
    wav: str | None = None
    duration: float = 0.0
    sha256: str = ""
    qa: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mp4": self.mp4,
            "png": self.png,
            "wav": self.wav,
            "duration": self.duration,
            "sha256": self.sha256,
            "qa": self.qa,
        }


def _validate_json_schema(data: Any, schema: dict[str, Any], path: str = "params") -> None:
    """Lightweight, zero-dependency JSON schema validator."""
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(data, dict):
            raise CapabilityError(f"{path}: expected object/dict, got {type(data).__name__}")
        required = schema.get("required", [])
        for req in required:
            if req not in data:
                raise CapabilityError(f"{path}: missing required property {req!r}")
        props = schema.get("properties", {})
        for k, v in data.items():
            if k in props:
                _validate_json_schema(v, props[k], f"{path}.{k}")
    elif expected_type == "string":
        if not isinstance(data, str):
            raise CapabilityError(f"{path}: expected string, got {type(data).__name__}")
        enum_vals = schema.get("enum")
        if enum_vals is not None and data not in enum_vals:
            raise CapabilityError(f"{path}: value {data!r} not in enum {enum_vals}")
    elif expected_type in ("number", "integer"):
        if not isinstance(data, (int, float)) or isinstance(data, bool):
            raise CapabilityError(f"{path}: expected {expected_type}, got {type(data).__name__}")
        if "minimum" in schema and data < schema["minimum"]:
            raise CapabilityError(f"{path}: {data} is less than minimum {schema['minimum']}")
        if "maximum" in schema and data > schema["maximum"]:
            raise CapabilityError(f"{path}: {data} is greater than maximum {schema['maximum']}")
    elif expected_type == "boolean":
        if not isinstance(data, bool):
            raise CapabilityError(f"{path}: expected boolean, got {type(data).__name__}")
    elif expected_type == "array":
        if not isinstance(data, list):
            raise CapabilityError(f"{path}: expected list, got {type(data).__name__}")
        items_schema = schema.get("items")
        if items_schema:
            for idx, item in enumerate(data):
                _validate_json_schema(item, items_schema, f"{path}[{idx}]")


@dataclass
class Capability:
    name: str
    kind: str                         # shot | overlay | transition | audio | title | line
    aspects: list[str]                # e.g. ["16:9", "9:16"]
    params_schema: dict[str, Any]
    cpu_cost_hint: float
    render_fn: Callable[..., CapabilityResult]

    def validate_params(self, params: dict[str, Any]) -> None:
        """Validate caller's params dict against params_schema. Raises CapabilityError."""
        _validate_json_schema(params, self.params_schema)

    def render(
        self,
        params: dict[str, Any],
        out_dir: str | Path,
        *,
        duration: float = 2.0,
        aspect: str = "16:9",
        seed: str = "default",
    ) -> CapabilityResult:
        self.validate_params(params)
        out_p = Path(out_dir)
        out_p.mkdir(parents=True, exist_ok=True)
        try:
            return self.render_fn(params, out_p, duration=duration, aspect=aspect, seed=seed)
        except Exception as e:
            if isinstance(e, CapabilityError):
                raise
            raise CapabilityError(f"Capability {self.name} render failed: {e}") from e


_REGISTRY: dict[str, Capability] = {}


def register(cap: Capability) -> None:
    _REGISTRY[cap.name] = cap


def get(name: str) -> Capability:
    if name not in _REGISTRY:
        # Try auto-registering standard capabilities if empty
        _ensure_standard_capabilities_registered()
    if name not in _REGISTRY:
        raise KeyError(f"Capability {name!r} not found in registry (available: {list(_REGISTRY)})")
    return _REGISTRY[name]


def list_capabilities(kind: str | None = None, aspect: str | None = None) -> list[Capability]:
    _ensure_standard_capabilities_registered()
    results = [c for c in _REGISTRY.values()]
    if kind:
        results = [c for c in results if c.kind == kind]
    if aspect:
        results = [c for c in results if aspect in c.aspects]
    return results


# Alias for contract list(...)
list = list_capabilities


_ENSURED = False

def _ensure_standard_capabilities_registered() -> None:
    global _ENSURED
    if _ENSURED:
        return
    _ENSURED = True
    if "manga.name_layout" not in _REGISTRY:
        from ..manga.capabilities import register_manga_capabilities
        register_manga_capabilities()
