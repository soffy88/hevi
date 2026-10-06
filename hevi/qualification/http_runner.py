"""HEVI P9.2 — the HTTP qualification runner.

    credential check -> policy -> runtime -> submit -> poll -> download
                                                       |
                                  P8.2 acquisition -> P8.3 receipt -> P8.4 validation
                                                       |
                                                   QUALIFIED

Why a new state machine
-----------------------
``RunState`` (P9.0) describes a *live* run's lifecycle. HTTP qualification is a
different thing: an async submit/poll/download against a third party, gated on a
credential that may simply not exist. Reusing ``RunState`` would have implied that
``CREDENTIAL_MISSING`` and ``REQUEST_FAILED`` were the same kind of event. They are not —
one never left the machine, the other did and was refused — and the failure matrix
depends on the difference.

The runner adds no evidence authority. The P8 chain is still owned by
``qualify_local_provider``, so there is exactly one place where bytes become a receipt.

Failure mapping
---------------
An HTTP failure is mapped from *typed* metadata (``AdapterFailure.error_type`` and
``http_status``), never by matching substrings in a reason string. A provider that
happens to include the word "timeout" in an error message must not silently reclassify
its own failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from hevi.artifact.checks import CheckOperator, CheckRequirement
from hevi.qualification.credentials import (
    CredentialResolution,
    CredentialSource,
    resolve,
)
from hevi.qualification.framework_local import LocalQualification, qualify_local_provider
from hevi.qualification.live_run import QualificationVerdict
from hevi.qualification.models import (
    AdapterFailure,
    ExecutionState,
    ProviderQualification,
    QualificationRequest,
    RuntimeUnavailable,
)
from hevi.qualification.providers.http import (
    HTTPProviderAdapter,
    HTTPProviderProfile,
    JobTimeout,
    Transport,
    profile_for,
)

#: What an HTTP video provider's bytes must demonstrably be.
#:
#: These are **required, not optional**. P8.4's ``qualify()`` treats an empty check
#: tuple as "nothing to disprove", which means a download of ``b"not a video"`` passes.
#: A qualification runner that forwards an empty tuple has therefore silently disabled
#: artifact validation — and did, until this was written down. The runner owns the
#: contract for its fleet, so the contract is stated here rather than left to each caller.
HTTP_VIDEO_CHECKS: tuple[CheckRequirement, ...] = (
    CheckRequirement("container", "isom"),
    CheckRequirement("duration", 0.5, CheckOperator.GTE),
)


class HTTPQualificationState(StrEnum):
    """The HTTP qualification lifecycle. Deliberately not ``RunState``."""

    INITIAL = "initial"
    CREDENTIAL_CHECKED = "credential_checked"
    REQUEST_SUBMITTED = "request_submitted"
    WAITING_RESULT = "waiting_result"
    ARTIFACT_DOWNLOADED = "artifact_downloaded"
    VALIDATING = "validating"
    QUALIFIED = "qualified"
    # ── terminal failures ──
    CREDENTIAL_MISSING = "credential_missing"
    REQUEST_FAILED = "request_failed"
    TIMEOUT = "timeout"
    DOWNLOAD_FAILED = "download_failed"
    INVALID_ARTIFACT = "invalid_artifact"
    BLOCKED_BY_POLICY = "blocked_by_policy"
    NOT_ATTEMPTED = "not_attempted"


@dataclass(frozen=True)
class HTTPQualificationOutcome:
    """The runner's report. A verdict plus the path taken to reach it."""

    provider_id: str
    state: HTTPQualificationState
    verdict: QualificationVerdict
    reason: str = ""
    credentials: CredentialResolution | None = None
    qualification: LocalQualification | None = None
    state_path: tuple[HTTPQualificationState, ...] = ()

    @property
    def qualified(self) -> bool:
        return self.verdict is QualificationVerdict.QUALIFIED

    @property
    def receipt(self) -> Any:
        """The P8.3 ProductionReceipt, when one was issued."""
        return self.qualification.receipt if self.qualification else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "state": self.state.value,
            "verdict": self.verdict.value,
            "reason": self.reason,
            "credentials": self.credentials.to_dict() if self.credentials else None,
            "state_path": [s.value for s in self.state_path],
        }


#: typed failure metadata -> verdict. The whole HTTP failure matrix, in one table.
_FAILURE_VERDICTS: dict[str, QualificationVerdict] = {
    "credential_rejected": QualificationVerdict.QUALIFICATION_FAILED,
    "provider_unreachable": QualificationVerdict.PROVIDER_UNREACHABLE,
    "poll_unreachable": QualificationVerdict.PROVIDER_UNREACHABLE,
    "request_rejected": QualificationVerdict.QUALIFICATION_FAILED,
    "job_failed": QualificationVerdict.QUALIFICATION_FAILED,
    "submit_no_job_id": QualificationVerdict.QUALIFICATION_FAILED,
    "download_failed": QualificationVerdict.QUALIFICATION_FAILED,
    "no_artifact": QualificationVerdict.REJECTED,
    # A timeout is reported as TIMEOUT in the state machine, and as a qualification
    # failure in the verdict vocabulary: the verdict enum has no TIMEOUT member because
    # a timeout is not a distinct *outcome*, only a distinct way of not having one.
    "timeout": QualificationVerdict.QUALIFICATION_FAILED,
    "credentials_missing": QualificationVerdict.BLOCKED_BY_CREDENTIAL,
    # a non-TLS submit URL is a refused runtime contract, not a policy decision
    "submit_url_not_https": QualificationVerdict.BLOCKED_BY_RUNTIME,
}


def _verdict_for(failure: AdapterFailure) -> QualificationVerdict:
    """Map a typed adapter failure. Never parses the reason prose."""
    if failure.error_type and failure.error_type in _FAILURE_VERDICTS:
        return _FAILURE_VERDICTS[failure.error_type]
    if failure.state is ExecutionState.NO_ARTIFACT:
        return QualificationVerdict.REJECTED
    return QualificationVerdict.QUALIFICATION_FAILED


def _state_for(failure: AdapterFailure) -> HTTPQualificationState:
    kind = failure.error_type
    if kind == "timeout":
        return HTTPQualificationState.TIMEOUT
    if kind in {"download_failed"}:
        return HTTPQualificationState.DOWNLOAD_FAILED
    if kind in {"credential_rejected", "request_rejected", "job_failed", "submit_no_job_id"}:
        return HTTPQualificationState.REQUEST_FAILED
    if failure.state is ExecutionState.NO_ARTIFACT:
        return HTTPQualificationState.INVALID_ARTIFACT
    return HTTPQualificationState.REQUEST_FAILED


def qualify_http_provider(
    provider_id: str,
    output_path: str | Path,
    *,
    params: dict[str, Any] | None = None,
    timeout_s: float = 600.0,
    credential_source: CredentialSource | None = None,
    profile: HTTPProviderProfile | None = None,
    transport: Transport | None = None,
    adapter: ProviderQualification | None = None,
    auth_value: str = "",
    expected_checksum: str = "",
    checks: tuple[CheckRequirement, ...] = HTTP_VIDEO_CHECKS,
) -> HTTPQualificationOutcome:
    """Attempt HTTP qualification for one provider, and record how far it got."""
    chosen = profile or profile_for(provider_id)
    if chosen is None:
        return HTTPQualificationOutcome(
            provider_id=provider_id,
            state=HTTPQualificationState.NOT_ATTEMPTED,
            verdict=QualificationVerdict.NOT_RUN,
            reason=f"no declared HTTP profile for {provider_id}",
        )

    # ── 1. credentials ──
    credentials = resolve(
        provider_id, chosen.required_credentials, source=credential_source
    )
    # A provider that requires no credential is runnable. ``complete`` is False when
    # nothing was required, so guarding on it alone would block such a provider forever
    # with the nonsensical reason "credentials_missing:".
    if credentials.required and not credentials.complete:
        # Nothing was attempted, so nothing may be claimed about the provider.
        return HTTPQualificationOutcome(
            provider_id=provider_id,
            state=HTTPQualificationState.CREDENTIAL_MISSING,
            verdict=QualificationVerdict.BLOCKED_BY_CREDENTIAL,
            reason=f"credentials_missing:{','.join(credentials.missing)}",
            credentials=credentials,
            state_path=(HTTPQualificationState.INITIAL,
                        HTTPQualificationState.CREDENTIAL_MISSING),
        )

    path: tuple[HTTPQualificationState, ...] = (
        HTTPQualificationState.INITIAL, HTTPQualificationState.CREDENTIAL_CHECKED
    )
    request = QualificationRequest(
        provider_id=provider_id,
        output_path=str(output_path),
        params=dict(params or {}),
        timeout_s=timeout_s,
    )

    actor = adapter or HTTPProviderAdapter(
        chosen, credentials=credentials, auth_value=auth_value, transport=transport
    )

    # ── 2..4. submit -> poll -> download, with typed failure mapping ──
    try:
        availability = actor.available()
        if not availability.can_run:
            return HTTPQualificationOutcome(
                provider_id=provider_id,
                state=HTTPQualificationState.NOT_ATTEMPTED,
                verdict=QualificationVerdict.BLOCKED_BY_RUNTIME,
                reason=availability.reason,
                credentials=credentials,
                state_path=path,
            )
        actor.execute(request)
        path = path + (
            HTTPQualificationState.REQUEST_SUBMITTED,
            HTTPQualificationState.WAITING_RESULT,
            HTTPQualificationState.ARTIFACT_DOWNLOADED,
        )
    except JobTimeout as exc:
        return HTTPQualificationOutcome(
            provider_id=provider_id, state=HTTPQualificationState.TIMEOUT,
            verdict=QualificationVerdict.QUALIFICATION_FAILED,
            reason=f"timeout:{exc}", credentials=credentials, state_path=path,
        )
    except AdapterFailure as exc:
        return HTTPQualificationOutcome(
            provider_id=provider_id, state=_state_for(exc),
            verdict=_verdict_for(exc),
            reason=f"{exc.error_type or exc.state.value}:{exc.reason}",
            credentials=credentials, state_path=path,
        )
    except RuntimeUnavailable as exc:
        return HTTPQualificationOutcome(
            provider_id=provider_id, state=HTTPQualificationState.NOT_ATTEMPTED,
            verdict=QualificationVerdict.BLOCKED_BY_RUNTIME,
            reason=str(exc), credentials=credentials, state_path=path,
        )

    # ── 5..7. the P8 chain, owned by framework_local ──
    path = path + (HTTPQualificationState.VALIDATING,)
    qualification = qualify_local_provider(
        request, adapter=actor, expected_checksum=expected_checksum, checks=checks
    )
    if qualification.qualified:
        return HTTPQualificationOutcome(
            provider_id=provider_id, state=HTTPQualificationState.QUALIFIED,
            verdict=QualificationVerdict.QUALIFIED,
            credentials=credentials, qualification=qualification,
            state_path=path + (HTTPQualificationState.QUALIFIED,),
        )
    state = (
        HTTPQualificationState.INVALID_ARTIFACT
        if qualification.verdict is QualificationVerdict.INVALID_ARTIFACT
        else HTTPQualificationState.DOWNLOAD_FAILED
    )
    return HTTPQualificationOutcome(
        provider_id=provider_id, state=state, verdict=qualification.verdict,
        reason=qualification.reason, credentials=credentials,
        qualification=qualification, state_path=path,
    )


__all__ = [
    "HTTP_VIDEO_CHECKS",
    "HTTPQualificationOutcome",
    "HTTPQualificationState",
    "qualify_http_provider",
]
