"""
Hevi Capability Registry: Unified registry for all rendering and media capabilities across product lines.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
import os
import subprocess

@dataclass
class CapabilityResult:
    artifact_path: str
    duration: float
    sha256: str
    qa_report: Dict[str, Any]

@dataclass
class Capability:
    name: str
    kind: str  # shot | overlay | transition | audio | title | line
    aspects: List[str]
    params_schema: Dict[str, Any]
    cpu_cost_hint: float  # CPU seconds per second of video
    render_func: Callable[..., CapabilityResult]

    def render(self, params: Dict[str, Any], out_dir: str, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
        # Validate simple required params or schema if needed
        os.makedirs(out_dir, exist_ok=True)
        return self.render_func(params, out_dir, duration=duration, aspect=aspect, seed=seed)

class CapabilityRegistry:
    def __init__(self):
        self._capabilities: Dict[str, Capability] = {}

    def register(self, cap: Capability) -> None:
        self._capabilities[cap.name] = cap

    def get(self, name: str) -> Capability:
        if name not in self._capabilities:
            raise KeyError(f"Capability not found: {name}")
        return self._capabilities[name]

    def list_capabilities(self, kind: Optional[str] = None, aspect: Optional[str] = None) -> List[Capability]:
        results = []
        for cap in self._capabilities.values():
            if kind and cap.kind != kind:
                continue
            if aspect and aspect not in cap.aspects:
                continue
            results.append(cap)
        return results

# Global registry instance
_registry = CapabilityRegistry()

def register(cap: Capability) -> None:
    _registry.register(cap)

def get(name: str) -> Capability:
    return _registry.get(name)

def list_caps(kind: Optional[str] = None, aspect: Optional[str] = None) -> List[Capability]:
    return _registry.list_capabilities(kind, aspect)

# Register default core capabilities
def _render_satori_title(params: Dict[str, Any], out_dir: str, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    from hevi.webrender.satori_resvg import SatoriResvgCardRenderer
    renderer = SatoriResvgCardRenderer()
    title = params.get("title", "Hevi Video")
    subtitle = params.get("subtitle", "Automated Production")
    out_path = os.path.join(out_dir, f"satori_title_{seed}.png")
    renderer.render_card_png(title, subtitle, out_path, aspect=aspect)
    
    import hashlib
    sha = hashlib.sha256(open(out_path, "rb").read()).hexdigest()
    return CapabilityResult(artifact_path=out_path, duration=duration, sha256=sha, qa_report={"status": "ok"})

register(Capability(
    name="satori.title_card",
    kind="title",
    aspects=["16:9", "9:16"],
    params_schema={"type": "object", "properties": {"title": {"type": "string"}, "subtitle": {"type": "string"}} },
    cpu_cost_hint=0.1,
    render_func=_render_satori_title
))
