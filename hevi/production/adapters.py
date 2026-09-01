"""Application-owned production adapter registry.

TaskService owns persistence and scheduling.  The application composition root
injects product adapters here; this module never imports API routers.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Protocol


class ProductionAdapter(Protocol):
    async def __call__(self, task: dict[str, Any], pool: Any) -> dict[str, Any]: ...


class ProductionAdapterRegistry:
    """Explicit source → injected application adapter mapping."""

    def __init__(self) -> None:
        self._targets: dict[str, ProductionAdapter] = {}

    def register(self, source: str, target: ProductionAdapter, *, replace: bool = False) -> None:
        if source in self._targets and not replace:
            raise ValueError(f"production adapter already registered: {source}")
        self._targets[source] = target

    def sources(self) -> tuple[str, ...]:
        return tuple(sorted(self._targets))

    def resolve(self, source: str) -> ProductionAdapter:
        target = self._targets.get(source)
        if target is None:
            raise ValueError(f"Unsupported adapter production source: {source}")
        return target

    async def execute(self, task: dict[str, Any], pool: Any) -> dict[str, Any]:
        source = str((task.get("config_json") or {}).get("production_source", ""))
        result = self.resolve(source)(task, pool)
        if isinstance(result, Awaitable):
            return await result
        raise RuntimeError(f"Production adapter returned non-awaitable result: {source}")


_DEFAULT = ProductionAdapterRegistry()


def _register_builtin_adapters() -> None:
    async def execute_checkpoint(task: dict[str, Any], pool: Any) -> dict[str, Any]:
        from hevi.execution.resumable_render import execute_checkpoint_render

        return await execute_checkpoint_render(task, pool)

    async def execute_clip_video(task: dict[str, Any], pool: Any) -> dict[str, Any]:
        from hevi.production.media_workflows import execute_clip_video_task

        return await execute_clip_video_task(task, pool)

    async def execute_localize_video(task: dict[str, Any], pool: Any) -> dict[str, Any]:
        from hevi.production.media_workflows import execute_video_localize_task

        return await execute_video_localize_task(task, pool)

    async def execute_mpt(task: dict[str, Any], pool: Any) -> dict[str, Any]:
        from hevi.services.mpt_adapter import execute_mpt_task

        return await execute_mpt_task(task, pool)

    async def execute_lot(task: dict[str, Any], pool: Any) -> dict[str, Any]:
        from hevi.studio.slate import execute_lot_task

        return await execute_lot_task(task, pool)

    _DEFAULT.register("checkpoint_render", execute_checkpoint, replace=True)
    _DEFAULT.register("clip_video", execute_clip_video, replace=True)
    _DEFAULT.register("localize_video", execute_localize_video, replace=True)
    _DEFAULT.register("mpt", execute_mpt, replace=True)
    _DEFAULT.register("lot", execute_lot, replace=True)


_register_builtin_adapters()


def default_production_adapters() -> ProductionAdapterRegistry:
    """Return the application-configured registry without importing routers."""
    return _DEFAULT


def configure_default_adapters(**adapters: ProductionAdapter) -> ProductionAdapterRegistry:
    """Inject adapters at process composition time.

    Reconfiguration is intentional for tests and application reloads.  Existing
    task bindings stay immutable; this only selects the adapter for newly run
    process instances.
    """
    for source, adapter in adapters.items():
        _DEFAULT.register(source, adapter, replace=True)
    return _DEFAULT
