"""W5 gates: secret-free definitions, lifecycle, sandbox, admission."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hevi.creative.layer4.endpoint_lifecycle import (
    AuthMode,
    CapabilityDeclaration,
    CapabilityRequirement,
    DeclarativeEndpointDefinition,
    EndpointError,
    EndpointState,
    SyncMode,
    bump_version,
    check_capability,
    disable,
    enable,
    export_definition,
    import_definition,
    mark_validated,
    preview_request,
    preview_result,
    promote_test_to_production,
    quarantine_test_artifact,
    record_trial,
    validate_definition,
)


def _definition(**kw) -> DeclarativeEndpointDefinition:
    args: dict = {
        "name": "example-video",
        "provider_family": "example",
        "base_url": "https://provider.example/v1/generate",
        "auth_mode": AuthMode.API_KEY_HEADER,
        "headers_template": {"X-API-Key": "{$SECRET:example_key}"},
        "request_schema": {"properties": {"prompt": {}, "duration_s": {}}},
        "request_template": '{"prompt": "{{prompt}}"}',
        "sync_mode": SyncMode.ASYNC_JOB,
        "job_id_path": "job.id",
        "poll_path_template": "https://provider.example/v1/jobs/{{job_id}}",
        "status_path": "job.status",
        "success_states": ("succeeded",),
        "failure_states": ("failed",),
        "artifact_url_path": "job.video_url",
        "error_code_path": "error.code",
        "error_message_path": "error.message",
        "capability": CapabilityDeclaration(
            media_type="video",
            durations_s=(5, 10),
            resolutions=("720p",),
            max_references=2,
            async_job=True,
        ),
        "secret_references": ("example_key",),
    }
    args.update(kw)
    return DeclarativeEndpointDefinition(**args)


def test_validate_happy_path() -> None:
    report = validate_definition(_definition())
    assert report.valid is True
    assert report.findings == ()


def test_plaintext_secret_forbidden_at_construction() -> None:
    with pytest.raises(ValidationError, match="ENDPOINT_PLAINTEXT_SECRET_FORBIDDEN"):
        _definition(headers_template={"Authorization": "Bearer real-token-value-123"})
    with pytest.raises(ValidationError, match="ENDPOINT_PLAINTEXT_SECRET_FORBIDDEN"):
        _definition(headers_template={"X-API-Key": "sk-abcdefgh1234567890"})
    assert "{$SECRET:example_key}" in _definition().headers_template["X-API-Key"]


def test_validate_finds_lifecycle_gaps() -> None:
    report = validate_definition(
        _definition(
            sync_mode=SyncMode.ASYNC_JOB,
            job_id_path="",
            success_states=("done",),
            failure_states=("done",),
            secret_references=(),
            request_template='{"prompt": "{{mystery}}"}',
        )
    )
    assert report.valid is False
    codes = {finding.code for finding in report.findings}
    assert "ENDPOINT_ASYNC_NEEDS_JOB_ID_PATH" in codes
    assert "ENDPOINT_STATE_SETS_OVERLAP" in codes
    assert "ENDPOINT_AUTH_NEEDS_SECRET_REFERENCE" in codes
    assert "ENDPOINT_SLOT_UNDECLARED" in codes


def test_lifecycle_gates() -> None:
    draft = _definition()
    assert draft.state is EndpointState.DRAFT
    validated = mark_validated(draft)
    assert validated.state is EndpointState.VALIDATED
    with pytest.raises(EndpointError, match="ENDPOINT_ENABLE_ILLEGAL_FROM"):
        enable(validated)
    tested = record_trial(validated, outcome="success", provider_job_ref="job-9")
    assert tested.state is EndpointState.TESTED
    assert "job-9" in tested.trial_summary
    enabled = enable(tested)
    assert enabled.state is EndpointState.ENABLED
    disabled = disable(enabled)
    assert disabled.state is EndpointState.DISABLED
    revalidated = mark_validated(disabled)
    assert revalidated.state is EndpointState.VALIDATED
    with pytest.raises(EndpointError, match="ENDPOINT_VALIDATION_FAILED"):
        mark_validated(_definition(sync_mode=SyncMode.ASYNC_JOB, job_id_path=""))
    with pytest.raises(EndpointError, match="ENDPOINT_TRIAL_OUTCOME_UNKNOWN"):
        record_trial(validated, outcome="maybe")


def test_preview_request_never_sends_or_bills() -> None:
    preview = preview_request(_definition(), {"prompt": "雨夜街景", "duration_s": 5})
    assert preview.sent is False
    assert preview.method == "POST"
    assert preview.url == "https://provider.example/v1/generate"
    assert preview.headers == {"X-API-Key": "{$SECRET:example_key}"}
    assert preview.body == {"prompt": "雨夜街景", "duration_s": 5}


def test_preview_result_extracts_without_persisting() -> None:
    result = preview_result(
        _definition(),
        {
            "job": {"id": "job-7", "status": "succeeded", "video_url": "https://cdn/x.mp4"},
            "error": {"code": None, "message": None},
        },
    )
    assert result.job_id == "job-7"
    assert result.status == "succeeded"
    assert result.artifact_url == "https://cdn/x.mp4"
    assert result.persisted is False
    failed = preview_result(_definition(), {"error": {"code": "429", "message": "busy"}})
    assert failed.error_code == "429"
    assert failed.job_id is None


def test_quarantine_and_explicit_promote() -> None:
    quarantine = quarantine_test_artifact(test_artifact_id="t-art-1", trial_ref="trial-1")
    assert quarantine.test_only is True
    assert quarantine.production_artifact is False
    with pytest.raises(EndpointError, match="ENDPOINT_PROMOTE_NEEDS_EXPLICIT_CONFIRMATION"):
        promote_test_to_production(quarantine, user_confirmed=False)
    promoted = promote_test_to_production(quarantine, user_confirmed=True)
    assert promoted.production_artifact is True


def test_capability_admission() -> None:
    definition = _definition()
    ok = check_capability(definition, CapabilityRequirement(media_type="video", duration_s=5))
    assert ok.admitted is True
    assert ok.reasons == ()
    bad = check_capability(
        definition,
        CapabilityRequirement(
            media_type="video",
            duration_s=30,
            resolution="4K",
            references=5,
            start_end_frame=True,
            native_audio=True,
        ),
    )
    assert bad.admitted is False
    assert len(bad.reasons) == 5
    assert any("duration 30s" in reason for reason in bad.reasons)


def test_export_import_roundtrip_resets_to_draft() -> None:
    enabled = enable(record_trial(mark_validated(_definition()), outcome="success"))
    exported = export_definition(enabled)
    assert "SECRET" not in str(exported.get("secret_references"))
    imported = import_definition(exported)
    assert imported.state is EndpointState.DRAFT
    assert imported.version == enabled.version
    assert imported.trial_summary == ""
    assert imported.base_url == "https://provider.example/v1/generate"


def test_version_bump_restarts_lifecycle() -> None:
    enabled = enable(record_trial(mark_validated(_definition()), outcome="success"))
    bumped = bump_version(enabled)
    assert bumped.version == 2
    assert bumped.state is EndpointState.DRAFT
