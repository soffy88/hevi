"""Declarative model/provider routing without a hardcoded provider catalogue."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast


@dataclass(frozen=True)
class Route:
    provider: str
    model: str
    capability: str | None = None
    stage: str | None = None


@dataclass(frozen=True)
class RouteExecution:
    """Effective configuration trace plus the real provider response."""

    provider: str
    model: str
    content: str
    usage: dict[str, int]
    request_id: str | None = None


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

    async def execute(
        self,
        *,
        capability: str,
        messages: Sequence[dict[str, str]],
        stage: str | None = None,
        call_llm: Callable[..., Awaitable[dict[str, Any]]] | None = None,
    ) -> RouteExecution:
        """Resolve the effective route and run it through a real provider.

        ``call_llm`` is an injected provider adapter; when omitted the route's
        provider is looked up in the canonical provider registry.  A route that
        names an unregistered provider fails closed rather than silently using a
        different provider.
        """

        route = self.resolve(capability=capability, stage=stage)
        if call_llm is None:
            from obase.exceptions import ProviderNotFoundError
            from obase.provider_registry import ProviderRegistry

            if not ProviderRegistry.has("llm", route.provider):
                raise ProviderNotFoundError(
                    f"llm provider {route.provider!r} is not registered"
                )
            call_llm = cast(
                Callable[..., Awaitable[dict[str, Any]]],
                ProviderRegistry.get().llm(route.provider),
            )
        raw = await call_llm(messages=list(messages), model=route.model)
        return RouteExecution(
            provider=route.provider,
            model=route.model,
            content=str(raw.get("content", "")),
            usage=dict(raw.get("usage", {})),
            request_id=raw.get("request_id"),
        )


__all__ = ["ModelRouter", "Route", "RouteExecution"]
