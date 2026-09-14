"""Declarative model/provider routing without a hardcoded provider catalogue."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Route:
    provider: str
    model: str
    capability: str | None = None
    stage: str | None = None


class ModelRouter:
    def __init__(self, default: Route) -> None:
        self.default = default
        self._capability: dict[str, Route] = {}
        self._stage: dict[str, Route] = {}

    def set_capability(self, capability: str, route: Route) -> None:
        self._capability[capability] = route

    def set_stage(self, stage: str, route: Route) -> None:
        self._stage[stage] = route

    def resolve(self, *, capability: str, stage: str | None = None) -> Route:
        if stage and stage in self._stage:
            return self._stage[stage]
        return self._capability.get(capability, self.default)


__all__ = ["ModelRouter", "Route"]
