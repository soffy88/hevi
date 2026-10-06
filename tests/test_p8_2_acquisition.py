"""P8.2 — Acquisition, and the difference between a URI and proof.

A URI is the cheapest possible fake. It costs nothing to write ``https://cdn/x.mp4``,
it survives serialisation, and every layer above it will happily treat it as an asset.
So P8.2 makes the cheap fake insufficient: ``ACQUIRED`` requires a digest, and a digest
cannot be typed — it is a function of the payload.

The three gates, each stopping for its own reason:

    ProviderDecision        may this provider be used?
    ProviderRuntimeStatus   is it answering?
    payload + digest        did anything arrive, and is it what we expected?

And two separations carried forward from P7.3, because acquisition is the newest place
to break them: a source carries no provider *facts*, and no execution *verdict*.

T1-T5 below are the required mutations. Each is a specific way this collapses.
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from hevi.acquisition import (
    AcquiredSource,
    AcquisitionFailure,
    AcquisitionOutcome,
    AcquisitionRequest,
    AcquisitionState,
    acquire,
    verify_outcome,
)
from hevi.acquisition.acquire import Fetcher
from hevi.evidence import AcquisitionEvidence, AcquisitionMethod, checksum_bytes
from hevi.production.p6.production_runtime import RunState
from hevi.runtime.provider.models import ProviderRuntimeStatus, RuntimeAvailability

ACQ_DIR = pathlib.Path("hevi/acquisition")
EVIDENCE_DIR = pathlib.Path("hevi/evidence")
MODELS = ACQ_DIR / "models.py"
ACQUIRE = ACQ_DIR / "acquire.py"

PAYLOAD = b"the bytes a provider actually returned"


def _request(provider_id: str = "veo3") -> AcquisitionRequest:
    return AcquisitionRequest(
        request_id="r1", provider_id=provider_id, media_type="VIDEO", source_id="s1"
    )


def _usable(provider_id: str = "veo3") -> ProviderRuntimeStatus:
    return ProviderRuntimeStatus(
        provider_id=provider_id,
        availability=RuntimeAvailability.AVAILABLE,
        reachable=True,
        latency_ms=42,
    )


def _fetch(payload: bytes = PAYLOAD) -> Fetcher:
    def _inner(request: AcquisitionRequest) -> bytes:
        return payload

    return _inner


def _acquired(**kwargs) -> AcquisitionOutcome:
    base = {
        "eligible": True,
        "status": _usable(),
        "fetch": _fetch(),
    }
    base.update(kwargs)
    return acquire(_request(), **base)


def _code_identifiers(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return (
        {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    )


# ══════════════════════════════════════════════════════════════════════════
# the model, as specified
# ══════════════════════════════════════════════════════════════════════════


def test_acquired_source_has_exactly_the_specified_fields():
    names = {f.name for f in dataclasses.fields(AcquiredSource)}
    assert names == {
        "source_id", "provider_id", "uri", "checksum",
        "acquired_at", "evidence_id", "state",
    }


def test_acquisition_evidence_has_exactly_the_specified_fields():
    names = {f.name for f in dataclasses.fields(AcquisitionEvidence)}
    assert names == {
        "evidence_id", "provider_id", "source_id", "checksum",
        "timestamp", "acquisition_method",
    }


def test_evidence_carries_no_uri():
    """T1: a locator belongs to the source; evidence is about bytes.

    If evidence held the URI, `evidence == uri` would become expressible and the
    separation this phase exists to establish would be unenforceable by construction.
    """
    names = {f.name for f in dataclasses.fields(AcquisitionEvidence)}
    assert "uri" not in names
    assert "url" not in names and "location" not in names


def test_checksum_is_required_and_must_be_a_real_digest():
    with pytest.raises(ValueError, match="ACQUIRED_SOURCE_BAD_CHECKSUM"):
        AcquiredSource(
            source_id="s1", provider_id="veo3", uri="https://x/y",
            checksum=None, evidence_id="e1",
        )
    for placeholder in ("", "TODO", "pending", "0" * 8, "z" * 64):
        with pytest.raises(ValueError, match="ACQUIRED_SOURCE_BAD_CHECKSUM"):
            AcquiredSource(
                source_id="s1", provider_id="veo3", uri="https://x/y",
                checksum=placeholder, evidence_id="e1",
            )


def test_acquired_source_requires_verified_digest():
    """The owner of the checksum rule is the digest validation layer itself.

    Loosening that guard failed exactly one test and no end-to-end test, because
    nothing downstream ever constructs an invalid digest. That is correct but fragile:
    it means the whole rule rests on this assertion alone. So it is stated directly
    rather than left to indirect coverage — every shape that is not a verified sha256
    is refused, including the ones no caller currently produces.
    """
    valid = checksum_bytes(b"payload")
    assert AcquiredSource(
        source_id="s1", provider_id="veo3", uri="https://x/y",
        checksum=valid, evidence_id="e1",
    ).checksum == valid

    for bad in (None, "", "TODO", "pending", "none", "0", "0" * 63, "0" * 65,
                "A" * 64, "g" * 64, valid.upper(), valid[:-1] + "z", valid + "0"):
        with pytest.raises(ValueError, match="ACQUIRED_SOURCE_BAD_CHECKSUM"):
            AcquiredSource(
                source_id="s1", provider_id="veo3", uri="https://x/y",
                checksum=bad, evidence_id="e1",
            )


def test_uri_is_required():
    with pytest.raises(ValueError, match="ACQUIRED_SOURCE_WITHOUT_URI"):
        AcquiredSource(
            source_id="s1", provider_id="veo3", uri="", checksum="a" * 64,
            evidence_id="e1",
        )


def test_evidence_id_is_required_to_be_acquired():
    """T2/T3: without evidence the source may exist, but it is not ACQUIRED."""
    with pytest.raises(ValueError, match="ACQUIRED_SOURCE_WITHOUT_EVIDENCE"):
        AcquiredSource(
            source_id="s1", provider_id="veo3", uri="https://x/y",
            checksum="a" * 64, evidence_id="",
            state=AcquisitionState.ACQUIRED,
        )


def test_a_source_without_evidence_may_still_exist_but_not_be_acquired():
    """The distinction has to be representable, not just forbidden."""
    source = AcquiredSource(
        source_id="s1", provider_id="veo3", uri="https://x/y",
        checksum="a" * 64, evidence_id="", state=AcquisitionState.AVAILABLE,
    )
    assert source.is_acquired is False


def test_evidence_checksum_must_be_a_real_digest():
    with pytest.raises(ValueError, match="ACQUISITION_EVIDENCE_BAD_CHECKSUM"):
        AcquisitionEvidence(
            evidence_id="e1", provider_id="veo3", source_id="s1", checksum="TODO"
        )


# ══════════════════════════════════════════════════════════════════════════
# T3 — a URI must not be enough
# ══════════════════════════════════════════════════════════════════════════


def test_well_formed_uri_alone_does_not_produce_an_acquired_source():
    """The cheap fake. Constructing one by hand cannot yield ACQUIRED."""
    with pytest.raises(ValueError):
        AcquiredSource(
            source_id="s1", provider_id="veo3", uri="https://cdn.example/video.mp4",
            checksum=checksum_bytes(PAYLOAD), evidence_id="",
            state=AcquisitionState.ACQUIRED,
        )


def test_acquired_state_requires_a_verifiable_payload():
    outcome = _acquired()
    assert outcome.succeeded
    evidence = AcquisitionEvidence(
        "ev-r1", "veo3", "s1", outcome.source.checksum
    )
    assert verify_outcome(outcome, PAYLOAD, evidence)
    assert not verify_outcome(outcome, b"different bytes", evidence)


def test_digest_is_computed_from_bytes_not_supplied():
    """T3: the checksum must be a function of the payload."""
    outcome = _acquired()
    assert outcome.source.checksum == checksum_bytes(PAYLOAD)


def test_expected_checksum_mismatch_fails_acquisition():
    outcome = _acquired(expected_checksum="b" * 64)
    assert outcome.failure is AcquisitionFailure.CHECKSUM_MISMATCH
    assert outcome.source is None


def test_empty_payload_is_a_failure_not_an_empty_source():
    outcome = _acquired(fetch=_fetch(b""))
    assert outcome.failure is AcquisitionFailure.DOWNLOAD_FAILED
    assert outcome.source is None


def test_fetcher_exception_becomes_an_outcome_not_a_crash():
    def explode(request: AcquisitionRequest) -> bytes:
        raise ConnectionResetError("peer reset")

    outcome = _acquired(fetch=explode)
    assert outcome.failure is AcquisitionFailure.DOWNLOAD_FAILED
    assert "ConnectionResetError" in outcome.reason


# ══════════════════════════════════════════════════════════════════════════
# T5 — runtime dependency
# ══════════════════════════════════════════════════════════════════════════


def test_unavailable_provider_cannot_acquire():
    status = ProviderRuntimeStatus(
        "veo3", RuntimeAvailability.UNAVAILABLE, reachable=False,
        failure_reason="http_503",
    )
    outcome = _acquired(status=status)
    assert outcome.source is None
    assert outcome.failure is AcquisitionFailure.PROVIDER_UNREACHABLE
    assert "http_503" in outcome.reason


def test_unknown_runtime_state_cannot_acquire():
    """Fail-closed: never observed is not the same as observed-working."""
    outcome = _acquired(status=ProviderRuntimeStatus("veo3"))
    assert outcome.source is None
    assert outcome.failure is AcquisitionFailure.PROVIDER_UNREACHABLE


def test_absent_runtime_status_cannot_acquire():
    outcome = _acquired(status=None)
    assert outcome.source is None
    assert outcome.failure is AcquisitionFailure.PROVIDER_UNREACHABLE


def test_policy_rejection_stops_acquisition_before_any_fetch():
    fetched: list[str] = []

    def spy(request: AcquisitionRequest) -> bytes:
        fetched.append(request.request_id)
        return PAYLOAD

    outcome = _acquired(eligible=False, fetch=spy)
    assert outcome.source is None
    assert outcome.failure is AcquisitionFailure.POLICY_BLOCKED
    assert fetched == [], "a policy-rejected provider must not be fetched from"


def test_policy_and_runtime_failures_are_distinguishable():
    policy = _acquired(eligible=False)
    runtime = _acquired(status=ProviderRuntimeStatus("veo3"))
    assert policy.failure is not runtime.failure
    assert policy.failure is AcquisitionFailure.POLICY_BLOCKED
    assert runtime.failure is AcquisitionFailure.PROVIDER_UNREACHABLE


def test_policy_check_precedes_the_fetch():
    """Order matters: a rejected provider must not even be contacted."""
    calls: list[str] = []

    def tracking_fetch(request: AcquisitionRequest) -> bytes:
        calls.append("fetch")
        return PAYLOAD

    acquire(_request(), eligible=False, status=_usable(), fetch=tracking_fetch)
    assert calls == []


# ══════════════════════════════════════════════════════════════════════════
# T4 — provider authority separation
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "forbidden",
    ["locality", "license", "license_class", "capabilities", "capability_state",
     "quality", "quality_score", "ranking", "license_kind"],
)
def test_acquired_source_carries_no_provider_fact(forbidden):
    names = {f.name for f in dataclasses.fields(AcquiredSource)}
    assert forbidden not in names, f"acquired source carries provider fact {forbidden}"


def test_acquisition_package_declares_no_fact_field():
    for source in (MODELS, ACQUIRE, EVIDENCE_DIR / "acquisition.py"):
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                assert not node.target.id.startswith(
                    ("locality", "license", "licence", "capability", "quality")
                ), f"{source.name}:{node.lineno} declares fact {node.target.id}"


def test_provider_decision_cannot_carry_a_source():
    """T4/spec: ProviderPolicy does not do acquisition."""
    from hevi.provider_policy.policy import ProviderDecision

    names = set(ProviderDecision.model_fields)
    for forbidden in ("source", "source_url", "uri", "asset", "acquired_source"):
        assert forbidden not in names, (
            f"ProviderDecision carries {forbidden!r}; policy does not acquire"
        )


def test_acquisition_does_not_import_the_catalogue_or_policy():
    for source in (MODELS, ACQUIRE):
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.endswith("facts"), (
                    f"{source.name} imports the fact catalogue"
                )
                assert "hevi.production.p7" not in node.module


# ══════════════════════════════════════════════════════════════════════════
# no production state leak
# ══════════════════════════════════════════════════════════════════════════


def test_acquisition_state_is_disjoint_from_run_state():
    """Getting the asset is not rendering it."""
    assert {s.value for s in AcquisitionState}.isdisjoint({s.value for s in RunState})


def test_acquisition_states_are_the_four_specified():
    """The four specified states, with values namespaced against RunState.

    A bare ``failed`` would be identical to ``RunState.failed`` on the wire, so
    "the download failed" and "the render failed" would be indistinguishable in any
    serialised record. Namespacing keeps P7.3's I5 invariant true by construction.
    """
    assert {s.name for s in AcquisitionState} == {
        "REQUESTED", "AVAILABLE", "ACQUIRED", "FAILED"
    }
    assert {s.value for s in AcquisitionState} == {
        "acquisition_requested", "acquisition_available",
        "acquired", "acquisition_failed",
    }
    for state in AcquisitionState:
        assert state.value.startswith("acquisition") or state.value == "acquired"


@pytest.mark.parametrize(
    "token", ["PRODUCED", "QA_PASS", "QA_PASSED", "QA_FAIL", "EXECUTING", "CANCELLED"]
)
def test_no_execution_verdict_in_acquisition_code(token):
    for path in (MODELS, ACQUIRE, EVIDENCE_DIR / "acquisition.py"):
        assert token not in _code_identifiers(path), (
            f"{path.name} asserts execution state {token}"
        )


def test_acquisition_does_not_construct_an_execution_receipt():
    """Checked on identifiers, not text.

    The module docstrings name ExecutionReceipt to explain that production truth is
    *not* this package's — describing the boundary is the opposite of crossing it.
    """
    for path in (MODELS, ACQUIRE, EVIDENCE_DIR / "acquisition.py"):
        identifiers = _code_identifiers(path)
        assert "ExecutionReceipt" not in identifiers, (
            f"{path.name} constructs an ExecutionReceipt"
        )
        assert "ProductionRunResult" not in identifiers
        assert "RunState" not in identifiers


# ══════════════════════════════════════════════════════════════════════════
# failure model — causes stay distinct
# ══════════════════════════════════════════════════════════════════════════


def test_failure_causes_are_classified_not_collapsed():
    values = {f.value for f in AcquisitionFailure}
    assert values == {
        "policy_blocked", "provider_unreachable", "download_failed",
        "checksum_mismatch", "evidence_missing",
    }
    assert "failed" not in values, "an undifferentiated FAILED would hide the cause"


def test_every_failure_requires_a_reason():
    with pytest.raises(ValueError, match="ACQUISITION_FAILURE_WITHOUT_REASON"):
        AcquisitionOutcome(
            request_id="r1", provider_id="veo3",
            failure=AcquisitionFailure.DOWNLOAD_FAILED,
        )


def test_outcome_is_exactly_one_of_source_or_failure():
    with pytest.raises(ValueError, match="AMBIGUOUS_ACQUISITION_OUTCOME"):
        AcquisitionOutcome(request_id="r1", provider_id="veo3")
    outcome = _acquired()
    with pytest.raises(ValueError, match="AMBIGUOUS_ACQUISITION_OUTCOME"):
        AcquisitionOutcome(
            request_id="r1", provider_id="veo3", source=outcome.source,
            failure=AcquisitionFailure.DOWNLOAD_FAILED, reason="both",
        )


def test_outcome_provider_must_match_the_source_provider():
    outcome = _acquired()
    with pytest.raises(ValueError, match="ACQUISITION_OUTCOME_PROVIDER_MISMATCH"):
        AcquisitionOutcome(
            request_id="r1", provider_id="kling_v2", source=outcome.source
        )


def test_request_requires_an_identity_before_anything_is_fetched():
    for field, value in (("request_id", ""), ("provider_id", ""), ("media_type", "")):
        kwargs = {
            "request_id": "r1", "provider_id": "veo3", "media_type": "VIDEO",
            "source_id": "s1",
        }
        kwargs[field] = value
        with pytest.raises(ValueError, match="ACQUISITION_REQUEST_WITHOUT"):
            AcquisitionRequest(**kwargs)
    with pytest.raises(ValueError, match="ACQUISITION_REQUEST_WITHOUT_SOURCE"):
        AcquisitionRequest(request_id="r1", provider_id="veo3", media_type="VIDEO")


# ══════════════════════════════════════════════════════════════════════════
# no second fetcher
# ══════════════════════════════════════════════════════════════════════════


def test_acquisition_module_contains_no_network_client():
    tree = ast.parse(ACQUIRE.read_text())
    banned = {"httpx", "aiohttp", "requests", "urllib", "socket", "aiofiles"}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & banned), f"acquire.py imports {imported & banned}"


def test_acquisition_module_defines_no_fetcher():
    tree = ast.parse(ACQUIRE.read_text())
    functions = [
        n.name for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert not any(f in {"fetch", "download", "retrieve", "pull", "get"} for f in functions), (
        f"acquire.py defines a fetcher: {functions}"
    )
    assert not any(
        isinstance(n, ast.AsyncFunctionDef) for n in ast.walk(tree)
    ), "acquisition performs no async I/O of its own"


def test_evidence_package_defines_no_transport():
    tree = ast.parse((EVIDENCE_DIR / "acquisition.py").read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not (imported & {"httpx", "aiohttp", "requests", "urllib", "socket"})


# ══════════════════════════════════════════════════════════════════════════
# evidence records how it was obtained
# ══════════════════════════════════════════════════════════════════════════


def test_acquisition_methods_are_distinguishable():
    assert {m.value for m in AcquisitionMethod} == {
        "http_fetch", "queue_poll", "local_read", "api_response"
    }


def test_unknown_acquisition_method_is_refused():
    with pytest.raises(ValueError, match="UNKNOWN_ACQUISITION_METHOD"):
        AcquisitionEvidence(
            evidence_id="e1", provider_id="veo3", source_id="s1",
            checksum="a" * 64, acquisition_method="telepathy",
        )


def test_evidence_is_minted_with_the_source_from_the_same_payload():
    outcome = _acquired(method=AcquisitionMethod.QUEUE_POLL)
    assert outcome.source.evidence_id == "ev-r1"
    evidence = AcquisitionEvidence(
        "ev-r1", "veo3", "s1", outcome.source.checksum,
        acquisition_method=AcquisitionMethod.QUEUE_POLL,
    )
    assert verify_outcome(outcome, PAYLOAD, evidence)


def test_evidence_of_another_source_does_not_verify():
    outcome = _acquired()
    evidence = AcquisitionEvidence("ev-x", "veo3", "s-other", outcome.source.checksum)
    assert not verify_outcome(outcome, PAYLOAD, evidence)


def test_verification_requires_all_three_to_agree():
    outcome = _acquired()
    good = AcquisitionEvidence("ev-r1", "veo3", "s1", outcome.source.checksum)
    assert verify_outcome(outcome, PAYLOAD, good)
    # right digest, wrong bytes
    assert not verify_outcome(outcome, b"tampered", good)
    # right bytes, evidence for another provider
    other = AcquisitionEvidence("ev-r1", "kling_v2", "s1", outcome.source.checksum)
    assert not verify_outcome(outcome, PAYLOAD, other)


def test_serialisation_round_trips_for_audit():
    outcome = _acquired()
    payload = outcome.to_dict()
    assert payload["source"]["checksum"] == checksum_bytes(PAYLOAD)
    assert payload["failure"] is None
    assert payload["source"]["state"] == "acquired"


def test_local_read_is_available_for_local_providers():
    """Acquisition method reflects how bytes were obtained, not who the provider is."""
    outcome = _acquired(method=AcquisitionMethod.LOCAL_READ)
    assert outcome.succeeded
    evidence = AcquisitionEvidence(
        "ev-r1", "veo3", "s1", outcome.source.checksum,
        acquisition_method=AcquisitionMethod.LOCAL_READ,
    )
    assert evidence.acquisition_method is AcquisitionMethod.LOCAL_READ
