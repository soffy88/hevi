"""Operational provider configuration and health endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from hevi.provider_policy.runtime import inspect_providers, runtime_provider_ids

router = APIRouter(prefix="/providers", tags=["providers"])


@router.get("/status")
async def provider_status(
    probe: bool = Query(default=True),
    provider: list[str] | None = Query(default=None),  # noqa: B008
) -> dict[str, Any]:
    """Return redacted provider configuration and real reachability state."""

    requested = provider or list(runtime_provider_ids())
    unknown = sorted(set(requested) - set(runtime_provider_ids()))
    if unknown:
        return {
            "status": "invalid_request",
            "providers": [],
            "unknown_providers": unknown,
        }
    items = await inspect_providers(provider_ids=requested, probe=probe)
    if probe:
        status = "ready" if all(item["ready"] for item in items) else "degraded"
    else:
        status = (
            "configured"
            if all(item["configured"] for item in items)
            else "degraded"
        )
    return {
        "status": status,
        "probe": probe,
        "providers": items,
    }


__all__ = ["provider_status", "router"]
