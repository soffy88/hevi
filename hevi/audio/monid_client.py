"""Monid REST client for hevi providers (stdlib only, no CLI dependency).

Uses the Monid API directly (https://api.monid.ai): create a run with
``POST /v1/run {provider, endpoint, input}`` and poll
``GET /v1/runs/{id}`` until a terminal status.

Auth: ``MONID_API_KEY`` env (Bearer). Base URL: ``MONID_API_BASE`` env.
Never logs the key.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TERMINAL = {"COMPLETED", "FAILED", "BLOCKED", "STOPPED", "TIMED_OUT"}


class MonidError(RuntimeError):
    """Raised when a Monid run fails, is blocked, or cannot be reached."""


def _api_base() -> str:
    return os.environ.get("MONID_API_BASE", "https://api.monid.ai").rstrip("/")


def _api_key() -> str:
    key = os.environ.get("MONID_API_KEY", "").strip()
    if not key:
        raise MonidError(
            "MONID_API_KEY is not set; configure Soffy's Monid API key to use Monid-backed providers."
        )
    return key


def _request_json(method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    url = f"{_api_base()}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
            "X-Monid-Client": "hevi",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:  # noqa: BLE001 - fail loud with context
        raise MonidError(f"Monid API request failed ({method} {path}): {exc}") from exc


def _run_status(detail: dict[str, Any]) -> str:
    return str(detail.get("status", "")).upper()


def _run_output(detail: dict[str, Any]) -> dict[str, Any]:
    output = detail.get("output")
    if isinstance(output, dict):
        return output
    return detail


def _run_cost(detail: dict[str, Any]) -> float | None:
    cost = detail.get("cost")
    if isinstance(cost, dict):
        value = cost.get("value")
    else:
        value = cost
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _raise_if_terminal_failure(run_id: str, detail: dict[str, Any]) -> None:
    status = _run_status(detail)
    if status in {"FAILED", "STOPPED", "TIMED_OUT"}:
        raise MonidError(f"Monid run {run_id} ended with status {status}: {str(detail)[:500]}")
    if status == "BLOCKED":
        controls = detail.get("controls", [])
        raise MonidError(
            f"Monid run {run_id} BLOCKED by workspace control: {controls}. "
            "Adjust controls at https://app.monid.ai before retrying."
        )


async def run_endpoint(
    provider: str,
    endpoint: str,
    *,
    body: dict[str, Any] | None = None,
    query_params: dict[str, Any] | None = None,
    path_params: dict[str, Any] | None = None,
    timeout_s: float = 300.0,
    poll_interval_s: float = 5.0,
) -> tuple[dict[str, Any], float | None]:
    """Run a Monid endpoint, polling until completion.

    Returns (output, cost). Raises MonidError on failure/block/timeout.
    """
    payload: dict[str, Any] = {"provider": provider, "endpoint": endpoint}
    input_obj: dict[str, Any] = {}
    if body:
        input_obj["body"] = body
    if query_params:
        input_obj["queryParams"] = query_params
    if path_params:
        input_obj["pathParams"] = path_params
    if input_obj:
        payload["input"] = input_obj

    created = await asyncio.to_thread(_request_json, "POST", "/v1/run", payload)
    run_id = str(created.get("runId") or created.get("id") or "")
    if not run_id:
        raise MonidError(f"Monid did not return a run id: {str(created)[:300]}")
    detail = created
    if _run_status(detail) not in _TERMINAL:
        waited = 0.0
        while True:
            await asyncio.sleep(poll_interval_s)
            waited += poll_interval_s
            detail = await asyncio.to_thread(
                _request_json, "GET", f"/v1/runs/{run_id}", None
            )
            status = _run_status(detail)
            if status in _TERMINAL:
                break
            if waited >= timeout_s:
                raise MonidError(f"Monid run {run_id} timed out after {timeout_s}s")
    _raise_if_terminal_failure(run_id, detail)
    return _run_output(detail), _run_cost(detail)


async def sfs_public_url(path: str, *, ttl: str = "1d") -> str:
    """Mint a public HTTPS URL for an already-uploaded sfs path."""
    output, _ = await run_endpoint(
        "sfs", "/cat", body={"path": path, "ttl": ttl}, timeout_s=60.0
    )
    url = output.get("url")
    if not url:
        raise MonidError(f"sfs /cat did not return a url: {str(output)[:300]}")
    return str(url)


async def sfs_upload_file(local_path: Path, *, sfs_path: str, ttl: str = "1d") -> str:
    """Upload a local file to sfs and return a public HTTPS URL for it."""
    size_bytes = local_path.stat().st_size
    output, _ = await run_endpoint(
        "sfs",
        "/put",
        body={"path": sfs_path, "sizeBytes": size_bytes},
        timeout_s=60.0,
    )
    upload_url = output.get("uploadUrl")
    if not upload_url:
        raise MonidError(f"sfs /put did not return an uploadUrl: {str(output)[:300]}")

    def _put() -> None:
        req = urllib.request.Request(str(upload_url), method="PUT", data=local_path.read_bytes())
        with urllib.request.urlopen(req, timeout=120) as resp:
            if resp.status not in (200, 201, 204):
                raise MonidError(f"sfs upload failed with HTTP {resp.status}")

    await asyncio.to_thread(_put)
    return await sfs_public_url(sfs_path, ttl=ttl)
