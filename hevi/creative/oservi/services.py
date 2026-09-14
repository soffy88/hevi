"""Named HEVI creative service surface over the shared runtime registry."""

from __future__ import annotations

from collections.abc import Callable

from hevi.creative.oservi.registry import CreativeServiceRegistry, ServiceRequest, ServiceResult

CREATIVE_SERVICE_NAMES = (
    "creative.project.create",
    "creative.import",
    "creative.research",
    "narrative.plan",
    "narrative.write",
    "narrative.audit",
    "narrative.revise",
    "narrative.forecast",
    "script.create",
    "storyboard.create",
    "interactive_film.create",
    "play.start",
    "play.step",
    "translation.create",
    "translation.run",
    "cover.create",
    "creative.export",
)


class CreativeServiceSurface:
    """Registration helper; execution remains owned by HEVI runtime callers."""

    def __init__(self, registry: CreativeServiceRegistry | None = None) -> None:
        self.registry = registry or CreativeServiceRegistry()

    def register(self, name: str, handler: Callable[[ServiceRequest], ServiceResult]) -> None:
        if name not in CREATIVE_SERVICE_NAMES:
            raise ValueError(f"unknown creative service: {name}")
        self.registry.register(name, handler)

    def call(self, request: ServiceRequest) -> ServiceResult:
        return self.registry.call(request)


__all__ = ["CREATIVE_SERVICE_NAMES", "CreativeServiceSurface"]
