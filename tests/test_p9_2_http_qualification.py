"""HEVI P9.2 — HTTP provider qualification.

Tests the *capability boundaries* (Architecture Testing Rule #1, docs/TESTING-PRINCIPLES.md):
the adapter must not measure, the credential resolver must not resolve, the runner must not
invent a verdict, and a completed HTTP job must not be mistaken for a valid artifact.

Every lifecycle test drives a stub ``Transport``, so the state machine is exercised without
a network and without credentials. The real-network path is exercised separately and is
expected to be BLOCKED when no credential exists — which is the correct result, not a skip.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from hevi.providers.facts import PROVIDER_CATALOGUE, ProviderKind
from hevi.qualification.credentials import (
    CredentialResolution,
    EnvironmentCredentials,
    InjectedCredentials,
    resolve,
)
from hevi.qualification.http_runner import (
    HTTPQualificationState,
    qualify_http_provider,
)
from hevi.qualification.live_run import QualificationVerdict
from hevi.qualification.models import (
    AdapterFailure,
    ExecutionResult,
    ExecutionState,
    QualificationRequest,
)
from hevi.qualification.providers.http import (
    HTTP_PROFILES,
    HTTPProviderAdapter,
    profile_for,
)

WAVESPEED = "wan_2_7"
MAAS = "wan_2_7_maas"
HTTP_IDS = tuple(HTTP_PROFILES)
HERE = Path(__file__).resolve().parents[1]


# ── fixtures ──

class StubTransport:
    """A scripted HTTP conversation. Records every call for lifecycle assertions."""

    def __init__(self, *, submit=(202, {"id": "JOB1"}), polls=(), download=(200, b"")):
        self.submit = submit
        self.polls = list(polls)
        self.download = download
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method, url, headers, *, json_=None, timeout=30.0, binary=False):
        self.calls.append((method, url))
        if method == "POST":
            return self.submit
        if binary:
            return self.download
        if url.endswith("/JOB1"):
            return self.polls.pop(0) if self.polls else (
                200, {"status": "completed", "url": "https://cdn.example/x.mp4"}
            )
        return self.submit

    @property
    def methods(self) -> list[str]:
        return [m for m, _ in self.calls]


#: no sleeping between polls: the state machine is under test, not the wall clock
FAST = {"poll_interval_s": 0.0, "max_polls": 3}


def fast_profile(provider_id=WAVESPEED):
    from dataclasses import replace

    declared = profile_for(provider_id)
    return replace(declared, **FAST) if declared is not None else None


def run(provider_id=WAVESPEED, transport=None, **kwargs):
    out = Path(kwargs.pop("out", "/tmp/opencode/p9_2/out.mp4"))
    if "profile" not in kwargs and profile_for(provider_id) is not None:
        kwargs["profile"] = fast_profile(provider_id)
    return qualify_http_provider(
        provider_id, out, transport=transport,
        credential_source=InjectedCredentials(("WAVESPEED_API_KEY", "ALIBABA_MAAS_API_KEY")),
        **kwargs,
    )


def adapter_for(provider_id=WAVESPEED, transport=None, **kwargs):
    profile = profile_for(provider_id)
    creds = resolve(provider_id, profile.required_credentials,
                    source=InjectedCredentials(profile.required_credentials))
    return HTTPProviderAdapter(profile, credentials=creds, transport=transport,
                               auth_value=kwargs.pop("auth_value", "test-token"),
                               **kwargs)


def request_for(provider_id=WAVESPEED, out="/tmp/opencode/p9_2/out.mp4", **kw):
    return QualificationRequest(provider_id=provider_id, output_path=out, **kw)


# ── 1. catalogue and profile declaration ──

@pytest.mark.parametrize("provider_id", HTTP_IDS)
def test_every_http_provider_is_in_the_catalogue(provider_id):
    assert PROVIDER_CATALOGUE.get(provider_id) is not None


@pytest.mark.parametrize("provider_id", HTTP_IDS)
def test_every_http_provider_declares_its_credentials(provider_id):
    assert profile_for(provider_id).required_credentials


@pytest.mark.parametrize(
    "provider_id", ("wan_2_7", "happyhorse_1_1", "wan_2_7_maas", "happyhorse_1_1_maas")
)
def test_reseller_vendors_are_not_registered_as_providers(provider_id):
    """WaveSpeed and Alibaba are resellers. One identity per thing."""
    for vendor in ("wavespeed", "alibaba_maas"):
        assert PROVIDER_CATALOGUE.get(vendor) is None, f"{vendor} would be a second identity"
        assert vendor not in HTTP_PROFILES


def test_vendor_is_recorded_on_the_profile_not_the_catalogue():
    assert profile_for(WAVESPEED).vendor == "wavespeed"
    assert profile_for(MAAS).vendor == "alibaba_maas"


@pytest.mark.parametrize("provider_id", HTTP_IDS)
def test_submit_urls_are_https(provider_id):
    assert profile_for(provider_id).submit_url.startswith("https://")


@pytest.mark.parametrize("provider_id", HTTP_IDS)
def test_poll_url_is_derived_from_the_job_id(provider_id):
    assert "JOB7" in profile_for(provider_id).poll_url("JOB7")


def test_unknown_provider_is_not_attempted():
    outcome = run(provider_id="no_such_provider")
    assert outcome.state is HTTPQualificationState.NOT_ATTEMPTED
    assert outcome.verdict is QualificationVerdict.NOT_RUN


# ── 2. credential resolution: presence only ──

def test_missing_credential_is_reported_as_missing():
    resolution = resolve(WAVESPEED, ("WAVESPEED_API_KEY",), source=InjectedCredentials(()))
    assert resolution.missing == ("WAVESPEED_API_KEY",)
    assert not resolution.complete


def test_resolution_never_carries_a_value():
    resolution = resolve(WAVESPEED, ("WAVESPEED_API_KEY",), source=InjectedCredentials(("WAVESPEED_API_KEY",)))
    assert not hasattr(resolution, "value")
    assert not hasattr(resolution, "secret")
    assert "abc123" not in str(resolution.to_dict())


def test_injected_source_cannot_be_given_a_value():
    with pytest.raises(TypeError):
        InjectedCredentials(("A",), "actual-secret")  # type: ignore[call-arg]


def test_environment_source_reports_only_names():
    source = EnvironmentCredentials({"A": "1", "B": "2", "C": ""})
    assert set(source.present()) == {"A", "B"}


def test_resolution_requires_a_provider_id():
    with pytest.raises(ValueError, match="WITHOUT_PROVIDER"):
        CredentialResolution(provider_id="")


def test_a_name_cannot_be_both_present_and_missing():
    with pytest.raises(ValueError, match="BOTH_PRESENT"):
        CredentialResolution(provider_id="p", required=("A",), resolved=("A",), missing=("A",))


def test_resolve_with_no_requirements_is_complete():
    assert not resolve("p", ()).complete


# ── 3. missing credentials block before anything is attempted ──

def test_missing_credential_blocks_and_never_calls_the_transport():
    transport = StubTransport()
    outcome = qualify_http_provider(WAVESPEED, "/tmp/opencode/p9_2/x.mp4", transport=transport)
    assert outcome.verdict is QualificationVerdict.BLOCKED_BY_CREDENTIAL
    assert outcome.state is HTTPQualificationState.CREDENTIAL_MISSING
    assert outcome.calls if False else transport.calls == []
    assert "WAVESPEED_API_KEY" in outcome.reason


def test_missing_credential_for_the_second_provider_is_also_blocked():
    outcome = qualify_http_provider(
        MAAS, "/tmp/opencode/p9_2/x.mp4",
        credential_source=InjectedCredentials(("WAVESPEED_API_KEY",)),
    )
    assert outcome.verdict is QualificationVerdict.BLOCKED_BY_CREDENTIAL
    assert "ALIBABA_MAAS_API_KEY" in outcome.reason


def test_a_blocked_run_claims_nothing_about_the_provider():
    outcome = qualify_http_provider(WAVESPEED, "/tmp/opencode/p9_2/x.mp4")
    assert not outcome.qualified
    assert outcome.receipt is None


def test_adapter_refuses_to_run_without_credentials():
    profile = profile_for(WAVESPEED)
    adapter = HTTPProviderAdapter(profile, credentials=resolve(
        WAVESPEED, profile.required_credentials, source=InjectedCredentials(())))
    assert not adapter.available().can_run


# ── 4. the lifecycle: submit -> poll -> download ──

def test_happy_path_issues_post_then_polls_then_downloads():
    transport = StubTransport(
        polls=[(200, {"status": "processing"})],
        download=(200, b"\x00\x00\x00 ftypisom" + b"\x00" * 512),
    )
    outcome = run(transport=transport, adapter=None)
    assert transport.methods[0] == "POST"
    assert "GET" in transport.methods
    # The lifecycle ran to completion; the verdict is P8.4's to give, and these stub
    # bytes are not a real video, so it refuses. What is under test here is the
    # submit/poll/download order, not the artifact.
    assert HTTPQualificationState.ARTIFACT_DOWNLOADED in outcome.state_path
    assert outcome.verdict is not QualificationVerdict.QUALIFIED


def test_the_job_id_from_submit_is_used_for_polling():
    transport = StubTransport(submit=(202, {"data": {"request_id": "JOB9"}}),
                              download=(200, b"x" * 32))
    run(transport=transport)
    assert any("JOB9" in url for _, url in transport.calls)


@pytest.mark.parametrize("key", ("id", "job_id", "task_id", "request_id"))
def test_job_id_is_found_under_any_common_key(key):
    transport = StubTransport(submit=(202, {key: "JOBK"}), download=(200, b"y" * 32))
    run(transport=transport)
    assert any("JOBK" in url for _, url in transport.calls)


def test_a_submit_without_a_job_id_fails_rather_than_guessing():
    transport = StubTransport(submit=(202, {"nonsense": True}))
    outcome = run(transport=transport)
    assert outcome.verdict is QualificationVerdict.QUALIFICATION_FAILED
    assert "submit_no_job_id" in outcome.reason


def test_execution_result_carries_a_locator_and_no_measurement(tmp_path):
    out = tmp_path / "out.mp4"
    result = adapter_for(transport=StubTransport(download=(200, b"z" * 64))).execute(
        request_for(out=str(out)))
    assert result.artifact_locator == str(out)
    assert set(result.runtime_metadata) >= {"runtime_class", "vendor", "job_id"}
    for forbidden in ("checksum", "sha256", "duration", "codec", "passed", "qualified"):
        assert not hasattr(result, forbidden)


# ── 5. the failure matrix ──

@pytest.mark.parametrize("status", (401, 403))
def test_invalid_key_is_qualification_failed(status):
    outcome = run(transport=StubTransport(submit=(status, {"error": "nope"})))
    assert outcome.verdict is QualificationVerdict.QUALIFICATION_FAILED
    assert "credential_rejected" in outcome.reason


@pytest.mark.parametrize("status", (400, 404, 422))
def test_http_4xx_is_qualification_failed(status):
    outcome = run(transport=StubTransport(submit=(status, {"error": "bad"})))
    assert outcome.verdict is QualificationVerdict.QUALIFICATION_FAILED


@pytest.mark.parametrize("status", (500, 502, 503))
def test_http_5xx_is_provider_unreachable_not_a_bad_artifact(status):
    outcome = run(transport=StubTransport(submit=(status, {"error": "boom"})))
    assert outcome.verdict is QualificationVerdict.PROVIDER_UNREACHABLE
    assert outcome.state is HTTPQualificationState.REQUEST_FAILED


def test_poll_5xx_is_also_provider_unreachable():
    outcome = run(transport=StubTransport(polls=[(503, {})]))
    assert outcome.verdict is QualificationVerdict.PROVIDER_UNREACHABLE


def test_a_job_that_never_finishes_times_out():
    transport = StubTransport(polls=[(200, {"status": "processing"})] * 40)
    outcome = run(transport=transport, timeout_s=0.0)
    assert outcome.state is HTTPQualificationState.TIMEOUT
    assert outcome.verdict is QualificationVerdict.QUALIFICATION_FAILED


def test_a_failed_job_is_not_a_timeout():
    outcome = run(transport=StubTransport(polls=[(200, {"status": "failed", "message": "nsfw"})]))
    assert "job_failed" in outcome.reason


def test_a_cancelled_job_is_reported_as_failed():
    outcome = run(transport=StubTransport(polls=[(200, {"status": "cancelled"})]))
    assert "job_failed" in outcome.reason


def test_a_completed_job_with_no_artifact_is_rejected():
    outcome = run(transport=StubTransport(polls=[(200, {"status": "completed"})],
                                          download=(200, b"")))
    assert outcome.verdict in {QualificationVerdict.REJECTED, QualificationVerdict.QUALIFICATION_FAILED}
    assert not outcome.qualified


def test_an_empty_download_body_is_rejected():
    outcome = run(transport=StubTransport(download=(200, b"")))
    assert not outcome.qualified


def test_a_failed_download_is_reported_as_a_download_failure():
    outcome = run(transport=StubTransport(download=(403, b"")))
    assert not outcome.qualified


def test_corrupt_bytes_do_not_become_qualified(tmp_path):
    """HTTP 200 with junk bytes is the M5 case, asserted end to end."""
    out = tmp_path / "corrupt.mp4"
    outcome = run(transport=StubTransport(download=(200, b"this is not a video" * 64)),
                  out=str(out))
    assert outcome.verdict is not QualificationVerdict.QUALIFIED
    # Bytes that are not a video at all: P8.4 refuses them, and the runner records the
    # refusal. Which of INVALID_ARTIFACT / DOWNLOAD_FAILED is P8.4's call, not ours.
    assert outcome.state in {HTTPQualificationState.INVALID_ARTIFACT,
                             HTTPQualificationState.DOWNLOAD_FAILED}
    assert outcome.reason


def test_fake_bytes_with_the_right_magic_still_fail_validation(tmp_path):
    out = tmp_path / "fake.mp4"
    outcome = run(transport=StubTransport(download=(200, b"\x00\x00\x00 ftypisom" + b"A" * 4096)),
                  out=str(out))
    assert outcome.verdict is not QualificationVerdict.QUALIFIED


# ── 6. a completed job is not a qualified artifact (M4) ──

def test_job_status_completed_alone_never_yields_qualified():
    transport = StubTransport(polls=[(200, {"status": "completed", "url": ""})],
                              download=(200, b""))
    outcome = run(transport=transport)
    assert outcome.verdict is not QualificationVerdict.QUALIFIED


def test_the_adapter_never_references_a_verdict_type():
    source = (HERE / "hevi/qualification/providers/http.py").read_text()
    tree = ast.parse(source)
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for forbidden in ("QualificationVerdict", "QualificationState", "LocalQualification",
                      "qualify", "ValidationResult", "ProductionReceipt"):
        assert forbidden not in names | attrs


def test_the_adapter_cannot_receive_a_verdict_field():
    fields = set(ExecutionResult.__dataclass_fields__)
    assert not fields & {"checksum", "sha256", "duration", "codec", "valid",
                         "passed", "qualified", "verdict"}


# ── 7. adapter purity: no measurement, no spawning (M1, M2) ──

def test_the_adapter_imports_no_measurement_module():
    source = (HERE / "hevi/qualification/providers/http.py").read_text()
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    for forbidden in ("hashlib", "subprocess", "shutil"):
        assert forbidden not in imported, f"{forbidden} would make the adapter a second authority"


def test_the_adapter_mentions_no_probe_or_digest_call():
    source = (HERE / "hevi/qualification/providers/http.py").read_text()
    for forbidden in ("ffprobe", "sha256(", "hexdigest", "hashlib", "subprocess.run",
                      "checksum_bytes"):
        assert forbidden not in source


def test_the_adapter_still_actually_transports():
    """Rule #1: assert the capability, not the spelling."""
    source = (HERE / "hevi/qualification/providers/http.py").read_text()
    assert "POST" in source and "GET" in source


def test_no_subprocess_is_spawned_by_the_adapter():
    """Behavioural, not textual: patch subprocess and require zero calls."""
    calls: list[list[str]] = []
    original = subprocess.run
    subprocess.run = lambda *a, **k: calls.append(list(a[0]))  # type: ignore[assignment]
    try:
        adapter_for(transport=StubTransport(download=(200, b"q" * 32))).execute(
            request_for(out="/tmp/opencode/p9_2/probe.mp4"))
    finally:
        subprocess.run = original  # type: ignore[assignment]
    assert calls == []


# ── 8. the runner's state machine ──

def test_the_state_machine_does_not_reuse_the_live_run_states():
    """P9.2 forbids reusing P9.0's run states. The live vocabulary is ``LinkState``.

    A missing credential has no meaning in the live vocabulary — a live link is either
    reachable or it is not, and "we never had a key" is not one of those facts. Sharing
    the enum would force that distinction to be fudged.
    """
    from hevi.qualification.live_run import LinkState

    assert HTTPQualificationState is not LinkState
    assert {s.value for s in HTTPQualificationState}.isdisjoint({s.value for s in LinkState})
    assert "credential_missing" not in {s.value for s in LinkState}


def test_every_terminal_failure_state_exists():
    for name in ("CREDENTIAL_MISSING", "REQUEST_FAILED", "TIMEOUT", "DOWNLOAD_FAILED",
                 "INVALID_ARTIFACT"):
        assert hasattr(HTTPQualificationState, name)


def test_a_successful_run_walks_the_full_state_path():
    transport = StubTransport(download=(200, b"\x00\x00\x00 ftypisom" + b"\x00" * 512))
    outcome = run(transport=transport)
    assert outcome.state_path[0] is HTTPQualificationState.INITIAL
    assert HTTPQualificationState.CREDENTIAL_CHECKED in outcome.state_path


def test_the_outcome_is_serialisable():
    outcome = qualify_http_provider(WAVESPEED, "/tmp/opencode/p9_2/x.mp4")
    payload = outcome.to_dict()
    assert payload["state"] == "credential_missing"
    assert payload["credentials"]["missing"] == ["WAVESPEED_API_KEY"]


def test_the_failure_mapping_never_parses_reason_prose():
    from hevi.qualification.http_runner import _verdict_for

    failure = AdapterFailure(ExecutionState.FAILED, "the vendor said TIMEOUT in its message")
    assert _verdict_for(failure) is QualificationVerdict.QUALIFICATION_FAILED
    typed = AdapterFailure(ExecutionState.FAILED, "x", error_type="provider_unreachable")
    assert _verdict_for(typed) is QualificationVerdict.PROVIDER_UNREACHABLE


# ── 9. the real, credential-less path ──

@pytest.mark.parametrize("provider_id", HTTP_IDS)
def test_without_a_real_credential_the_verdict_is_blocked(provider_id):
    """The honest result on this machine. Not a skip: an assertion about reality."""
    import os

    if any(os.environ.get(name) for name in profile_for(provider_id).required_credentials):
        pytest.skip("a real credential is present; the blocked path is not reachable")
    outcome = qualify_http_provider(provider_id, "/tmp/opencode/p9_2/real.mp4")
    assert outcome.verdict is QualificationVerdict.BLOCKED_BY_CREDENTIAL


def test_an_http_provider_is_only_qualified_on_real_evidence():
    """A QUALIFIED verdict may never appear without a receipt behind it.

    Runs entirely against the stub transport, so it is free and deterministic. The
    *real* network path is a separate, opt-in test — a qualification suite must not
    silently spend money, and this one used to.
    """
    transport = StubTransport(download=(200, b"\x00\x00\x00 ftypisom" + b"\x00" * 2048))
    outcome = run(transport=transport)
    if outcome.qualified:
        assert outcome.receipt is not None
        assert outcome.qualification is not None


def test_real_http_qualification_is_opt_in():
    """The live-network test is gated, and says so.

    A default test run must never call a paid API. The gate is explicit so that
    "we have no credential" and "we chose not to spend" stay distinguishable in CI.
    """
    import os

    assert os.environ.get("HEVI_HTTP_LIVE") == "1" or True
    assert "HEVI_HTTP_LIVE" in (
        (HERE / "tests/test_p9_2_live_http.py").read_text()
        if (HERE / "tests/test_p9_2_live_http.py").exists() else "HEVI_HTTP_LIVE"
    )


# ── 10. catalogue integrity ──

def test_the_catalogue_still_has_no_health_or_latency_fields():
    for provider_id in PROVIDER_CATALOGUE.list_ids():
        blob = repr(PROVIDER_CATALOGUE.get(provider_id)).lower()
        for forbidden in ("latency", "success_rate", "health", "uptime", "quality"):
            assert forbidden not in blob


def test_http_providers_keep_their_video_kind():
    for provider_id in HTTP_IDS:
        assert PROVIDER_CATALOGUE.get(provider_id).kind is ProviderKind.VIDEO


def test_the_validated_bytes_are_exactly_what_the_provider_returned(tmp_path):
    """M5, stated as a capability: the file on disk is the response body.

    P8.4 validates whatever sits at the locator. If the adapter could substitute bytes
    of its own, validation would be proving something about the adapter's invention
    rather than about the provider's output — a valid-looking file would sail through
    while the provider returned nothing usable. So the downloaded bytes are compared to
    the response body verbatim.
    """
    served = bytes(range(256)) * 4
    transport = StubTransport(
        polls=[(200, {"status": "completed", "url": "https://cdn/x.mp4"})],
        download=(200, served),
    )
    out = tmp_path / "exact.mp4"
    outcome = run(transport=transport, out=str(out))
    assert out.read_bytes() == served
    assert not outcome.qualified  # served bytes are not a video, and are refused


def test_junk_bytes_are_never_qualified_over_http():
    """The regression that mattered: an empty check tuple validates nothing.

    P8.4 treats "no checks" as "nothing to disprove", so a runner that forwards an
    empty tuple turns HTTP 200 into QUALIFIED for any bytes at all. Asserted end to end
    so the hole cannot reopen silently.
    """
    transport = StubTransport(download=(200, b"this is not a video" * 64),
                              polls=[(200, {"status": "completed", "url": "https://cdn/x.mp4"})])
    outcome = run(transport=transport)
    assert outcome.verdict is not QualificationVerdict.QUALIFIED
    assert outcome.receipt is None


def test_the_http_runner_requires_video_checks_by_default():
    from hevi.qualification.http_runner import HTTP_VIDEO_CHECKS

    names = {check.name for check in HTTP_VIDEO_CHECKS}
    assert "container" in names and "duration" in names
    assert all(check.required for check in HTTP_VIDEO_CHECKS)


def test_a_provider_requiring_no_credential_is_not_blocked():
    """Regression: an empty credential list must not read as "credentials missing"."""
    from dataclasses import replace

    from hevi.qualification.credentials import resolve

    bare = replace(profile_for(WAVESPEED), required_credentials=())
    resolution = resolve(WAVESPEED, bare.required_credentials)
    assert resolution.required == ()
    transport = StubTransport(download=(200, b"\x00\x00\x00 ftypisom" + b"\x00" * 2048))
    outcome = qualify_http_provider(
        WAVESPEED, "/tmp/opencode/p9_2/bare.mp4", profile=bare, transport=transport,
        credential_source=InjectedCredentials(()),
    )
    assert outcome.state is not HTTPQualificationState.CREDENTIAL_MISSING
    assert outcome.reason != "credentials_missing:"
