"""Runtime configuration and reachability checks for external providers.

Configuration and availability are intentionally separate:

* ``configured`` means HEVI has enough information to call a provider;
* ``reachable`` means a real health/API probe succeeded;
* ``ready`` is only true when both are true.

This is the operational counterpart to the truthful production capability
catalog.  It does not print or return secrets and it never treats a provider
URL alone as a healthy service.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


@dataclass(frozen=True)
class ProviderSpec:
    provider_id: str
    name: str
    kind: str
    required_env: tuple[str, ...]
    health_path: str | None
    setup: str
    default_endpoint: str | None = None
    probe_method: str = "GET"


PROVIDER_SPECS: tuple[ProviderSpec, ...] = (
    ProviderSpec(
        "voicebox",
        "Voicebox / HEVI Gen Engine",
        "audio",
        ("VOICEBOX_BASE_URL",),
        "/api/ai/health",
        "启动 hevi-gen-engine/Voicebox，并设置 VOICEBOX_BASE_URL；Compose 会在容器内改写为服务名。",
        default_endpoint="http://127.0.0.1:17600",
    ),
    ProviderSpec(
        "longcat",
        "LongCat-2.0 Agent",
        "llm",
        ("LONGCAT_BASE_URL", "LONGCAT_API_KEY"),
        "/models",
        "设置 LONGCAT_BASE_URL 指向 OpenAI-compatible /v1 服务；LONGCAT_API_KEY 按服务要求填写。",
    ),
    ProviderSpec(
        "joyai",
        "JoyAI causal V2V",
        "video",
        ("JOYAI_STREAM_WS_URL", "JOYAI_BASE_URL"),
        None,
        "设置 JOYAI_STREAM_WS_URL，或设置 JOYAI_BASE_URL + JOYAI_STREAM_WS_PATH，并启动兼容 WebSocket 服务。",
    ),
    ProviderSpec(
        "mpt",
        "MoneyPrinterTurbo",
        "video",
        ("MPT_API_BASE",),
        "/ping",
        "启动 MPT API；本机默认监听 127.0.0.1:8080，生产容器由 Compose 使用 mpt-api:8080。",
        default_endpoint="http://127.0.0.1:8080",
    ),
    ProviderSpec(
        "pexels",
        "Pexels stock media",
        "media",
        ("PEXELS_API_KEY",),
        "/v1/search",
        "设置 PEXELS_API_KEY；HEVI 会检索后下载到本地缓存并保留许可证来源。",
        default_endpoint="https://api.pexels.com",
    ),
    ProviderSpec(
        "duix",
        "Duix digital human",
        "avatar",
        ("DUIX_SERVICE_URL", "DUIX_LIVESTREAM_PATH"),
        "/health",
        "启动 Duix，并设置 DUIX_SERVICE_URL + DUIX_LIVESTREAM_PATH；Provider 必须返回真实 session_id 和 stream_url。",
    ),
    ProviderSpec(
        "pocket_tts",
        "Pocket TTS capability",
        "audio",
        (),
        None,
        "HEVI native/local runtime or optional Pocket TTS weights; a real WAV is required for READY.",
    ),
    ProviderSpec(
        "voxcpm",
        "VoxCPM capability",
        "audio",
        (),
        None,
        "HEVI native/local runtime or optional VoxCPM weights; a real WAV is required for READY.",
    ),
)

_SPECS = {item.provider_id: item for item in PROVIDER_SPECS}


def _value(name: str) -> str:
    return os.getenv(name, "").strip()


def _safe_url(value: str | None) -> str | None:
    """Return an endpoint without credentials or query fragments."""

    if not value:
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.hostname:
        return None
    try:
        netloc = parsed.hostname
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
    except ValueError:
        return None
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))


def _endpoint(provider_id: str) -> tuple[str | None, str]:
    if provider_id == "voicebox":
        value = _value("VOICEBOX_BASE_URL") or _value("GEN_ENGINE_BASE_URL")
        return value or _SPECS[provider_id].default_endpoint, "env" if value else "default"
    if provider_id == "mpt":
        value = _value("MPT_API_BASE")
        return value or _SPECS[provider_id].default_endpoint, "env" if value else "default"
    if provider_id == "pexels":
        return _SPECS[provider_id].default_endpoint, "public_api"
    if provider_id == "joyai":
        value = _value("JOYAI_STREAM_WS_URL") or _value("JOYAI_BASE_URL")
        return value or None, "env"
    value = _value(
        {
            "longcat": "LONGCAT_BASE_URL",
            "duix": "DUIX_SERVICE_URL",
        }.get(provider_id, "")
    )
    return value or None, "env"


def _is_configured(provider_id: str) -> tuple[bool, list[str]]:
    if provider_id in {"pocket_tts", "voxcpm"}:
        return True, []
    if provider_id == "voicebox":
        configured = bool(_value("VOICEBOX_BASE_URL") or _value("GEN_ENGINE_BASE_URL"))
        return configured, [] if configured else ["VOICEBOX_BASE_URL"]
    if provider_id == "joyai":
        configured = bool(_value("JOYAI_STREAM_WS_URL") or _value("JOYAI_BASE_URL"))
        return configured, [] if configured else ["JOYAI_STREAM_WS_URL or JOYAI_BASE_URL"]
    if provider_id == "mpt":
        return True, []  # A deterministic local default is part of the HEVI install.
    if provider_id == "pexels":
        configured = bool(_value("PEXELS_API_KEY"))
        return configured, [] if configured else ["PEXELS_API_KEY"]
    spec = _SPECS[provider_id]
    missing = [name for name in spec.required_env if not _value(name)]
    return not missing, missing


def provider_configuration(provider_id: str | None = None) -> list[dict[str, Any]]:
    """Return non-secret configuration state for one or all providers."""

    specs = (_SPECS[provider_id],) if provider_id else PROVIDER_SPECS
    result: list[dict[str, Any]] = []
    for spec in specs:
        configured, missing = _is_configured(spec.provider_id)
        endpoint, source = _endpoint(spec.provider_id)
        item: dict[str, Any] = {
            "id": spec.provider_id,
            "name": spec.name,
            "kind": spec.kind,
            "configured": configured,
            "configuration_source": source,
            "endpoint": _safe_url(endpoint),
            "missing": missing,
            "setup": spec.setup,
        }
        if spec.provider_id == "joyai":
            item["stream_endpoint"] = _safe_url(stream_endpoint())
            item["health_probe"] = "tcp_or_websocket_required"
        result.append(item)
    return result


def stream_endpoint() -> str:
    """Resolve JoyAI's actual WebSocket endpoint using the same rule as runtime."""

    explicit = _value("JOYAI_STREAM_WS_URL").rstrip("/")
    if explicit:
        return explicit
    base = _value("JOYAI_BASE_URL").rstrip("/")
    if not base:
        return ""
    if base.startswith("https://"):
        base = "wss://" + base.removeprefix("https://")
    elif base.startswith("http://"):
        base = "ws://" + base.removeprefix("http://")
    path = _value("JOYAI_STREAM_WS_PATH") or "/ws/edit"
    return f"{base}/{path.lstrip('/')}"


def _probe_url(spec: ProviderSpec, endpoint: str) -> tuple[str, dict[str, str], dict[str, Any]]:
    path = spec.health_path or ""
    headers: dict[str, str] = {}
    params: dict[str, Any] = {}
    if spec.provider_id == "pexels":
        path = "/v1/search"
        params = {"query": "hevi", "per_page": 1}
        headers["Authorization"] = _value("PEXELS_API_KEY")
    elif spec.provider_id == "mpt" and _value("MPT_API_KEY"):
        headers["x-api-key"] = _value("MPT_API_KEY")
    elif spec.provider_id == "longcat" and _value("LONGCAT_API_KEY"):
        headers["Authorization"] = f"Bearer {_value('LONGCAT_API_KEY')}"
    if not path:
        return endpoint, headers, params
    return f"{endpoint.rstrip('/')}{path}", headers, params


async def probe_provider(
    provider_id: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    """Probe one provider and return a redacted, machine-readable result."""

    if provider_id not in _SPECS:
        raise ValueError(f"unknown runtime provider: {provider_id}")
    spec = _SPECS[provider_id]
    state = provider_configuration(provider_id)[0]
    if not state["configured"]:
        return {**state, "reachable": False, "ready": False, "error": "missing_configuration"}

    endpoint, _ = _endpoint(provider_id)
    if provider_id in {"pocket_tts", "voxcpm"}:
        available = False
        try:
            if provider_id == "pocket_tts":
                from hevi.audio.pocket_tts_service import pocket_tts_available

                available = pocket_tts_available()
            else:
                from hevi.audio.voxcpm_service import voxcpm_available

                available = voxcpm_available()
        except Exception as exc:
            return {
                **state,
                "reachable": False,
                "ready": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        return {
            **state,
            "reachable": available,
            "ready": available,
            "error": None if available else "local_runtime_unavailable",
        }
    if endpoint is None:
        return {**state, "reachable": False, "ready": False, "error": "missing_endpoint"}
    if provider_id == "joyai":
        return await _probe_joyai(state, timeout_s=timeout_s)

    url, headers, params = _probe_url(spec, endpoint)
    owns_client = client is None
    probe_client = client or httpx.AsyncClient(timeout=timeout_s, follow_redirects=True)
    try:
        response = await probe_client.request(
            spec.probe_method, url, headers=headers, params=params
        )
        reachable = 200 <= response.status_code < 300
        error = None if reachable else f"http_{response.status_code}"
        return {
            **state,
            "reachable": reachable,
            "ready": bool(reachable),
            "http_status": response.status_code,
            "error": error,
        }
    except (httpx.HTTPError, OSError) as exc:
        return {
            **state,
            "reachable": False,
            "ready": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if owns_client:
            await probe_client.aclose()


async def _probe_joyai(state: dict[str, Any], *, timeout_s: float) -> dict[str, Any]:
    """Complete a real WebSocket handshake without sending an edit request."""

    url = stream_endpoint()
    if not url:
        return {**state, "reachable": False, "ready": False, "error": "missing_endpoint"}
    try:
        from websockets.asyncio.client import connect

        headers: dict[str, str] = {}
        api_key = _value("JOYAI_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        kwargs: dict[str, Any] = {
            "open_timeout": timeout_s,
            "close_timeout": timeout_s,
            "ping_interval": None,
        }
        if headers:
            kwargs["additional_headers"] = headers
        async with connect(url, **kwargs):
            pass
        return {**state, "reachable": True, "ready": True, "error": None}
    except Exception as exc:
        return {
            **state,
            "reachable": False,
            "ready": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


async def inspect_providers(
    *,
    provider_ids: list[str] | None = None,
    probe: bool = True,
    timeout_s: float = 5.0,
) -> list[dict[str, Any]]:
    """Inspect all configured providers concurrently, optionally probing them."""

    ids = provider_ids or [item.provider_id for item in PROVIDER_SPECS]
    if not probe:
        return [
            {
                **item,
                "reachable": None,
                "configuration_ready": bool(item["configured"]),
                "ready": None,
                "error": "probe_disabled",
            }
            for item in provider_configuration()
            if item["id"] in ids
        ]
    results = await asyncio.gather(*(probe_provider(item, timeout_s=timeout_s) for item in ids))
    return list(results)


READINESS_STATUSES = frozenset(
    {
        "READY",
        "BLOCKED_CONFIG",
        "BLOCKED_NETWORK",
        "BLOCKED_AUTH",
        "BLOCKED_MODEL",
        "BLOCKED_RUNTIME",
        "UNSUPPORTED",
    }
)


def _blocked_status(raw: dict[str, Any]) -> tuple[str, str]:
    """Classify a failed probe without converting failure into success."""

    if not raw.get("configured"):
        missing = ", ".join(str(item) for item in raw.get("missing", []))
        return "BLOCKED_CONFIG", f"missing configuration: {missing or 'provider endpoint'}"
    status_code = raw.get("http_status")
    if status_code in {401, 403}:
        return "BLOCKED_AUTH", f"provider returned HTTP {status_code}"
    error = str(raw.get("error") or "probe failed")
    return "BLOCKED_NETWORK", error


def readiness_from_probe(
    raw: dict[str, Any],
    *,
    model_ready: bool = False,
    submit_ready: bool = False,
    artifact_ready: bool = False,
    provider_job_id: str | None = None,
) -> dict[str, Any]:
    """Build the fail-closed readiness contract from probe and live evidence.

    A health response alone never proves a production generation.  The caller
    must provide model, submit/ACK, and artifact evidence before this function
    can return ``READY``.  This keeps control-plane health distinct from the
    generation plane, especially for MPT.
    """

    result: dict[str, Any] = {
        "provider_name": raw.get("name") or raw.get("provider_name") or raw.get("id"),
        "configured": bool(raw.get("configured")),
        "reachable": bool(raw.get("reachable")),
        "authenticated": False,
        "model_ready": bool(model_ready),
        "submit_ready": bool(submit_ready),
        "artifact_ready": bool(artifact_ready),
        "provider_job_id": provider_job_id,
        "status": "BLOCKED_RUNTIME",
        "reason": "",
    }
    if not result["configured"] or not result["reachable"]:
        result["status"], result["reason"] = _blocked_status(raw)
        return result

    # A successful authenticated request is the strongest evidence exposed by
    # the generic probe.  Local runtimes have no auth step, so reachability is
    # sufficient for this field; submit/artifact evidence is still required.
    result["authenticated"] = True
    provider_id = str(raw.get("id") or "")
    if provider_id == "mpt" and not model_ready:
        result["status"] = "BLOCKED_MODEL"
        result["reason"] = "control-plane /ping passed; generation-plane model/artifact not proven"
        return result
    if not result["model_ready"]:
        result["status"] = "BLOCKED_MODEL"
        result["reason"] = "probe reached provider, but model readiness was not proven"
        return result
    if not result["submit_ready"]:
        result["status"] = "BLOCKED_RUNTIME"
        result["reason"] = "model is ready, but no real provider submit/ACK evidence was supplied"
        return result
    if not result["artifact_ready"]:
        result["status"] = "BLOCKED_RUNTIME"
        result["reason"] = (
            "provider submit/ACK exists, but no verified non-empty artifact was supplied"
        )
        return result
    result["status"] = "READY"
    result["reason"] = "real probe, model, submit/ACK, and artifact evidence present"
    return result


async def probe_provider_readiness(
    provider_id: str,
    *,
    artifact_path: str | Path | None = None,
    model_ready: bool = False,
    submit_ready: bool = False,
    provider_job_id: str | None = None,
    timeout_s: float = 5.0,
) -> dict[str, Any]:
    """Run a real probe and return the strict production readiness contract."""

    raw = await probe_provider(provider_id, timeout_s=timeout_s)
    artifact_ready = False
    if artifact_path is not None:
        path = Path(artifact_path)
        artifact_ready = path.is_file() and path.stat().st_size > 0
    return readiness_from_probe(
        raw,
        model_ready=model_ready,
        submit_ready=submit_ready,
        artifact_ready=artifact_ready,
        provider_job_id=provider_job_id,
    )


def runtime_provider_ids() -> tuple[str, ...]:
    return tuple(item.provider_id for item in PROVIDER_SPECS)


__all__ = [
    "PROVIDER_SPECS",
    "READINESS_STATUSES",
    "ProviderSpec",
    "inspect_providers",
    "probe_provider",
    "probe_provider_readiness",
    "provider_configuration",
    "readiness_from_probe",
    "runtime_provider_ids",
    "stream_endpoint",
]
