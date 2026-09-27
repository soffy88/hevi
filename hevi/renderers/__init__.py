"""HEVI P5.2 — renderer backends.

Registration is explicit and idempotent. Renderer backends are deliberately not
part of the P3 ``ProviderRegistry``: they execute media locally rather than
calling a model API, and folding them into the provider authority would blur the
line between "which model generates" and "how these bytes are produced".
Provider authority stays exactly where P0-P5 put it.
"""

from __future__ import annotations

from hevi.renderers.base import (
    RenderContractViolation,
    RendererBackend,
    RendererCapability,
    RendererId,
    RenderOutcome,
    RenderPlan,
    RenderResult,
    SelectionDecision,
    SelectionRequirement,
    enforce_equivalence,
    get_renderer,
    list_renderers,
    register_renderer,
    render,
    select_renderer,
    verify_equivalence,
)
from hevi.renderers.ffmpeg import FfmpegRenderer, plan_requires_semantic_motion
from hevi.renderers.html_gsap import (
    HtmlGsapRenderer,
    SandboxReport,
    assert_no_unsafe_url,
    assert_sandbox_path,
    scrubbed_environment,
)
from hevi.renderers.remotion import RemotionRenderer, remotion_capability_snapshot

_REGISTERED = False


def register_all_renderers(force: bool = False) -> list[str]:
    """Register the canonical backends. Idempotent."""
    global _REGISTERED
    if _REGISTERED and not force:
        return [backend.renderer_id.value for backend in list_renderers()]
    for backend in (
        RemotionRenderer(),
        HtmlGsapRenderer(),
        FfmpegRenderer(),
    ):
        register_renderer(backend)
    _REGISTERED = True
    return [backend.renderer_id.value for backend in list_renderers()]


def renderer_capability_matrix() -> dict[str, list[str]]:
    """Declared capabilities per backend, for the qualification record."""
    register_all_renderers()
    return {
        backend.renderer_id.value: sorted(c.value for c in backend.capabilities)
        for backend in list_renderers()
    }


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
    "FfmpegRenderer",
    "plan_requires_semantic_motion",
    "HtmlGsapRenderer",
    "SandboxReport",
    "assert_no_unsafe_url",
    "assert_sandbox_path",
    "scrubbed_environment",
    "RemotionRenderer",
    "remotion_capability_snapshot",
    "register_all_renderers",
    "renderer_capability_matrix",
]
