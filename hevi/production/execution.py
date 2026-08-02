"""HEVI projection bridge for the stateless :mod:`oservi` execution engine.

This module deliberately owns no task, user, billing, or database state.  It
only turns an injected standard ``omodul`` transaction and optional HEVI event
projector into an ``oservi`` run.  ``TaskService`` remains the sole scheduler
and persistence owner.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, cast

from oservi import ProductionExecutionEngine  # type: ignore[import-untyped]

from hevi.production.contracts import ExecutionBinding

Operation = Callable[[dict[str, Any], dict[str, Any], Path], Awaitable[dict[str, Any]]]
EventSink = Callable[[dict[str, Any]], Awaitable[None] | None]


def execution_binding(capability_id: str, *, adapter_version: str = "1") -> ExecutionBinding:
    """Freeze the engine selection when a new HEVI task is created."""
    try:
        engine_version = version("oservi")
    except PackageNotFoundError:
        engine_version = "unknown"
    return ExecutionBinding(
        capability_id=capability_id,
        adapter_version=adapter_version,
        engine_version=engine_version,
    )


async def execute_standard_operation(
    *,
    operation: Operation,
    config: dict[str, Any],
    input_data: dict[str, Any],
    output_dir: Path,
    event_sink: EventSink | None = None,
) -> dict[str, Any]:
    """Run one standard transaction through ``oservi`` without app state."""
    engine = ProductionExecutionEngine(
        operation=operation,
        event_sink=event_sink,
        config=config,
    )
    result = await engine.run(input_data=input_data, output_dir=output_dir)
    return cast(dict[str, Any], result)
