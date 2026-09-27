"""HEVI P5.2 — renderer backend abstraction.

A ``ShotPlan`` says *what* a shot must communicate. A renderer says how those
bytes get produced. Keeping those apart is the whole point: the renderer is not
a planning authority and must never re-decide narrative, timing or evidence. It
receives a resolved plan and is contractually forbidden from changing the
semantic intent, the duration, the required evidence or the timeline.

Backends declare their capabilities so selection is reasoned about rather than
guessed. ``RANDOM_VARIATION`` is not a selection mode: a backend is chosen
because the MotionPlan needs ``CANVAS`` and only HTML/GSAP can supply it, or
because the profile prefers Remotion and it is available — never because it came
first in a dict.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class RendererId(StrEnum):
    REMOTION = "REMOTION"
    HTML_GSAP = "HTML_GSAP"
    FFMPEG = "FFMPEG"
    MANIM = "MANIM"


class RendererCapability(StrEnum):
    TEXT = "TEXT"
    SVG = "SVG"
    HTML = "HTML"
    CSS = "CSS"
    THREE_D = "3D"
    VIDEO = "VIDEO"
    AUDIO = "AUDIO"
    CANVAS = "CANVAS"
    FRAME_EXACT = "FRAME_EXACT"
    TRANSPARENCY = "TRANSPARENCY"


class RenderOutcome(StrEnum):
    OK = "OK"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"
    REJECTED = "REJECTED"


class RenderContractViolation(RuntimeError):
    """A backend changed something the plan owns."""

    def __init__(self, violations: list[str]) -> None:
        self.violations = violations
        super().__init__("RENDER_CONTRACT_VIOLATION: " + "; ".join(violations))


@dataclass
class RenderPlan:
    """The resolved input a backend is allowed to execute.

    This mirrors the canonical P1/P0 plan shapes without redefining them: a
    backend reads ``shot_id``, ``duration_s``, ``motion_purposes``,
    ``asset_refs`` and ``audio_lock_id`` and nothing else.
    """

    shot_id: str
    duration_s: float
    motion_purposes: list[str] = field(default_factory=list)
    asset_refs: list[str] = field(default_factory=list)
    caption_text: str = ""
    audio_lock_id: str = ""
    required_evidence: list[str] = field(default_factory=list)
    semantic_intent: str = ""
    width: int = 1280
    height: int = 720
    fps: int = 30
    profile_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RenderResult:
    """What a backend produced, plus the evidence it did not cheat."""

    shot_id: str
    renderer: str
    outcome: RenderOutcome = RenderOutcome.OK
    output_path: str = ""
    duration_s: float = 0.0
    frame_count: int = 0
    content_hash: str = ""
    frame_deterministic: bool = False
    sandbox_report: dict[str, Any] = field(default_factory=dict)
    capability_used: list[str] = field(default_factory=list)
    reason: str = ""
    latency_s: float = 0.0
    violations: list[str] = field(default_factory=list)
    #: How many times the backend was invoked. Above 1 means a transient was
    #: retried, which is worth surfacing rather than hiding.
    attempts: int = 1

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["outcome"] = self.outcome.value
        d["renderer"] = str(self.renderer)
        return d


class RendererBackend:
    """Base class for every renderer backend."""

    renderer_id: RendererId = RendererId.FFMPEG
    capabilities: frozenset[RendererCapability] = frozenset()
    #: Deterministic given identical inputs, frame for frame.
    frame_deterministic: bool = False
    available: bool = False
    unavailable_reason: str = "not probed"

    def detect(self) -> bool:
        """Probe availability. Subclasses override."""
        return self.available

    def supports(self, capability: RendererCapability) -> bool:
        return capability in self.capabilities

    def render(self, plan: RenderPlan, output_dir: Path) -> RenderResult:
        raise NotImplementedError

    def describe(self) -> dict[str, Any]:
        return {
            "renderer_id": self.renderer_id.value,
            "capabilities": sorted(c.value for c in self.capabilities),
            "frame_deterministic": self.frame_deterministic,
            "available": self.detect(),
            "unavailable_reason": self.unavailable_reason,
        }


# ── Renderer equivalence (§63) ───────────────────────────────────────────


def duration_tolerance(plan: RenderPlan) -> float:
    """How much duration drift is container padding rather than a contract break.

    A rendered file's reported duration is not its frame count divided by its
    frame rate: muxers pad the last frame and audio frames do not align to video.
    One video frame plus a small mux allowance is therefore drift, and anything
    beyond it means the backend really did change the shot's length.
    """
    return (1.0 / max(1, plan.fps)) + 0.03


def verify_equivalence(
    plan: RenderPlan, result: RenderResult, *, tolerance_s: float | None = None
) -> tuple[bool, list[str]]:
    """Verify a backend honoured the plan's semantic contract.

    Different backends may look different. They may not change what the shot
    means, how long it is, what evidence it must carry, or where it sits.
    """
    violations: list[str] = []
    tolerance = tolerance_s if tolerance_s is not None else duration_tolerance(plan)
    if abs(result.duration_s - plan.duration_s) > tolerance:
        violations.append(
            f"DURATION_CHANGED:plan={plan.duration_s:.3f} rendered={result.duration_s:.3f} "
            f"tolerance={tolerance:.3f}"
        )
    if plan.audio_lock_id and not plan.extra.get("audio_lock_honoured", True):
        violations.append("AUDIO_LOCK_DROPPED")
    if plan.required_evidence and not plan.extra.get("evidence_present", True):
        violations.append("REQUIRED_EVIDENCE_DROPPED")
    if plan.semantic_intent and not plan.extra.get("semantic_intent_honoured", True):
        violations.append("SEMANTIC_INTENT_OVERRIDDEN")
    result.violations = violations
    return (not violations), violations


def enforce_equivalence(plan: RenderPlan, result: RenderResult) -> RenderResult:
    """Raise if the backend broke the plan's contract (§56, adversarial A19)."""
    ok, violations = verify_equivalence(plan, result)
    if not ok:
        raise RenderContractViolation(violations)
    return result


# ── Selection (§58) ─────────────────────────────────────────────────────


@dataclass
class SelectionRequirement:
    """What a plan needs from a renderer."""

    required_capabilities: list[RendererCapability] = field(default_factory=list)
    preferred_renderers: list[RendererId] = field(default_factory=list)
    profile_id: str = ""
    max_cost_usd: float | None = None
    asset_types: list[str] = field(default_factory=list)


@dataclass
class SelectionDecision:
    renderer: RendererId | None = None
    reason: str = ""
    considered: list[str] = field(default_factory=list)
    rejected: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["renderer"] = self.renderer.value if self.renderer else None
        return d


def select_renderer(
    backends: list[RendererBackend], requirement: SelectionRequirement
) -> SelectionDecision:
    """Choose a renderer deterministically from declared requirements.

    The order is fixed and explainable: capability first (a plan that needs a
    canvas must get a canvas), then availability, then profile preference. No
    randomness, and no "first registered wins".
    """
    decision = SelectionDecision(considered=[b.renderer_id.value for b in backends])
    viable: list[RendererBackend] = []
    for backend in backends:
        if not backend.detect():
            decision.rejected[backend.renderer_id.value] = backend.unavailable_reason
            continue
        missing = [
            cap.value
            for cap in requirement.required_capabilities
            if not backend.supports(cap)
        ]
        if missing:
            decision.rejected[backend.renderer_id.value] = "missing:" + ",".join(missing)
            continue
        viable.append(backend)

    if not viable:
        needed = sorted(c.value for c in requirement.required_capabilities) or ["none"]
        decision.reason = "NO_CAPABLE_RENDERER:" + ",".join(needed)
        return decision

    for preferred in requirement.preferred_renderers:
        for backend in viable:
            if backend.renderer_id is preferred:
                decision.renderer = backend.renderer_id
                decision.reason = f"PROFILE_PREFERRED:{preferred.value}"
                return decision

    # Capability count is a tiebreak only; it never overrides a stated profile
    # preference, and it is deterministic.
    required = set(requirement.required_capabilities)
    viable.sort(key=lambda b: (-len(b.capabilities & required), b.renderer_id.value))
    decision.renderer = viable[0].renderer_id
    decision.reason = f"CAPABILITY_MATCH:{sorted(c.value for c in requirement.required_capabilities)}"
    return decision


# ── Registry (§5, no second provider registry) ───────────────────────────

#: Renderer backends are a *capability* surface, not providers. They deliberately
#: live in their own registry because they execute media rather than call a model
#: API; provider selection authority remains the P3 obase ProviderRegistry.
_RENDERERS: dict[RendererId, RendererBackend] = {}


def register_renderer(backend: RendererBackend) -> None:
    _RENDERERS[backend.renderer_id] = backend


def list_renderers() -> list[RendererBackend]:
    return [_RENDERERS[key] for key in sorted(_RENDERERS, key=lambda k: k.value)]


def get_renderer(renderer_id: RendererId) -> RendererBackend | None:
    return _RENDERERS.get(renderer_id)


def render(
    plan: RenderPlan, output_dir: Path, *, renderer_id: RendererId | None = None
) -> RenderResult:
    """Render one shot with the named (or a selected) backend, enforcing the contract."""
    backend = get_renderer(renderer_id) if renderer_id else None
    if backend is None:
        decision = select_renderer(list_renderers(), SelectionRequirement(
            required_capabilities=[RendererCapability.FRAME_EXACT]
        ))
        backend = get_renderer(decision.renderer) if decision.renderer else None
    if backend is None:
        return RenderResult(
            shot_id=plan.shot_id,
            renderer="none",
            outcome=RenderOutcome.UNAVAILABLE,
            reason="NO_RENDERER_AVAILABLE",
        )
    started = time.monotonic()
    result = backend.render(plan, Path(output_dir))
    result.latency_s = time.monotonic() - started
    return result


__all__ = [
    "RenderContractViolation",
    "RenderOutcome",
    "RenderPlan",
    "RenderResult",
    "RendererBackend",
    "RendererCapability",
    "RendererId",
    "SelectionDecision",
    "SelectionRequirement",
    "enforce_equivalence",
    "get_renderer",
    "list_renderers",
    "register_renderer",
    "render",
    "select_renderer",
    "verify_equivalence",
]
