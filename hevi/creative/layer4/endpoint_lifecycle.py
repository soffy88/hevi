"""Declarative provider endpoint lifecycle (Gap Closure W5, ARC-M06/M07).

A provider endpoint that fits the generic contract enters production
without a new HEVI Python provider class: one
:class:`DeclarativeEndpointDefinition` describes submit/poll/extract
semantics, capability claims, pricing metadata, and secret *references*.
Lifecycle: DRAFT -> VALIDATED -> TESTED -> ENABLED (DISABLED off-ramp).

Hard boundaries:

- Definitions never carry plaintext secrets: auth positions accept only
  ``{$SECRET:<name>}`` references into the HEVI credential authority.
  Anything else there refuses at construction.
- Test calls never touch production state: previews render without
  sending; trial artifacts are quarantined as test-only; promotion to
  production needs an explicit flag.
- Declaring a capability proves nothing: :func:`check_capability`
  matches requirements against the declaration before admission.

Role split (one module, documented roles):

- OPRIM role (adapters, not here): single request/poll/extract HTTP calls
  execute :func:`preview_request` plans with caller-resolved secrets.
- OBASE role: generic HTTP/auth shapes (:class:`AuthMode`, header rules).
- OSKILL role: :func:`validate_definition`, :func:`check_capability` —
  deterministic matching/validation.
- OSERVI role: durable submit/poll/download runs on top (see W3
  provider_execution; endpoint definitions supply its parameters).
- HEVI_LAYER4 role: endpoint/project configuration surfaces persist and
  render these definitions.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

SECRET_REF_RE = re.compile(r"^\{\$SECRET:[A-Za-z0-9_.-]{1,64}\}$")
TEMPLATE_SLOT_RE = re.compile(r"\{\{([a-zA-Z0-9_.]+)\}\}")
SECRET_VALUE_RE = re.compile(r"sk-[A-Za-z0-9]{16,}|[A-Za-z0-9]{32,}")


class AuthMode(StrEnum):
    NONE = "none"
    API_KEY_HEADER = "api_key_header"
    API_KEY_QUERY = "api_key_query"
    BEARER = "bearer"


class SyncMode(StrEnum):
    SYNC = "sync"
    ASYNC_JOB = "async_job"


class EndpointState(StrEnum):
    DRAFT = "draft"
    VALIDATED = "validated"
    TESTED = "tested"
    ENABLED = "enabled"
    DISABLED = "disabled"


class EndpointError(ValueError):
    """Refusal with a stable machine code."""


class CapabilityDeclaration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    media_type: str = Field(min_length=1)
    durations_s: tuple[int, ...] = ()
    resolutions: tuple[str, ...] = ()
    max_references: int = 0
    start_end_frame: bool = False
    native_audio: bool = False
    async_job: bool = True


class PricingMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    currency: str = "USD"
    per_video_second: float = 0.0
    per_image: float = 0.0
    per_1k_units: float = 0.0


class DeclarativeEndpointDefinition(BaseModel):
    """The protocol slot: URL shapes, auth convention, field semantics."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    provider_family: str = Field(min_length=1)
    version: int = Field(ge=1, default=1)
    state: EndpointState = EndpointState.DRAFT
    base_url: str = Field(min_length=1)
    method: str = "POST"
    auth_mode: AuthMode = AuthMode.API_KEY_HEADER
    headers_template: dict[str, str] = Field(default_factory=dict)
    request_schema: dict[str, Any] = Field(default_factory=dict)
    request_template: str = ""
    sync_mode: SyncMode = SyncMode.ASYNC_JOB
    job_id_path: str = ""
    poll_path_template: str = ""
    status_path: str = ""
    success_states: tuple[str, ...] = ()
    failure_states: tuple[str, ...] = ()
    artifact_url_path: str = ""
    error_code_path: str = ""
    error_message_path: str = ""
    rate_limit_rpm: int = 0
    max_concurrency: int = 1
    capability: CapabilityDeclaration
    pricing: PricingMetadata = Field(default_factory=PricingMetadata)
    secret_references: tuple[str, ...] = ()
    trial_summary: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def _no_plaintext_secrets(self) -> DeclarativeEndpointDefinition:
        for header, value in self.headers_template.items():
            lowered = header.lower()
            is_auth_position = (
                self.auth_mode is not AuthMode.NONE
                and lowered in {"authorization", "x-api-key", "api-key"}
            ) or lowered in {"authorization", "x-api-key", "api-key"}
            if is_auth_position and not SECRET_REF_RE.match(value):
                raise EndpointError("ENDPOINT_PLAINTEXT_SECRET_FORBIDDEN")
            if SECRET_VALUE_RE.search(value):
                raise EndpointError("ENDPOINT_PLAINTEXT_SECRET_FORBIDDEN")
        for secret in self.secret_references:
            if not secret or len(secret) > 64:
                raise EndpointError("ENDPOINT_SECRET_REFERENCE_INVALID")
        return self

    def touch(self, **updates: Any) -> DeclarativeEndpointDefinition:
        return self.model_copy(update={**updates, "updated_at": datetime.now(UTC)})


class ValidationFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    blocking: bool = True


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    valid: bool
    findings: tuple[ValidationFinding, ...] = ()


def _slots(template: str) -> set[str]:
    return set(TEMPLATE_SLOT_RE.findall(template))


def validate_definition(definition: DeclarativeEndpointDefinition) -> ValidationReport:
    """Static validation: schema/template coherence, lifecycle completeness."""

    findings: list[ValidationFinding] = []
    if definition.method not in {"GET", "POST", "PUT", "PATCH"}:
        findings.append(
            ValidationFinding(
                code="ENDPOINT_METHOD_UNSUPPORTED",
                message=f"method {definition.method} is not an endpoint method",
            )
        )
    schema_keys = set(definition.request_schema.get("properties", {}).keys())
    for slot in sorted(_slots(definition.request_template)):
        root = slot.split(".")[0]
        if root not in schema_keys and root not in {"secret", "param"}:
            findings.append(
                ValidationFinding(
                    code="ENDPOINT_SLOT_UNDECLARED",
                    message=f"template slot {slot} has no schema property",
                )
            )
    if definition.sync_mode is SyncMode.ASYNC_JOB:
        for field, code in (
            (definition.job_id_path, "ENDPOINT_ASYNC_NEEDS_JOB_ID_PATH"),
            (definition.poll_path_template, "ENDPOINT_ASYNC_NEEDS_POLL_TEMPLATE"),
            (definition.status_path, "ENDPOINT_ASYNC_NEEDS_STATUS_PATH"),
        ):
            if not field:
                findings.append(ValidationFinding(code=code, message=code.lower()))
        if not definition.success_states:
            findings.append(
                ValidationFinding(
                    code="ENDPOINT_ASYNC_NEEDS_SUCCESS_STATES",
                    message="async endpoints must declare success states",
                )
            )
        overlap = set(definition.success_states) & set(definition.failure_states)
        if overlap:
            findings.append(
                ValidationFinding(
                    code="ENDPOINT_STATE_SETS_OVERLAP",
                    message=f"states in both success and failure: {sorted(overlap)}",
                )
            )
    if definition.auth_mode is not AuthMode.NONE and not definition.secret_references:
        findings.append(
            ValidationFinding(
                code="ENDPOINT_AUTH_NEEDS_SECRET_REFERENCE",
                message="auth mode set but no secret reference declared",
            )
        )
    if definition.capability.max_references < 0 or definition.rate_limit_rpm < 0:
        findings.append(
            ValidationFinding(code="ENDPOINT_NEGATIVE_LIMIT", message="limits must be >= 0")
        )
    blocking = [finding for finding in findings if finding.blocking]
    return ValidationReport(valid=not blocking, findings=tuple(findings))


def mark_validated(definition: DeclarativeEndpointDefinition) -> DeclarativeEndpointDefinition:
    report = validate_definition(definition)
    if not report.valid:
        raise EndpointError(
            "ENDPOINT_VALIDATION_FAILED:"
            + ",".join(finding.code for finding in report.findings if finding.blocking)
        )
    if definition.state not in (EndpointState.DRAFT, EndpointState.DISABLED):
        raise EndpointError(f"ENDPOINT_VALIDATE_ILLEGAL_FROM:{definition.state.value}")
    return definition.touch(state=EndpointState.VALIDATED)


def record_trial(
    definition: DeclarativeEndpointDefinition, *, outcome: str, provider_job_ref: str = ""
) -> DeclarativeEndpointDefinition:
    """Record a caller-executed billable trial; the trial itself runs outside."""

    if definition.state is not EndpointState.VALIDATED:
        raise EndpointError(f"ENDPOINT_TRIAL_ILLEGAL_FROM:{definition.state.value}")
    if outcome not in {"success", "failure"}:
        raise EndpointError("ENDPOINT_TRIAL_OUTCOME_UNKNOWN")
    summary = f"trial {outcome}" + (f" job={provider_job_ref}" if provider_job_ref else "")
    return definition.touch(state=EndpointState.TESTED, trial_summary=summary)


def enable(definition: DeclarativeEndpointDefinition) -> DeclarativeEndpointDefinition:
    if definition.state is not EndpointState.TESTED:
        raise EndpointError(f"ENDPOINT_ENABLE_ILLEGAL_FROM:{definition.state.value}")
    return definition.touch(state=EndpointState.ENABLED)


def disable(definition: DeclarativeEndpointDefinition) -> DeclarativeEndpointDefinition:
    if definition.state is EndpointState.DRAFT:
        raise EndpointError("ENDPOINT_DISABLE_ILLEGAL_FROM:draft")
    return definition.touch(state=EndpointState.DISABLED)


def bump_version(definition: DeclarativeEndpointDefinition) -> DeclarativeEndpointDefinition:
    """Material edits version the definition; the copy restarts at DRAFT."""

    return definition.touch(version=definition.version + 1, state=EndpointState.DRAFT)


class RequestPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    method: str
    url: str
    headers: dict[str, str]
    body: dict[str, Any]
    sent: bool = False


def _render_template(template: str, params: dict[str, Any]) -> str:
    rendered = template
    for slot in _slots(template):
        value = params
        for part in slot.split("."):
            value = value.get(part, "") if isinstance(value, dict) else ""
        rendered = rendered.replace("{{" + slot + "}}", str(value))
    return rendered


def preview_request(
    definition: DeclarativeEndpointDefinition, params: dict[str, Any]
) -> RequestPreview:
    """Render the wire request for human review. Never sends, never bills.

    Secret references stay symbolic (``{$SECRET:name}``); nothing resolves
    credentials here — resolution happens in the OPRIM adapter at call time.
    """

    body: dict[str, Any] = {}
    for key in definition.request_schema.get("properties", {}):
        if key in params:
            body[key] = params[key]
    return RequestPreview(
        method=definition.method,
        url=_render_template(definition.base_url, params),
        headers=dict(definition.headers_template),
        body=body,
        sent=False,
    )


class ResultPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str | None = None
    status: str | None = None
    artifact_url: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    persisted: bool = False


def _dig(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def preview_result(
    definition: DeclarativeEndpointDefinition, raw_response: dict[str, Any]
) -> ResultPreview:
    """Preview normalized extraction from a real supplier response sample.

    Check-response mode: validates taking paths against supplier data
    without sending anything and without persisting any artifact.
    """

    def _take(path: str) -> str | None:
        if not path:
            return None
        value = _dig(raw_response, path)
        return None if value is None else str(value)

    return ResultPreview(
        job_id=_take(definition.job_id_path),
        status=_take(definition.status_path),
        artifact_url=_take(definition.artifact_url_path),
        error_code=_take(definition.error_code_path),
        error_message=_take(definition.error_message_path),
        persisted=False,
    )


class TestQuarantine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    test_artifact_id: str
    test_only: bool = True
    production_artifact: bool = False
    trial_ref: str = ""


def quarantine_test_artifact(*, test_artifact_id: str, trial_ref: str = "") -> TestQuarantine:
    """Trial outputs are test-only by construction; promotion is explicit."""

    return TestQuarantine(test_artifact_id=test_artifact_id, trial_ref=trial_ref)


def promote_test_to_production(
    quarantine: TestQuarantine, *, user_confirmed: bool
) -> TestQuarantine:
    if not user_confirmed:
        raise EndpointError("ENDPOINT_PROMOTE_NEEDS_EXPLICIT_CONFIRMATION")
    return quarantine.model_copy(update={"test_only": False, "production_artifact": True})


class CapabilityRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    media_type: str
    duration_s: int | None = None
    resolution: str | None = None
    references: int = 0
    start_end_frame: bool = False
    native_audio: bool = False
    async_job: bool = True


class AdmissionVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    admitted: bool
    reasons: tuple[str, ...] = ()


def check_capability(
    definition: DeclarativeEndpointDefinition, requirement: CapabilityRequirement
) -> AdmissionVerdict:
    """Declaring a capability proves nothing: match before admission."""

    capability = definition.capability
    reasons: list[str] = []
    if capability.media_type != requirement.media_type:
        reasons.append(f"media {capability.media_type} != {requirement.media_type}")
    if (
        requirement.duration_s is not None
        and capability.durations_s
        and (requirement.duration_s not in capability.durations_s)
    ):
        reasons.append(f"duration {requirement.duration_s}s not in {list(capability.durations_s)}")
    if (
        requirement.resolution is not None
        and capability.resolutions
        and requirement.resolution not in capability.resolutions
    ):
        reasons.append(f"resolution {requirement.resolution} not declared")
    if requirement.references > capability.max_references:
        reasons.append(f"needs {requirement.references} refs, declares {capability.max_references}")
    if requirement.start_end_frame and not capability.start_end_frame:
        reasons.append("start/end frame not declared")
    if requirement.native_audio and not capability.native_audio:
        reasons.append("native audio not declared")
    if requirement.async_job and not capability.async_job:
        reasons.append("async job mode not declared")
    return AdmissionVerdict(admitted=not reasons, reasons=tuple(reasons))


def export_definition(definition: DeclarativeEndpointDefinition) -> dict[str, Any]:
    """Safe export: serializable and secret-free by construction."""

    return definition.model_dump(mode="json")


def import_definition(data: dict[str, Any]) -> DeclarativeEndpointDefinition:
    """Import resets to DRAFT: imported definitions prove nothing yet."""

    definition = DeclarativeEndpointDefinition.model_validate(data)
    return definition.touch(state=EndpointState.DRAFT, trial_summary="")


__all__ = [
    "AdmissionVerdict",
    "AuthMode",
    "CapabilityDeclaration",
    "CapabilityRequirement",
    "DeclarativeEndpointDefinition",
    "EndpointError",
    "EndpointState",
    "PricingMetadata",
    "RequestPreview",
    "ResultPreview",
    "SyncMode",
    "TestQuarantine",
    "ValidationFinding",
    "ValidationReport",
    "bump_version",
    "check_capability",
    "disable",
    "enable",
    "export_definition",
    "import_definition",
    "mark_validated",
    "preview_request",
    "preview_result",
    "promote_test_to_production",
    "quarantine_test_artifact",
    "record_trial",
    "validate_definition",
]
