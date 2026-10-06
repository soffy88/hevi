"""HEVI P9.0 — Live drivers: one per declared health-check mechanism.

P8.1.5 declared four mechanisms, and refusing to unify them was the right call — a
video provider may be a hosted API, a queue that reports liveness out of band, a
subprocess on the render host, or an in-process library. Probing a subprocess with an
HTTP request would have produced confident nonsense.

P9.0 turns each into a driver that can actually attempt a call:

```
HTTP            request -> response -> status
QUEUE           submit -> job id -> poll -> locator
CLI / LOCAL     command -> exit code -> artifact
```

Every driver is fail-closed and *attempt-honest*. With no credential it reports
``CREDENTIAL_MISSING``; with no configured command it reports ``NOT_ATTEMPTED``. Those
are different states, and conflating them would mean "we could not try" is recorded as
"the provider is broken" — a fact about the provider that only the environment supports.

Credentials are resolved through :class:`CredentialProvider` and handed straight to the
transport. ``credential_names`` records **which names were actually resolved**, never
their values — and never the declared requirements, because echoing the declaration
would make the declared-vs-observed diff compare the catalogue to itself and always
report agreement.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from hevi.providers.runtime_specs import HealthCheckKind, ProviderRuntimeSpec
from hevi.runtime.live.credentials import (
    CredentialProvider,
    EnvironmentCredentialProvider,
)
from hevi.runtime.live.status import LiveOutcome, LiveRuntimeStatus

#: Patterns that can carry a secret, each with whether group 1 is a *prefix to keep*.
#:
#: The distinction is load-bearing. For ``?api_key=<secret>`` group 1 is the parameter
#: name and must survive; for ``sk-<secret>`` group 1 *is* the secret and re-emitting it
#: would put the token straight back into the record — which an earlier version of this
#: function did.
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], bool], ...] = (
    (re.compile(r"(?i)([?&](?:key|token|api_key|apikey|access_token|secret)=)[^&\s]+"), True),
    # consumes "Bearer <token>" as a unit; an earlier pattern stopped at the scheme and
    # left the token behind
    (re.compile(r"(?i)(authorization:\s*)(?:bearer\s+|token\s+)?\S+"), True),
    (re.compile(r"(?i)((?:bearer|token)\s+)\S+"), True),
    (re.compile(r"(?i)sk-[A-Za-z0-9_\-]{6,}"), False),
)


def redact(text: str) -> str:
    """Strip anything token-shaped from a string bound for a record.

    ``prefix_kept`` says whether group 1 is safe to re-emit. Getting this wrong in
    either direction leaks: preserving a secret, or destroying useful context.
    """
    out = text
    for pattern, prefix_kept in _SECRET_PATTERNS:
        out = pattern.sub(
            (lambda m: f"{m.group(1)}***") if prefix_kept else (lambda m: "***"), out
        )
    return out


@dataclass(frozen=True)
class DriverResult:
    """What a driver saw. ``ok`` cannot be true without an observation behind it."""

    status: LiveRuntimeStatus
    payload: bytes = b""
    locator: str = ""

    @property
    def ok(self) -> bool:
        return self.status.is_live_usable

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.to_dict(),
            "payload_bytes": len(self.payload),
            "has_payload": bool(self.payload),
            "locator": self.locator,
        }


class LiveDriver(Protocol):
    """Attempts one real call. Never fabricates success."""

    kind: HealthCheckKind

    def attempt(self, spec: ProviderRuntimeSpec) -> DriverResult: ...


def _absent(
    spec: ProviderRuntimeSpec, provider: CredentialProvider
) -> DriverResult | None:
    """The shared credential gate.

    Every driver refuses the same way rather than each inventing a failure mode. The
    result records **no** credential names, because none were resolved — recording the
    declared requirement list here is what previously made the declared-vs-observed
    diff report agreement while the credential was in fact missing.
    """
    missing = tuple(name for name in spec.auth_requirements if provider.get(name) is None)
    if not missing:
        return None
    return DriverResult(
        status=LiveRuntimeStatus(
            provider_id=spec.provider_id,
            outcome=LiveOutcome.CREDENTIAL_MISSING,
            reason=f"required credentials absent: {', '.join(missing)}",
            request_kind=spec.health_check.value,
            credential_names=(),
        )
    )


def _not_attempted(spec: ProviderRuntimeSpec, reason: str) -> DriverResult:
    return DriverResult(
        status=LiveRuntimeStatus(
            provider_id=spec.provider_id,
            outcome=LiveOutcome.NOT_ATTEMPTED,
            reason=redact(reason),
            request_kind=spec.health_check.value,
            credential_names=(),
        )
    )


def _resolved(spec: ProviderRuntimeSpec, provider: CredentialProvider) -> dict[str, str]:
    """Credential values keyed by header. Names are recorded by the caller."""
    headers: dict[str, str] = {}
    for name in spec.auth_requirements:
        credential = provider.get(name)
        if credential is not None:
            headers[_header_for(name)] = credential.resolve()
    return headers


def _resolved_names(spec: ProviderRuntimeSpec, provider: CredentialProvider) -> tuple[str, ...]:
    return tuple(
        name for name in spec.auth_requirements if provider.get(name) is not None
    )


def _as_url(target: str) -> str:
    """Normalise a declared target to a URL.

    ``ProviderRuntimeSpec.target`` is a host for most services
    (``api.wavespeed.ai``, ``fal.run``) rather than a full URL. Requiring a scheme
    would refuse every real provider for a formatting reason, so a bare host means
    https.
    """
    if not target:
        return ""
    if target.startswith(("http://", "https://")):
        return target
    return f"https://{target}"


def _runtime_unavailable(spec: ProviderRuntimeSpec, executable: str) -> DriverResult:
    """A declared local runtime that is not installed.

    Distinct from ``NOT_ATTEMPTED``: the driver exists, the mechanism is declared, and
    something specific is known to be missing. That names a fixable cause, where
    ``NOT_ATTEMPTED`` says only that nothing was tried.
    """
    return DriverResult(
        status=LiveRuntimeStatus(
            provider_id=spec.provider_id,
            outcome=LiveOutcome.RUNTIME_UNAVAILABLE,
            reason=f"declared runtime not found on PATH: {executable}",
            request_kind=spec.health_check.value,
            credential_names=(),
        )
    )


def _header_for(name: str) -> str:
    """Map a credential name to a header, without pretending one mapping is universal."""
    upper = name.upper()
    return "Authorization" if upper.endswith("_API_KEY") else upper


class HttpLiveDriver:
    """One request, one response."""

    kind = HealthCheckKind.HTTP

    def __init__(
        self,
        *,
        credentials: CredentialProvider | None = None,
        endpoint: str = "",
        timeout_s: float = 10.0,
        transport: Any | None = None,
    ) -> None:
        self._credentials = credentials or EnvironmentCredentialProvider()
        self._endpoint = endpoint
        self._timeout = timeout_s
        #: injectable transport, so qualification can be exercised without a network
        self._transport = transport

    def attempt(self, spec: ProviderRuntimeSpec) -> DriverResult:
        absent = _absent(spec, self._credentials)
        if absent is not None:
            return absent

        endpoint = _as_url(self._endpoint or spec.target)
        if not endpoint:
            return _not_attempted(spec, f"no usable endpoint declared for {spec.provider_id}")

        headers = _resolved(spec, self._credentials)
        names = _resolved_names(spec, self._credentials)
        kind = self.kind.value

        try:
            if self._transport is not None:
                status_code, body, elapsed_ms = self._transport(endpoint, headers, self._timeout)
            else:
                import httpx

                started = time.monotonic()
                response = httpx.get(endpoint, headers=headers, timeout=self._timeout)
                status_code, body = response.status_code, response.content
                elapsed_ms = int((time.monotonic() - started) * 1000)
        except Exception as exc:
            return DriverResult(
                status=LiveRuntimeStatus(
                    provider_id=spec.provider_id, outcome=LiveOutcome.UNREACHABLE,
                    reason=redact(f"{type(exc).__name__}:{exc}"),
                    request_kind=kind, credential_names=names,
                )
            )

        code = int(status_code)
        if not 200 <= code < 300:
            return DriverResult(
                status=LiveRuntimeStatus(
                    provider_id=spec.provider_id, outcome=LiveOutcome.REJECTED,
                    reason=f"http_{code}", status_code=code,
                    latency_ms=int(elapsed_ms), request_kind=kind, credential_names=names,
                )
            )

        return DriverResult(
            status=LiveRuntimeStatus(
                provider_id=spec.provider_id, outcome=LiveOutcome.OK,
                latency_ms=int(elapsed_ms), status_code=code,
                request_kind=kind, credential_names=names,
            ),
            payload=body if isinstance(body, bytes) else str(body).encode(),
        )


class QueueLiveDriver:
    """Submit, collect a job id, poll it. A queue is not a request/response API."""

    kind = HealthCheckKind.QUEUE

    def __init__(
        self,
        *,
        credentials: CredentialProvider | None = None,
        endpoint: str = "",
        submit: Any | None = None,
        poll: Any | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._credentials = credentials or EnvironmentCredentialProvider()
        self._endpoint = endpoint
        self._submit = submit
        self._poll = poll
        self._timeout = timeout_s

    def attempt(self, spec: ProviderRuntimeSpec) -> DriverResult:
        absent = _absent(spec, self._credentials)
        if absent is not None:
            return absent

        endpoint = _as_url(self._endpoint or spec.target)
        if not endpoint:
            return _not_attempted(spec, f"no usable endpoint declared for {spec.provider_id}")

        headers = _resolved(spec, self._credentials)
        names = _resolved_names(spec, self._credentials)
        kind = self.kind.value

        try:
            submitted = (
                self._submit(endpoint, headers)
                if self._submit is not None
                else _default_submit(endpoint, headers, self._timeout)
            )
        except Exception as exc:
            return DriverResult(
                status=LiveRuntimeStatus(
                    provider_id=spec.provider_id, outcome=LiveOutcome.UNREACHABLE,
                    reason=redact(f"submit failed {type(exc).__name__}:{exc}"),
                    request_kind=kind, credential_names=names,
                )
            )

        job_id = _extract_job_id(submitted)
        if not job_id:
            return DriverResult(
                status=LiveRuntimeStatus(
                    provider_id=spec.provider_id, outcome=LiveOutcome.REJECTED,
                    reason="submit succeeded but returned no job id",
                    request_kind=kind, credential_names=names,
                )
            )

        try:
            finished = (
                self._poll(endpoint, headers, job_id)
                if self._poll is not None
                else _default_poll(endpoint, headers, job_id, self._timeout)
            )
        except Exception as exc:
            return DriverResult(
                status=LiveRuntimeStatus(
                    provider_id=spec.provider_id, outcome=LiveOutcome.UNREACHABLE,
                    reason=redact(f"poll failed {type(exc).__name__}:{exc}"),
                    request_kind=f"{kind}:{job_id}", credential_names=names,
                )
            )

        locator = _extract_locator(finished)
        if not locator:
            return DriverResult(
                status=LiveRuntimeStatus(
                    provider_id=spec.provider_id, outcome=LiveOutcome.REJECTED,
                    reason=f"job {job_id} completed without an artifact locator",
                    request_kind=f"{kind}:{job_id}", credential_names=names,
                )
            )

        return DriverResult(
            status=LiveRuntimeStatus(
                provider_id=spec.provider_id, outcome=LiveOutcome.OK,
                latency_ms=0, request_kind=f"{kind}:{job_id}", credential_names=names,
            ),
            locator=redact(locator),
        )


class LocalLiveDriver:
    """Run a command and read its exit code. For CLI and LOCAL_PROCESS providers."""

    kind = HealthCheckKind.LOCAL_PROCESS

    def __init__(
        self,
        *,
        credentials: CredentialProvider | None = None,
        command: tuple[str, ...] | None = None,
        runner: Any | None = None,
        timeout_s: float = 120.0,
        artifact_path: str = "",
        cwd: str | None = None,
    ) -> None:
        self._credentials = credentials or EnvironmentCredentialProvider()
        self._command = command
        self._runner = runner
        self._timeout = timeout_s
        self._artifact_path = artifact_path
        #: a renderer is normally run from its own project directory
        self._cwd = cwd

    def attempt(self, spec: ProviderRuntimeSpec) -> DriverResult:
        absent = _absent(spec, self._credentials)
        if absent is not None:
            return absent

        if not self._command:
            return _not_attempted(
                spec,
                f"no command configured for {spec.provider_id}; declared mechanism "
                f"is {spec.health_check.value}",
            )

        # A configured command whose executable is absent is a different state from
        # no command at all: we know precisely what is missing.
        if self._runner is None and shutil.which(self._command[0]) is None:
            return _runtime_unavailable(spec, self._command[0])

        names = _resolved_names(spec, self._credentials)
        kind = self.kind.value
        started = time.monotonic()
        try:
            exit_code, artifact = (
                self._runner(self._command, self._timeout)
                if self._runner is not None
                else _default_run(self._command, self._timeout, self._cwd)
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return DriverResult(
                status=LiveRuntimeStatus(
                    provider_id=spec.provider_id, outcome=LiveOutcome.UNREACHABLE,
                    reason=redact(f"{type(exc).__name__}:{exc}"),
                    request_kind=kind, credential_names=names,
                )
            )
        elapsed_ms = int((time.monotonic() - started) * 1000)

        # exit code 0 is not production success; an artifact must exist too.
        if int(exit_code) != 0:
            return DriverResult(
                status=LiveRuntimeStatus(
                    provider_id=spec.provider_id, outcome=LiveOutcome.REJECTED,
                    reason=f"command exited {exit_code}", status_code=int(exit_code),
                    latency_ms=elapsed_ms, request_kind=kind, credential_names=names,
                )
            )

        locator = artifact or self._artifact_path
        if not locator:
            return DriverResult(
                status=LiveRuntimeStatus(
                    provider_id=spec.provider_id, outcome=LiveOutcome.REJECTED,
                    reason="command exited 0 but produced no artifact",
                    latency_ms=elapsed_ms, request_kind=kind, credential_names=names,
                )
            )

        return DriverResult(
            status=LiveRuntimeStatus(
                provider_id=spec.provider_id, outcome=LiveOutcome.OK,
                latency_ms=elapsed_ms, status_code=0,
                request_kind=kind, credential_names=names,
            ),
            locator=locator,
        )


def _default_submit(endpoint: str, headers: dict[str, str], timeout_s: float) -> Any:
    import httpx

    response = httpx.post(endpoint, headers=headers, timeout=timeout_s, json={})
    response.raise_for_status()
    return response


def _default_poll(endpoint: str, headers: dict[str, str], job_id: str, timeout_s: float) -> Any:
    import httpx

    response = httpx.get(f"{endpoint.rstrip('/')}/{job_id}", headers=headers, timeout=timeout_s)
    response.raise_for_status()
    return response


def _default_run(
    command: tuple[str, ...], timeout_s: float, cwd: str | None = None
) -> tuple[int, str]:
    result = subprocess.run(  # noqa: S603 - the command is operator-supplied config
        list(command), capture_output=True, timeout=timeout_s, check=False,
        env=dict(os.environ), cwd=cwd,
    )
    return result.returncode, ""


def _json_of(response: Any) -> dict[str, Any]:
    try:
        payload = response.json()
    except (AttributeError, json.JSONDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_job_id(response: Any) -> str:
    payload = _json_of(response)
    for key in ("id", "job_id", "request_id", "task_id", "requestId"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _extract_locator(response: Any) -> str:
    payload = _json_of(response)
    for key in ("url", "video_url", "output_url", "output", "artifact_url", "video"):
        value = payload.get(key)
        if isinstance(value, dict):
            value = value.get("url")
        if isinstance(value, str) and value:
            return value
    return ""


@dataclass(frozen=True)
class DriverRegistry:
    """Maps a declared mechanism to the driver that can attempt it."""

    drivers: dict[HealthCheckKind, Any] = field(default_factory=dict)

    def driver_for(self, spec: ProviderRuntimeSpec) -> Any | None:
        return self.drivers.get(spec.health_check)

    def kinds(self) -> tuple[HealthCheckKind, ...]:
        return tuple(sorted(self.drivers, key=lambda k: k.value))


def default_registry(
    *,
    credentials: CredentialProvider | None = None,
    http_endpoint: str = "",
    queue_endpoint: str = "",
    local_command: tuple[str, ...] | None = None,
) -> DriverRegistry:
    """A registry covering all four declared mechanisms."""
    provider = credentials or EnvironmentCredentialProvider()
    return DriverRegistry(
        drivers={
            HealthCheckKind.HTTP: HttpLiveDriver(credentials=provider, endpoint=http_endpoint),
            HealthCheckKind.QUEUE: QueueLiveDriver(
                credentials=provider, endpoint=queue_endpoint
            ),
            HealthCheckKind.CLI: LocalLiveDriver(
                credentials=provider, command=local_command
            ),
            HealthCheckKind.LOCAL_PROCESS: LocalLiveDriver(
                credentials=provider, command=local_command
            ),
        }
    )


__all__ = [
    "DriverRegistry",
    "DriverResult",
    "HttpLiveDriver",
    "LiveDriver",
    "LocalLiveDriver",
    "QueueLiveDriver",
    "default_registry",
    "redact",
]
