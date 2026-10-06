"""HEVI P9.2 — the HTTP adapter: request lifecycle only.

    submit -> poll -> download -> ExecutionResult(artifact_locator)

The adapter performs the provider's request lifecycle and nothing else. It does not
hash, probe, decode, validate or judge. The moment it measured its own download it
would be a second artifact authority — the exact defect P9.1.d removed from
``hevi/renderers/``.

Three properties make that structural rather than aspirational:

* ``ExecutionResult`` has no ``checksum`` / ``codec`` / ``duration`` / ``passed`` field.
* This module imports no hashing, probing or validation module, and spawns nothing.
* A completed job is **not** a qualified artifact. ``status="completed"`` means the
  provider finished; whether the bytes are a valid MP4 is P8.4's question, asked after
  the download, by the framework.

Provider identity note
----------------------
The HTTP fleet is addressed by **product id**, not vendor id: ``wan_2_7`` and
``happyhorse_1_1`` are WaveSpeed routes, ``wan_2_7_maas`` and ``happyhorse_1_1_maas``
are Alibaba Bailian routes. Registering ``wavespeed`` and ``alibaba_maas`` as providers
too would be two identities for one reseller — the collision P7.3 refused for
``ExecutionReceipt`` and P8.2 refused for ``ValidationCheck``. The vendor is declared on
``ProviderProfile.notes`` instead.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Union

from hevi.qualification.credentials import CredentialResolution
from hevi.qualification.models import (
    AdapterAvailability,
    AdapterFailure,
    Availability,
    ExecutionResult,
    ExecutionState,
    QualificationRequest,
    RuntimeUnavailable,
)
from hevi.qualification.providers._shared import check_locator, result_for, unavailable

ResponseBody = Union[dict[str, Any], bytes, str]  # noqa: UP007


class Transport(Protocol):
    """One HTTP round trip. Injectable, so the lifecycle is testable offline.

    The adapter depends on this narrow shape rather than on ``httpx`` itself: the
    request lifecycle is what is under test, and the network is not.
    """

    def __call__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        *,
        json_: dict[str, Any] | None = ...,
        timeout: float = ...,
        binary: bool = ...,
    ) -> tuple[int, ResponseBody]:
        ...


class JobTimeout(Exception):
    """The provider never finished the job inside its declared budget."""


@dataclass(frozen=True)
class HTTPProviderProfile:
    """Where and how to talk to one HTTP provider. Endpoint config, not identity."""

    provider_id: str
    vendor: str
    submit_url: str
    poll_url_template: str
    result_key: str = "video"
    poll_interval_s: float = 3.0
    max_polls: int = 20
    auth_header: str = "Authorization"
    required_credentials: tuple[str, ...] = ()

    def poll_url(self, job_id: str) -> str:
        return self.poll_url_template.format(job_id=job_id)


#: Declared endpoints for the HTTP fleet. Base hosts are operator-configurable via the
#: environment; nothing here is inferred from a provider's name.
HTTP_PROFILES: dict[str, HTTPProviderProfile] = {
    "wan_2_7": HTTPProviderProfile(
        provider_id="wan_2_7", vendor="wavespeed",
        submit_url="https://api.wavespeed.ai/api/v3/wan-2.7/text-to-video",
        poll_url_template="https://api.wavespeed.ai/api/v3/wan-2.7/tasks/{job_id}",
        required_credentials=("WAVESPEED_API_KEY",),
    ),
    "happyhorse_1_1": HTTPProviderProfile(
        provider_id="happyhorse_1_1", vendor="wavespeed",
        submit_url="https://api.wavespeed.ai/api/v3/happyhorse-1.1/text-to-video",
        poll_url_template="https://api.wavespeed.ai/api/v3/happyhorse-1.1/tasks/{job_id}",
        required_credentials=("WAVESPEED_API_KEY",),
    ),
    "wan_2_7_maas": HTTPProviderProfile(
        provider_id="wan_2_7_maas", vendor="alibaba_maas",
        submit_url="https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis",
        poll_url_template="https://dashscope.aliyuncs.com/api/v1/tasks/{job_id}",
        required_credentials=("ALIBABA_MAAS_API_KEY",),
    ),
    "happyhorse_1_1_maas": HTTPProviderProfile(
        provider_id="happyhorse_1_1_maas", vendor="alibaba_maas",
        submit_url="https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis",
        poll_url_template="https://dashscope.aliyuncs.com/api/v1/tasks/{job_id}",
        required_credentials=("ALIBABA_MAAS_API_KEY",),
    ),
}


def profile_for(provider_id: str) -> HTTPProviderProfile | None:
    return HTTP_PROFILES.get(provider_id)


class HTTPProviderAdapter:
    """Submit, poll, download. Returns a locator and nothing measured."""

    provider_id: str

    def __init__(
        self,
        profile: HTTPProviderProfile,
        *,
        credentials: CredentialResolution | None = None,
        auth_value: str = "",
        transport: Transport | None = None,
    ) -> None:
        self.profile = profile
        self.provider_id = profile.provider_id
        self._credentials = credentials
        #: resolved by the caller from a secret store and used only for the request
        self._auth_value = auth_value
        #: injectable transport, so the lifecycle is testable without a network
        self._transport = transport

    # ── availability ──
    def available(self) -> AdapterAvailability:
        if not self.profile.submit_url.startswith("https://"):
            return unavailable("submit_url_not_https:a submit URL must be TLS")
        creds = self._credentials
        if creds is not None and not creds.complete:
            return unavailable(
                f"credentials_missing:{','.join(creds.missing) or 'unspecified'}"
            )
        return AdapterAvailability(Availability.AVAILABLE)

    # ── execution ──
    def execute(self, request: QualificationRequest) -> ExecutionResult:
        availability = self.available()
        if not availability.can_run:
            raise RuntimeUnavailable(availability.reason)

        headers: dict[str, str] = {self.profile.auth_header: self._auth_value}
        transport: Transport = self._transport or _httpx_transport

        job_id = self._submit(request, headers, transport)
        locator = self._poll_and_download(request, headers, transport, job_id)
        check_locator(request, self.provider_id)
        return result_for(
            request,
            {
                "runtime_class": "http",
                "vendor": self.profile.vendor,
                "job_id": job_id,
                "transport": getattr(transport, "__name__", type(transport).__name__),
            },
        )

    def _submit(
        self,
        request: QualificationRequest,
        headers: dict[str, str],
        transport: Transport,
    ) -> str:
        started = time.monotonic()
        response: tuple[int, ResponseBody] = transport(
            "POST", self.profile.submit_url, headers,
            json_=request.params.get("payload", {}), timeout=request.timeout_s,
        )
        status, payload = response
        elapsed = int((time.monotonic() - started) * 1000)
        if status in (401, 403):
            # The credential was present and refused. Not unreachable, not a
            # transport fault: the provider answered, and the answer was no.
            raise AdapterFailure(
                ExecutionState.FAILED, f"credential_rejected:http_{status}",
                error_type="credential_rejected", http_status=status
            )
        if status >= 500:
            raise AdapterFailure(
                ExecutionState.FAILED, f"provider_unreachable:http_{status}:{elapsed}ms",
                error_type="provider_unreachable", http_status=status
            )
        if status >= 400:
            raise AdapterFailure(
                ExecutionState.FAILED, f"request_rejected:http_{status}",
                error_type="request_rejected", http_status=status
            )
        job_id = _job_id_of(_as_json(payload))
        if not job_id:
            raise AdapterFailure(
                ExecutionState.FAILED, "submit returned no job id",
                error_type="submit_no_job_id", http_status=status
            )
        return job_id

    def _poll_and_download(
        self,
        request: QualificationRequest,
        headers: dict[str, str],
        transport: Transport,
        job_id: str,
    ) -> str:
        deadline = time.monotonic() + request.timeout_s
        attempts = 0
        while attempts < self.profile.max_polls:
            if time.monotonic() > deadline:
                raise JobTimeout(
                    f"job {job_id} did not finish within {request.timeout_s:.0f}s"
                )
            attempts += 1
            response: tuple[int, ResponseBody] = transport(
                "GET", self.profile.poll_url(job_id), headers, json_=None,
                timeout=self.profile.poll_interval_s + 5,
            )
            status, payload = response
            if status >= 500:
                raise AdapterFailure(
                    ExecutionState.FAILED, f"poll_unreachable:http_{status}",
                    error_type="poll_unreachable", http_status=status
                )
            document = _as_json(payload)
            state = str(document.get("status", "")).lower()
            if state in {"failed", "error", "cancelled"}:
                raise AdapterFailure(
                    ExecutionState.FAILED, f"job_failed:{document.get('message', state)}",
                    error_type="job_failed", http_status=status
                )
            if state in {"completed", "succeeded", "success"}:
                # A completed job is NOT a qualified artifact. The bytes still have
                # to be downloaded, and then P8.4 has to agree they are a video.
                url = _result_url_of(document, self.profile.result_key)
                if not url:
                    raise AdapterFailure(
                        ExecutionState.NO_ARTIFACT,
                        f"job {job_id} completed but carried no artifact URL",
                        error_type="no_artifact", http_status=status,
                    )
                return self._download(request, headers, transport, url)
            time.sleep(self.profile.poll_interval_s)
        raise JobTimeout(f"job {job_id} still running after {attempts} polls")

    def _download(
        self,
        request: QualificationRequest,
        headers: dict[str, str],
        transport: Transport,
        url: str,
    ) -> str:
        response = transport(
            "GET", url, {}, json_=None, timeout=request.timeout_s, binary=True
        )
        status, body = response
        if status >= 400:
            raise AdapterFailure(
                ExecutionState.FAILED, f"download_failed:http_{status}",
                error_type="download_failed", http_status=status
            )
        payload: bytes = body if isinstance(body, bytes) else str(body).encode()
        if not payload:
            raise AdapterFailure(
                ExecutionState.NO_ARTIFACT, "download returned an empty body",
                error_type="no_artifact", http_status=status
            )
        target = Path(request.output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return str(target)


# ── response helpers ──

_JOB_ID_KEYS = ("id", "job_id", "request_id", "task_id", "requestId")
_RESULT_KEYS = ("url", "video_url", "output_url", "output", "video", "artifact_url")


def _as_json(body: ResponseBody) -> dict[str, Any]:
    """Narrow a transport body to JSON.

    A non-JSON body carries no job id and no status. Coercing it to ``{}`` makes that
    visible as a real failure ("submit returned no job id") instead of an AttributeError,
    and avoids pretending a parsed structure exists when none did.
    """
    if isinstance(body, dict):
        return body
    return {}


def _job_id_of(payload: dict[str, Any]) -> str:
    for key in _JOB_ID_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    nested = payload.get("data")
    if isinstance(nested, dict):
        return _job_id_of(nested)
    return ""


def _result_url_of(payload: dict[str, Any], preferred: str) -> str:
    def _search(node: dict[str, Any]) -> str:
        for key in (preferred, *_RESULT_KEYS):
            value = node.get(key)
            if isinstance(value, dict):
                inner = value.get("url")
                if isinstance(inner, str) and inner:
                    return inner
            if isinstance(value, str) and value.startswith("http"):
                return value
        return ""

    found = _search(payload)
    if found:
        return found
    for key in ("data", "output", "result"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = _search(nested)
            if found:
                return found
    return ""


def _httpx_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    *,
    json_: dict[str, Any] | None = None,
    timeout: float = 30.0,
    binary: bool = False,
) -> tuple[int, ResponseBody]:
    """Default transport. Real HTTP; inject a stub to exercise the lifecycle offline."""
    import httpx

    if method == "POST":
        response = httpx.post(url, headers=headers, json=json_ or {}, timeout=timeout)
    else:
        response = httpx.get(url, headers=headers, timeout=timeout)
    if binary:
        return response.status_code, response.content
    try:
        return response.status_code, response.json()
    except Exception:
        return response.status_code, {}


__all__ = [
    "HTTP_PROFILES",
    "HTTPProviderAdapter",
    "HTTPProviderProfile",
    "JobTimeout",
    "Transport",
    "profile_for",
]
