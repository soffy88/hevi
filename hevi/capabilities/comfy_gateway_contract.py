"""ComfyUI gateway contract (``qa.comfy_gateway_contract``).

Clean-room rewrite of the gateway discipline from
``raph651/open-source-canvas`` (MIT; see
OPEN_SOURCE_CANVAS_ATTRIBUTION.md). No code, text or configuration
from that repository is copied here, and nothing here opens a
network connection, stores a credential, or submits a job: this
module judges *request plans* only. It is the access contract that
any future ComfyUI executor must satisfy before it is allowed to
talk to a ComfyUI server.

Rules, in own wording:

1. Endpoint allowlist. Exactly six ComfyUI endpoints may be
   reached through the gateway: ``POST /prompt``,
   ``GET /history/<prompt_id>``, ``GET /view``,
   ``POST /upload/image``, ``POST /interrupt`` and
   ``GET /system_stats``. Everything else is refused, including
   WebSocket upgrades, file browsing, custom-node installation and
   ``/object_info`` (whose snapshot the model-install gate takes
   from the caller, out of band, never through this gateway).
2. Body size. A request body larger than the configured cap
   (default 40 MiB, the upstream default) fails; the cap itself is
   caller-configurable and is always named in the failure.
3. Visitor isolation. Queue-scoped endpoints (``/prompt``,
   ``/history/*``, ``/view``) carry a visitor id; a request that
   names a different visitor than the resource it addresses, or
   that addresses another visitor's resource anonymously, fails.
4. Health redaction. Without authentication a health response may
   only say the server is online and report its version; any
   further field fails as unredacted.
5. Authentication layers are declared, never supplied. The plan
   may name one of three layers (direct bearer token, gateway key,
   Cloudflare Access). Key, secret or token *values* in the plan
   fail outright: credentials are never part of a judged plan.

Failure contract: a malformed request (not a JSON object, missing
method/path) raises :class:`CapabilityError`. Gate failures are
reported in the result, never raised. Verdicts are ``pass`` /
``fail`` only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

# (method, path template). ``{prompt_id}`` matches exactly one
# non-empty path segment.
ALLOWED_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("POST", "/prompt"),
    ("GET", "/history/{prompt_id}"),
    ("GET", "/view"),
    ("POST", "/upload/image"),
    ("POST", "/interrupt"),
    ("GET", "/system_stats"),
)

DEFAULT_MAX_BODY_BYTES = 40 * 1024 * 1024

AUTH_LAYERS = frozenset({"direct_bearer", "gateway_key", "cloudflare_access"})

# Endpoints that are queue-scoped: visitor isolation applies.
QUEUE_SCOPED_PATHS = frozenset({"/prompt", "/history", "/view"})

# Health responses without authentication may only carry these keys.
HEALTH_PUBLIC_KEYS = frozenset({"online", "version"})

_SECRET_FIELD_NAMES = frozenset(
    {
        "api_key",
        "apikey",
        "osc_access_key",
        "access_key",
        "secret",
        "token",
        "authorization",
        "password",
        "cf_access_client_secret",
    }
)

__all__ = [
    "ALLOWED_ENDPOINTS",
    "DEFAULT_MAX_BODY_BYTES",
    "AUTH_LAYERS",
    "HEALTH_PUBLIC_KEYS",
    "check_gateway_request",
    "check_health_response",
]


def _fail(message: str) -> None:
    raise CapabilityError(message)


def _normalize_path(path: Any) -> str:
    if not isinstance(path, str) or not path:
        _fail("gateway request path must be a non-empty string")
    path = path.split("?", 1)[0].split("#", 1)[0]
    if len(path) > 1:
        path = path.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return path


def _endpoint_matches(method: str, path: str) -> str | None:
    """Return the matched allowlist template, or None."""
    segments = [s for s in path.split("/") if s != ""]
    for allowed_method, template in ALLOWED_ENDPOINTS:
        if method != allowed_method:
            continue
        template_segments = [s for s in template.split("/") if s != ""]
        if len(segments) != len(template_segments):
            continue
        matched = True
        for actual, expected in zip(segments, template_segments):
            if expected.startswith("{") and expected.endswith("}"):
                if not actual:
                    matched = False
                    break
            elif actual != expected:
                matched = False
                break
        if matched:
            return template
    return None


def _is_queue_scoped(path: str) -> bool:
    first = "/" + path.strip("/").split("/")[0] if path.strip("/") else "/"
    return first in QUEUE_SCOPED_PATHS


def _has_secret_value(request: dict[str, Any]) -> list[str]:
    """Field names in the plan that carry credential values."""
    found: list[str] = []
    for key, value in request.items():
        lowered = str(key).lower()
        if lowered in _SECRET_FIELD_NAMES or lowered.endswith(
            ("_key", "_secret", "_token")
        ):
            if value not in (None, ""):
                found.append(str(key))
    headers = request.get("headers")
    if isinstance(headers, dict):
        for key, value in headers.items():
            if str(key).lower() in ("authorization", "x-osc-key", "cookie"):
                if value not in (None, ""):
                    found.append(f"headers.{key}")
    return found


def check_gateway_request(
    request: Any, *, max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
) -> dict[str, Any]:
    """Judge one planned gateway request against the contract.

    ``request`` is a plain dict with ``method`` and ``path`` plus
    optional ``headers``, ``body_bytes``, ``visitor_id``,
    ``resource_visitor_id`` and ``auth_layer``. No network call is
    made and no credential is read: secret-looking values in the
    plan itself are a failure, not something to forward.
    """
    if not isinstance(request, dict):
        _fail("gateway request must be a JSON object")
    failures: list[dict[str, str]] = []
    warnings: list[str] = []

    method = request.get("method")
    if not isinstance(method, str) or not method:
        _fail("gateway request method must be a non-empty string")
    method = method.upper()
    path = _normalize_path(request.get("path"))

    headers = request.get("headers")
    if headers is not None and not isinstance(headers, dict):
        _fail("gateway request headers must be an object")
    upgrade = ""
    if isinstance(headers, dict):
        upgrade = str(headers.get("upgrade", "")).strip().lower()
    if upgrade == "websocket" or path in ("/ws", "/websocket"):
        failures.append(
            {
                "code": "websocket_denied",
                "message": "WebSocket upgrades are refused by the gateway contract",
            }
        )

    template = _endpoint_matches(method, path)
    if template is None:
        failures.append(
            {
                "code": "endpoint_not_allowed",
                "message": (
                    f"endpoint {method} {path} is not on the gateway "
                    "allowlist (POST /prompt, GET /history/<id>, "
                    "GET /view, POST /upload/image, POST /interrupt, "
                    "GET /system_stats)"
                ),
            }
        )
    else:
        if path == "/interrupt":
            warnings.append(
                "interrupt is machine-wide: it cancels the running "
                "job regardless of visitor"
            )

    if not isinstance(max_body_bytes, int) or max_body_bytes < 0:
        _fail("max_body_bytes must be a non-negative integer")
    body_bytes = request.get("body_bytes", 0)
    if body_bytes is not None:
        if not isinstance(body_bytes, int) or body_bytes < 0:
            _fail("body_bytes must be a non-negative integer")
        if body_bytes > max_body_bytes:
            failures.append(
                {
                    "code": "body_too_large",
                    "message": (
                        f"request body {body_bytes} bytes exceeds the "
                        f"gateway cap of {max_body_bytes} bytes"
                    ),
                }
            )

    auth_layer = request.get("auth_layer")
    if auth_layer is not None and auth_layer not in AUTH_LAYERS:
        failures.append(
            {
                "code": "unknown_auth_layer",
                "message": (
                    f"auth_layer {auth_layer!r} is unknown; known "
                    "layers are direct_bearer, gateway_key and "
                    "cloudflare_access"
                ),
            }
        )
    for field in _has_secret_value(request):
        failures.append(
            {
                "code": "secret_must_not_be_supplied",
                "message": (
                    f"credential value field {field!r} must not appear "
                    "in a gateway plan; declare the auth layer only"
                ),
            }
        )

    if template is not None and _is_queue_scoped(path):
        visitor_id = request.get("visitor_id")
        resource_visitor_id = request.get("resource_visitor_id")
        if resource_visitor_id is not None:
            if visitor_id is None:
                failures.append(
                    {
                        "code": "cross_visitor_denied",
                        "message": (
                            "queue-scoped resource addressed without "
                            "a visitor id; anonymous cross-visitor "
                            "queries are refused"
                        ),
                    }
                )
            elif str(visitor_id) != str(resource_visitor_id):
                failures.append(
                    {
                        "code": "cross_visitor_denied",
                        "message": (
                            "visitor id does not match the resource "
                            "owner; cross-visitor queries are refused"
                        ),
                    }
                )

    return {
        "verdict": "fail" if failures else "pass",
        "method": method,
        "path": path,
        "endpoint": template,
        "failures": failures,
        "warnings": warnings,
    }


def check_health_response(
    response: Any, *, authenticated: bool = False
) -> dict[str, Any]:
    """Judge a health response against the redaction rule.

    Unauthenticated callers may only learn that the server is
    online and which version it runs. Anything beyond ``online``
    and ``version`` fails as unredacted. Authenticated callers
    must still receive both fields.
    """
    if not isinstance(response, dict):
        _fail("health response must be a JSON object")
    failures: list[dict[str, str]] = []
    missing = [key for key in ("online", "version") if key not in response]
    if missing:
        failures.append(
            {
                "code": "health_response_incomplete",
                "message": f"health response is missing {', '.join(missing)}",
            }
        )
    if not authenticated:
        leaked = sorted(set(response) - HEALTH_PUBLIC_KEYS)
        if leaked:
            failures.append(
                {
                    "code": "health_response_not_redacted",
                    "message": (
                        "unauthenticated health response must only "
                        f"carry online/version; leaked fields: "
                        f"{', '.join(leaked)}"
                    ),
                }
            )
    return {
        "verdict": "fail" if failures else "pass",
        "authenticated": authenticated,
        "failures": failures,
    }


_PARAMS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "request": {"type": "object"},
        "health_response": {"type": "object"},
        "authenticated": {"type": "boolean"},
        "max_body_bytes": {"type": "integer"},
    },
    "additionalProperties": False,
}


def _render(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {}
    if "request" in params:
        kwargs: dict[str, Any] = {}
        if params.get("max_body_bytes") is not None:
            kwargs["max_body_bytes"] = int(params["max_body_bytes"])
        report["gateway_request"] = check_gateway_request(
            params["request"], **kwargs
        )
    if "health_response" in params:
        report["health_response"] = check_health_response(
            params["health_response"],
            authenticated=bool(params.get("authenticated", False)),
        )
    if not report:
        _fail("comfy_gateway_contract needs request and/or health_response")
    report_path = out_dir / "comfy_gateway_contract_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    verdicts = [part["verdict"] for part in report.values()]
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={
            "report_json": str(report_path),
            "verdict": "fail" if "fail" in verdicts else "pass",
            **report,
        },
    )


def register_comfy_gateway_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.comfy_gateway_contract",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_PARAMS_SCHEMA,
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "ComfyUI gateway contract: six-endpoint allowlist, "
                "body-size cap, visitor isolation, redacted health "
                "checks and declared-only authentication. Judges "
                "request plans only; no network call, no credential "
                "is read or stored, no job is submitted."
            ),
            line="qa",
        )
    )
    return ["qa.comfy_gateway_contract"]


register_comfy_gateway_capabilities_once()
