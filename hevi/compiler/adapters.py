"""Transport-only provider adapter contract.

The compiler never calls this interface.  Runtime implementations call it
after persisting an immutable ExecutionPlan/TaskEnvelope.
"""

from __future__ import annotations

from typing import Any, Protocol


class ProviderAdapter(Protocol):
    async def send(self, request: dict[str, Any], *, idempotency_key: str) -> str: ...

    async def poll(self, provider_job_id: str) -> dict[str, Any]: ...

    async def cancel(self, provider_job_id: str) -> None: ...

    async def download(self, provider_job_id: str, destination: str) -> str: ...

    def parse_error(self, error: Exception) -> dict[str, Any]: ...


__all__ = ["ProviderAdapter"]
