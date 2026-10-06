"""P9.0 — The live qualification harness, and the ways it must not flatter us.

P8 proved that *if* a provider works, then its result is provable. It could not prove
any provider works. P9.0 is the entry point for closing that gap, and its whole
difficulty is that a harness can report a healthy fleet that does not exist.

Two things must never happen:

1. ``QUALIFIED`` without four proven links behind it.
2. A credential value reaching anything serialisable.

And one thing must stay visible:

    declared_profile  !=  observed reality

which is recorded as a **diff**, not collapsed into a boolean. A report whose only
output is ``PASS`` cannot be reviewed.

With no credentials configured — the current state — the harness must report
``QUALIFICATION_FAILED`` naming the missing credential, and ``NOT_RUN`` where nothing
was attempted. Neither is a pass, and ``UNKNOWN`` is not an acceptable answer to either,
because "we know exactly what we lack" is not the same as "we don't know".
"""

from __future__ import annotations

import ast
import dataclasses
import json
import pathlib

import pytest

from hevi.providers.facts import PROVIDER_CATALOGUE
from hevi.providers.runtime_specs import (
    RUNTIME_SPECS,
    HealthCheckKind,
    ProviderRuntimeSpec,
)
from hevi.qualification import (
    LinkName,
    LinkState,
    LiveQualificationRun,
    QualificationLink,
    QualificationVerdict,
    qualify_many,
    run_live_qualification,
)
from hevi.runtime.live import (
    Credential,
    CredentialMissing,
    EnvironmentCredentialProvider,
    HttpLiveDriver,
    LiveOutcome,
    LiveRuntimeStatus,
    LocalLiveDriver,
    QueueLiveDriver,
    StaticCredentialProvider,
    default_registry,
    redact,
)
from hevi.runtime.live.drivers import DriverRegistry

LIVE_DIR = pathlib.Path("hevi/runtime/live")
QUAL_DIR = pathlib.Path("hevi/qualification")

HTTP_SPEC = RUNTIME_SPECS.resolve("wan_2_7")
QUEUE_SPEC = RUNTIME_SPECS.resolve("veo3")
CLI_SPEC = RUNTIME_SPECS.resolve("wan_local")

CREDENTIALS = StaticCredentialProvider(
    {"FAL_API_KEY": "sk-live-DO-NOT-LEAK", "WAVESPEED_API_KEY": "ws-DO-NOT-LEAK"}
)


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _registry() -> DriverRegistry:
    """Three drivers, one per declared mechanism, all injected."""
    return DriverRegistry(
        drivers={
            HealthCheckKind.HTTP: HttpLiveDriver(
                credentials=CREDENTIALS,
                transport=lambda endpoint, headers, timeout: (200, b'{"ok":true}', 120),
            ),
            HealthCheckKind.QUEUE: QueueLiveDriver(
                credentials=CREDENTIALS,
                submit=lambda endpoint, headers: _Response({"request_id": "job-1"}),
                poll=lambda endpoint, headers, job: _Response(
                    {"video": {"url": "https://cdn.example/out.mp4"}}
                ),
            ),
            HealthCheckKind.CLI: LocalLiveDriver(
                credentials=CREDENTIALS,
                command=("wan2gp", "render"),
                runner=lambda command, timeout: (0, "/out/render.mp4"),
            ),
        }
    )


def _qualified(spec: ProviderRuntimeSpec, registry: DriverRegistry) -> LiveQualificationRun:
    return run_live_qualification(
        spec, registry=registry,
        acquisition_evidence_id="ev-1", production_receipt_id="rc-1",
        artifact_state="artifact_qualified",
    )


# ══════════════════════════════════════════════════════════════════════════
# HARNESS_EXISTS
# ══════════════════════════════════════════════════════════════════════════


def test_all_three_declared_mechanisms_have_a_driver():
    registry = _registry()
    for spec in (HTTP_SPEC, QUEUE_SPEC, CLI_SPEC):
        assert registry.driver_for(spec) is not None, (
            f"{spec.provider_id} declares {spec.health_check.value} but has no driver"
        )


def test_a_bare_host_target_is_usable():
    """`api.wavespeed.ai` is a host, not a URL; refusing it would refuse every provider."""
    result = HttpLiveDriver(
        credentials=CREDENTIALS, transport=lambda e, h, t: (200, b"ok", 5)
    ).attempt(HTTP_SPEC)
    assert result.ok is True


def test_default_registry_covers_every_declared_kind():
    registry = default_registry(credentials=CREDENTIALS)
    assert set(registry.kinds()) == set(HealthCheckKind)


# ══════════════════════════════════════════════════════════════════════════
# NO_FAKE_SUCCESS
# ══════════════════════════════════════════════════════════════════════════


def test_qualified_requires_all_four_links():
    for missing in LinkName:
        links = tuple(
            QualificationLink(name=name, state=LinkState.PROVEN, evidence_id=f"e-{name.value}")
            for name in LinkName
            if name is not missing
        )
        status = LiveRuntimeStatus(HTTP_SPEC.provider_id, LiveOutcome.OK, latency_ms=1,
                                   request_kind="http")
        with pytest.raises(ValueError, match="QUALIFIED_WITHOUT_ALL_LINKS"):
            LiveQualificationRun(
                provider_id=HTTP_SPEC.provider_id, declared_profile=HTTP_SPEC,
                verdict=QualificationVerdict.QUALIFIED, observed_runtime=status, links=links,
            )


def test_qualified_requires_an_observation():
    with pytest.raises(ValueError, match="QUALIFIED_WITHOUT_OBSERVATION"):
        LiveQualificationRun(
            provider_id=HTTP_SPEC.provider_id, declared_profile=HTTP_SPEC,
            verdict=QualificationVerdict.QUALIFIED,
        )


def test_a_proven_link_needs_something_to_point_at():
    with pytest.raises(ValueError, match="LINK_PROVEN_WITHOUT_EVIDENCE"):
        QualificationLink(name=LinkName.ARTIFACT, state=LinkState.PROVEN)


def test_live_call_alone_does_not_qualify():
    """The observation is one link of four. The rest must be earned."""
    run = run_live_qualification(HTTP_SPEC, registry=_registry())
    assert run.verdict is QualificationVerdict.QUALIFICATION_FAILED
    assert [link.state for link in run.links if link.name is LinkName.OBSERVATION] == [
        LinkState.PROVEN
    ]
    assert all(
        link.state is LinkState.PENDING
        for link in run.links
        if link.name is not LinkName.OBSERVATION
    )


def test_qualified_is_reachable_only_with_every_link():
    run = _qualified(HTTP_SPEC, _registry())
    assert run.verdict is QualificationVerdict.QUALIFIED
    assert all(link.holds for link in run.links)


def test_there_is_no_flag_that_forces_a_pass():
    """A harness that can be told to report success is a press release generator."""
    import inspect

    parameters = set(inspect.signature(run_live_qualification).parameters)
    for suspicious in ("force", "assume_pass", "trust", "skip_validation", "strict"):
        assert suspicious not in parameters


def test_missing_credential_fails_rather_than_passing():
    run = run_live_qualification(HTTP_SPEC, credentials=StaticCredentialProvider({}))
    assert run.verdict is QualificationVerdict.QUALIFICATION_FAILED
    assert "credential" in run.failure_reason.lower()


def test_nothing_attempted_is_not_run_not_failed():
    """`NOT_ATTEMPTED` and a failed attempt are different claims."""
    registry = DriverRegistry(
        drivers={HealthCheckKind.HTTP: HttpLiveDriver(
            credentials=CREDENTIALS, transport=lambda e, h, t: (200, b"ok", 1))}
    )
    run = run_live_qualification(CLI_SPEC, registry=registry)
    assert run.verdict is QualificationVerdict.NOT_RUN
    assert run.observed_runtime is None


def test_a_driver_reporting_not_attempted_is_not_run_not_failed():
    """The gap that let M4 through.

    The other not-run test used a registry with *no* CLI driver, so it took the
    "no driver for this mechanism" branch and never exercised a driver that exists,
    runs, and reports that it could not attempt anything. That is the branch a
    missing local command takes, and it must be NOT_RUN too.
    """
    registry = DriverRegistry(
        drivers={HealthCheckKind.CLI: LocalLiveDriver(credentials=CREDENTIALS)}
    )
    run = run_live_qualification(CLI_SPEC, registry=registry)
    assert run.verdict is QualificationVerdict.NOT_RUN, (
        "a driver with no configured command attempted nothing"
    )
    assert run.failure_reason
    assert run.observed_runtime is None


def test_a_driver_reporting_not_attempted_is_distinct_from_a_rejection():
    """NOT_ATTEMPTED is not a provider verdict; REJECTED is."""
    not_attempted = LocalLiveDriver(credentials=CREDENTIALS).attempt(CLI_SPEC)
    rejected = LocalLiveDriver(
        credentials=CREDENTIALS, command=("wan2gp",), runner=lambda c, t: (1, "")
    ).attempt(CLI_SPEC)
    assert not_attempted.status.outcome is LiveOutcome.NOT_ATTEMPTED
    assert rejected.status.outcome is LiveOutcome.REJECTED
    assert not_attempted.status.was_attempted is False
    assert rejected.status.was_attempted is True


def test_not_run_may_not_carry_an_observation():
    status = LiveRuntimeStatus("x", LiveOutcome.OK, latency_ms=1)
    with pytest.raises(ValueError, match="NOT_RUN_WITH_OBSERVATION"):
        LiveQualificationRun(
            provider_id=CLI_SPEC.provider_id, declared_profile=CLI_SPEC,
            verdict=QualificationVerdict.NOT_RUN, observed_runtime=status,
        )


def test_failure_requires_a_reason():
    with pytest.raises(ValueError, match="FAILED_WITHOUT_REASON"):
        LiveQualificationRun(
            provider_id=HTTP_SPEC.provider_id, declared_profile=HTTP_SPEC,
            verdict=QualificationVerdict.QUALIFICATION_FAILED,
        )


def test_http_rejection_is_not_success():
    driver = HttpLiveDriver(
        credentials=CREDENTIALS, transport=lambda e, h, t: (503, b"", 7)
    )
    result = driver.attempt(HTTP_SPEC)
    assert result.ok is False
    assert result.status.outcome is LiveOutcome.REJECTED
    assert result.status.status_code == 503


def test_exit_code_zero_without_an_artifact_is_not_success():
    driver = LocalLiveDriver(
        credentials=CREDENTIALS, command=("wan2gp",), runner=lambda c, t: (0, "")
    )
    result = driver.attempt(CLI_SPEC)
    assert result.ok is False
    assert "no artifact" in result.status.reason


def test_nonzero_exit_is_not_success():
    driver = LocalLiveDriver(
        credentials=CREDENTIALS, command=("wan2gp",), runner=lambda c, t: (1, "/out/a.mp4")
    )
    assert driver.attempt(CLI_SPEC).ok is False


def test_queue_without_a_job_id_is_not_success():
    driver = QueueLiveDriver(
        credentials=CREDENTIALS, submit=lambda e, h: _Response({}),
        poll=lambda e, h, j: _Response({"url": "https://cdn/x.mp4"}),
    )
    result = driver.attempt(QUEUE_SPEC)
    assert result.ok is False
    assert "job id" in result.status.reason


def test_queue_without_a_locator_is_not_success():
    driver = QueueLiveDriver(
        credentials=CREDENTIALS, submit=lambda e, h: _Response({"request_id": "j1"}),
        poll=lambda e, h, j: _Response({"status": "completed"}),
    )
    assert driver.attempt(QUEUE_SPEC).ok is False


def test_successful_live_call_must_record_a_latency():
    with pytest.raises(ValueError, match="LIVE_OK_WITHOUT_LATENCY"):
        LiveRuntimeStatus("x", LiveOutcome.OK)


def test_a_batch_keeps_its_failures():
    """A batch that dropped failures would report a healthier fleet than exists."""
    runs = qualify_many((HTTP_SPEC, QUEUE_SPEC, CLI_SPEC))
    assert len(runs) == 3
    assert all(r.verdict is not QualificationVerdict.QUALIFIED for r in runs)


# ══════════════════════════════════════════════════════════════════════════
# NO_CREDENTIAL_IN_FACTS
# ══════════════════════════════════════════════════════════════════════════


def test_running_the_harness_does_not_touch_the_catalogue():
    before = PROVIDER_CATALOGUE.to_dict()
    qualify_many((HTTP_SPEC, QUEUE_SPEC, CLI_SPEC), registry=_registry(),
                 credentials=CREDENTIALS)
    assert PROVIDER_CATALOGUE.to_dict() == before


def test_live_modules_never_import_the_catalogue_or_policy():
    for path in sorted(LIVE_DIR.glob("*.py")) + sorted(QUAL_DIR.glob("live_*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.endswith("facts"), f"{path.name} imports the catalogue"
                assert "provider_policy" not in node.module
                assert "production.p7" not in node.module


def test_no_credential_value_is_written_into_any_record():
    runs = qualify_many((HTTP_SPEC, QUEUE_SPEC, CLI_SPEC), registry=_registry(),
                        credentials=CREDENTIALS)
    blob = json.dumps([r.to_dict() for r in runs])
    for secret in CREDENTIALS._values.values():
        assert secret not in blob, f"{secret!r} reached a serialised record"


def test_credential_names_may_be_recorded_but_not_values():
    run = _qualified(HTTP_SPEC, _registry())
    payload = json.dumps(run.to_dict())
    assert "WAVESPEED_API_KEY" in payload, "the *name* is legitimate to record"
    assert "ws-DO-NOT-LEAK" not in payload


def test_credentials_do_not_leak_through_failure_reasons():
    driver = HttpLiveDriver(
        credentials=CREDENTIALS,
        transport=lambda e, h, t: (_ for _ in ()).throw(
            RuntimeError(f"connect failed for {e}?api_key=ws-DO-NOT-LEAK")
        ),
    )
    result = driver.attempt(HTTP_SPEC)
    assert "ws-DO-NOT-LEAK" not in result.status.reason
    assert "***" in result.status.reason


# ══════════════════════════════════════════════════════════════════════════
# NO_CREDENTIAL_IN_RECEIPT
# ══════════════════════════════════════════════════════════════════════════


def test_credential_redacts_in_every_rendering():
    credential = Credential("FAL_API_KEY", "sk-live-SECRET-VALUE")
    assert "sk-live-SECRET-VALUE" not in repr(credential)
    assert "sk-live-SECRET-VALUE" not in str(credential)
    assert "sk-live-SECRET-VALUE" not in json.dumps(credential.to_dict())
    assert "sk-live-SECRET-VALUE" not in f"{credential}"
    assert credential.to_dict()["value"] == "***"


@pytest.mark.parametrize(
    "text",
    [
        "https://x/y?api_key=sk-abcdef123&z=1",
        "Authorization: Bearer abc.def.ghi",
        "Bearer sk-live-9999 alone",
        "sk-proj-ABCDEFGHIJKLMNOP here",
        "connection to sk-live-SECRET-VALUE refused",
    ],
)
def test_redact_removes_secret_shapes(text):
    redacted = redact(text)
    for secret in ("sk-abcdef123", "abc.def.ghi", "sk-live-9999",
                   "sk-proj-ABCDEFGHIJKLMNOP", "sk-live-SECRET-VALUE"):
        assert secret not in redacted


def test_redact_preserves_useful_context():
    assert "api_key=***" in redact("https://x/y?api_key=sk-abcdef123")
    assert redact("http 503 Service Unavailable") == "http 503 Service Unavailable"


def test_a_non_secret_env_name_is_refused_as_a_credential():
    for name in ("PATH", "HOME", "SHELL"):
        with pytest.raises(ValueError, match="CREDENTIAL_NAME_NOT_A_SECRET"):
            Credential(name, "/usr/bin")


def test_missing_credentials_name_only_the_name():
    provider = EnvironmentCredentialProvider({})
    assert provider.missing(("FAL_API_KEY", "WAVESPEED_API_KEY")) == (
        "FAL_API_KEY", "WAVESPEED_API_KEY",
    )
    with pytest.raises(CredentialMissing) as excinfo:
        provider.require(("FAL_API_KEY",))
    assert "FAL_API_KEY" in str(excinfo.value)


def test_qualification_run_declares_no_credential_field():
    names = {f.name for f in dataclasses.fields(LiveQualificationRun)}
    for forbidden in ("token", "secret", "api_key", "credential", "password"):
        assert forbidden not in names


def test_live_status_carries_names_not_values():
    status = LiveRuntimeStatus(
        HTTP_SPEC.provider_id, LiveOutcome.OK, latency_ms=10,
        credential_names=("WAVESPEED_API_KEY",),
    )
    payload = json.dumps(status.to_dict())
    assert "WAVESPEED_API_KEY" in payload
    assert "ws-DO-NOT-LEAK" not in payload


# ══════════════════════════════════════════════════════════════════════════
# DECLARED_VS_OBSERVED_DIFF
# ══════════════════════════════════════════════════════════════════════════


def test_the_diff_is_recorded_even_when_the_declaration_holds():
    run = _qualified(HTTP_SPEC, _registry())
    assert run.differences, "a comparison must always be recorded"
    assert run.agrees_with_declaration is True
    assert run.disagreements == ()


def test_a_missing_credential_shows_as_a_disagreement():
    """The bug this guards: echoing the declaration made the diff compare it to itself."""
    run = run_live_qualification(QUEUE_SPEC, credentials=StaticCredentialProvider({}))
    presence = [d for d in run.differences if d.field_name == "credentials_present"]
    assert presence, "credential presence must be compared"
    assert presence[0].agrees is False
    assert presence[0].declared is True
    assert presence[0].observed is False


def test_the_diff_names_the_mechanism_that_was_used():
    run = run_live_qualification(HTTP_SPEC, credentials=StaticCredentialProvider({}))
    health = next(d for d in run.differences if d.field_name == "health_check")
    assert health.declared == "http"
    assert health.observed == "http"


def test_a_failed_live_call_disagrees_with_the_declaration():
    registry = DriverRegistry(
        drivers={HealthCheckKind.HTTP: HttpLiveDriver(
            credentials=CREDENTIALS, transport=lambda e, h, t: (503, b"", 3))}
    )
    run = run_live_qualification(HTTP_SPEC, registry=registry)
    outcome = next(d for d in run.differences if d.field_name == "live_outcome")
    assert outcome.agrees is False
    assert outcome.observed == "rejected"
    assert run.disagreements


def test_diff_report_is_human_readable():
    run = run_live_qualification(QUEUE_SPEC, credentials=StaticCredentialProvider({}))
    report = run.diff_report()
    assert "declared" in report and "observed" in report
    assert "!=" in report


def test_serialised_run_carries_the_diff():
    run = _qualified(HTTP_SPEC, _registry())
    payload = json.loads(json.dumps(run.to_dict()))
    assert payload["differences"]
    assert payload["agrees_with_declaration"] is True
    assert payload["credential_values"] == "***"


# ══════════════════════════════════════════════════════════════════════════
# boundary: observation is still not fact
# ══════════════════════════════════════════════════════════════════════════


def test_live_status_carries_no_provider_fact():
    names = {f.name for f in dataclasses.fields(LiveRuntimeStatus)}
    for forbidden in ("locality", "license", "license_class", "capabilities",
                      "quality", "rank", "eligible"):
        assert forbidden not in names


def test_live_run_carries_no_provider_fact():
    names = {f.name for f in dataclasses.fields(LiveQualificationRun)}
    for forbidden in ("locality", "license_class", "capabilities", "quality"):
        assert forbidden not in names


def test_live_modules_never_name_run_state():
    for path in sorted(LIVE_DIR.glob("*.py")) + sorted(QUAL_DIR.glob("live_*.py")):
        identifiers = {
            n.id for n in ast.walk(ast.parse(path.read_text())) if isinstance(n, ast.Name)
        } | {
            n.attr for n in ast.walk(ast.parse(path.read_text()))
            if isinstance(n, ast.Attribute)
        }
        assert "RunState" not in identifiers, f"{path.name} references RunState"
        assert "PRODUCED" not in identifiers


def test_a_profile_mismatch_is_refused():
    other = RUNTIME_SPECS.resolve("veo3")
    with pytest.raises(ValueError, match="LIVE_RUN_PROFILE_MISMATCH"):
        LiveQualificationRun(
            provider_id="wan_2_7", declared_profile=other,
        )


def test_pre_existing_qualification_authority_is_intact():
    """`hevi/qualification` was already an authority; P9.0 is additive."""
    import hevi.qualification as qualification

    for name in ("MediaValidation", "validate_media"):
        assert hasattr(qualification, name), f"pre-existing export {name} went missing"
    import hevi.qualification.framework as framework

    assert hasattr(framework, "discover_reports")
    assert hasattr(framework, "write_reports")
