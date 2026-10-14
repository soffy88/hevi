"""Hevi capability contract registry (CAPABILITY_CONTRACT.md).

Unified registry for cross-product line visual/audio capabilities (3D, handdraw,
riso, lottie, satori, etc.).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


class CapabilityError(RuntimeError):
    """Raised when capability execution or validation fails."""


@dataclass
class CapabilityResult:
    """Standard execution result returned by Capability.render()."""

    output_path: Path
    duration: float
    sha256: str
    qa: dict[str, Any] = field(default_factory=dict)
    mp4: Path | None = None
    png: Path | None = None
    wav: Path | None = None

    def __post_init__(self) -> None:
        self.output_path = Path(self.output_path)
        if self.mp4 is None and self.output_path.suffix.lower() == ".mp4":
            self.mp4 = self.output_path
        elif self.png is None and self.output_path.suffix.lower() == ".png":
            self.png = self.output_path
        elif self.wav is None and self.output_path.suffix.lower() in (".wav", ".mp3"):
            self.wav = self.output_path


def compute_sha256(path: Path | str) -> str:
    """Compute sha256 checksum of a file."""
    p = Path(path)
    if not p.is_file():
        raise CapabilityError(f"File not found for sha256 computation: {p}")
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Capability:
    """Registered capability definition."""

    name: str
    kind: str  # shot | overlay | transition | audio | title | line
    aspects: list[str]  # e.g. ["16:9", "9:16"]
    params_schema: dict[str, Any]
    cpu_cost_hint: float
    render: Callable[..., CapabilityResult]

    def validate_params(self, params: dict[str, Any]) -> None:
        """Validate input params against JSON schema if jsonschema is available."""
        try:
            import jsonschema  # type: ignore[import-not-found]

            jsonschema.validate(instance=params, schema=self.params_schema)
        except ImportError:
            # Basic validation
            required = self.params_schema.get("required", [])
            for field_name in required:
                if field_name not in params:
                    raise CapabilityError(f"Missing required parameter '{field_name}' for {self.name}")


_REGISTRY: dict[str, Capability] = {}


def register(cap: Capability, *, overwrite: bool = False) -> None:
    """Register a new capability."""
    if not overwrite and cap.name in _REGISTRY:
        raise CapabilityError(f"Capability '{cap.name}' already registered.")
    _REGISTRY[cap.name] = cap


def get(name: str) -> Capability:
    """Retrieve capability by name."""
    if name not in _REGISTRY:
        raise CapabilityError(f"Capability '{name}' not found in registry.")
    return _REGISTRY[name]


def list_capabilities(
    kind: str | None = None,
    aspect: str | None = None,
) -> list[Capability]:
    """List registered capabilities matching optional filters."""
    results = [c for c in _REGISTRY.values()]
    if kind:
        results = [c for c in results if c.kind == kind]
    if aspect:
        results = [c for c in results if aspect in c.aspects]
    return results


# Module-level list alias matching CAPABILITY_CONTRACT.md: `list(kind=..., aspect=...)`
def list(kind: str | None = None, aspect: str | None = None) -> list[Capability]:
    return list_capabilities(kind=kind, aspect=aspect)


def clear_registry() -> None:
    """Clear all registered capabilities (useful for tests)."""
    _REGISTRY.clear()
