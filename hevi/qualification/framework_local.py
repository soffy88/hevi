"""HEVI P9.1.d.1 — the framework: the only thing that may return a verdict.

    adapter.execute()  ->  ExecutionResult   (a locator, nothing measured)
            |
            v
    framework.qualify()
            |
            +--> AcquiredSource + AcquisitionEvidence   (P8.2)
            +--> ProductionReceipt                      (P8.3)
            +--> ArtifactValidation                     (P8.4)
            |
            v
      QUALIFIED / REJECTED / ...

The adapter never sees this module's verdict type and has no field in which to
return one. That asymmetry is the whole design: an adapter that could declare
success would be a second authority for artifact truth, which is exactly what
P9.1.d removed from ``hevi/renderers/``.

Every failure keeps its cause. ``BLOCKED_BY_RUNTIME`` means nothing started;
``REJECTED`` means it ran and did not produce something usable; ``INVALID_ARTIFACT``
means the bytes are not what was claimed. Collapsing them is how a broken provider
gets reported as an absent one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hevi.acquisition.models import AcquiredSource, AcquisitionState
from hevi.artifact.checks import CheckRequirement
from hevi.artifact.qualify import ArtifactState, describe, qualify
from hevi.evidence.acquisition import AcquisitionEvidence, AcquisitionMethod, checksum_bytes
from hevi.execution.execute import ReceiptLedger, issue_receipt
from hevi.execution.models import ExecutionRun
from hevi.qualification.live_run import QualificationVerdict
from hevi.qualification.models import (
    AdapterFailure,
    ExecutionState,
    ProviderQualification,
    QualificationRequest,
    RuntimeUnavailable,
)
from hevi.qualification.providers import adapter_for


@dataclass(frozen=True)
class LocalQualification:
    """A framework verdict, with everything that led to it."""

    provider_id: str
    verdict: QualificationVerdict
    reason: str = ""
    execution_id: str = ""
    locator: str = ""
    source: AcquiredSource | None = None
    evidence: AcquisitionEvidence | None = None
    receipt: Any | None = None
    artifact_state: ArtifactState | None = None
    checks: tuple[CheckRequirement, ...] = ()
    finished_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def qualified(self) -> bool:
        return self.verdict is QualificationVerdict.QUALIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "verdict": self.verdict.value,
            "reason": self.reason,
            "execution_id": self.execution_id,
            "locator": self.locator,
            "receipt": self.receipt.to_dict() if self.receipt else None,
            "artifact_state": self.artifact_state.value if self.artifact_state else None,
            "checks": [c.name for c in self.checks],
        }


def qualify_local_provider(
    request: QualificationRequest,
    *,
    checks: tuple[CheckRequirement, ...] = (),
    adapter: ProviderQualification | None = None,
    media_type: str = "VIDEO",
    expected_checksum: str = "",
) -> LocalQualification:
    """Execute a local provider and prove — or refuse to prove — its artifact."""
    factory = adapter_for(request.provider_id)
    chosen = adapter or (factory() if factory is not None else None)
    if chosen is None:
        return LocalQualification(
            provider_id=request.provider_id,
            verdict=QualificationVerdict.NOT_RUN,
            reason=f"no adapter for {request.provider_id}",
            checks=checks,
        )

    availability = chosen.available()
    if not availability.can_run:
        return LocalQualification(
            provider_id=request.provider_id,
            verdict=QualificationVerdict.BLOCKED_BY_RUNTIME,
            reason=availability.reason,
            checks=checks,
        )

    # ── execute ──
    try:
        execution = chosen.execute(request)
    except RuntimeUnavailable as exc:
        return LocalQualification(
            provider_id=request.provider_id,
            verdict=QualificationVerdict.BLOCKED_BY_RUNTIME,
            reason=str(exc), checks=checks,
        )
    except AdapterFailure as exc:
        verdict = (
            QualificationVerdict.REJECTED
            if exc.state is ExecutionState.NO_ARTIFACT
            else QualificationVerdict.QUALIFICATION_FAILED
        )
        return LocalQualification(
            provider_id=request.provider_id, verdict=verdict,
            reason=f"{exc.state.value}:{exc.reason}", checks=checks,
        )
    except Exception as exc:
        return LocalQualification(
            provider_id=request.provider_id,
            verdict=QualificationVerdict.QUALIFICATION_FAILED,
            reason=f"{type(exc).__name__}:{exc}"[:300], checks=checks,
        )

    locator = execution.artifact_locator
    try:
        payload = Path(locator).read_bytes()
    except OSError as exc:
        return LocalQualification(
            provider_id=request.provider_id, verdict=QualificationVerdict.REJECTED,
            reason=f"artifact unreadable:{type(exc).__name__}", execution_id=execution.execution_id,
            locator=locator, checks=checks,
        )

    # ── P8.2 acquisition ──
    digest = checksum_bytes(payload)
    if expected_checksum and digest != expected_checksum:
        return LocalQualification(
            provider_id=request.provider_id,
            verdict=QualificationVerdict.INVALID_ARTIFACT,
            reason=f"bytes do not match the declared digest: {digest}",
            execution_id=execution.execution_id, locator=locator, checks=checks,
        )
    evidence = AcquisitionEvidence(
        evidence_id=f"ev-{execution.execution_id}", provider_id=request.provider_id,
        source_id=locator, checksum=digest, acquisition_method=AcquisitionMethod.LOCAL_READ,
    )
    source = AcquiredSource(
        source_id=locator, provider_id=request.provider_id, uri=f"render://{locator}",
        checksum=digest, evidence_id=evidence.evidence_id, state=AcquisitionState.ACQUIRED,
    )

    # ── P8.4 validation ──
    descriptor = describe(locator, payload, location=source.uri, media_type=media_type)
    validation, artifact_state = qualify(descriptor, payload, checks)
    if artifact_state is ArtifactState.INVALID_ARTIFACT:
        return LocalQualification(
            provider_id=request.provider_id, verdict=QualificationVerdict.INVALID_ARTIFACT,
            reason="artifact bytes are not the declared artifact",
            execution_id=execution.execution_id, locator=locator, source=source,
            evidence=evidence, artifact_state=artifact_state, checks=checks,
        )
    if artifact_state is not ArtifactState.QUALIFIED:
        return LocalQualification(
            provider_id=request.provider_id, verdict=QualificationVerdict.REJECTED,
            reason=f"artifact did not qualify: {artifact_state.value}",
            execution_id=execution.execution_id, locator=locator, source=source,
            evidence=evidence, artifact_state=artifact_state, checks=checks,
        )

    # ── P8.3 receipt ──
    run = ExecutionRun(f"run-{request.provider_id}", source.source_id,
                       request.provider_id).completed()
    receipt, failure, why = issue_receipt(
        run, source_id=source.source_id, artifact_id=descriptor.artifact_id,
        read_artifact=lambda _aid: payload,
        validate=lambda _aid, body: validation if validation.verify_payload(body) else None,
        producer=request.provider_id, ledger=ReceiptLedger(),
    )
    if receipt is None:
        return LocalQualification(
            provider_id=request.provider_id, verdict=QualificationVerdict.REJECTED,
            reason=f"receipt refused: {failure} {why}".strip(),
            execution_id=execution.execution_id, locator=locator, source=source,
            evidence=evidence, artifact_state=artifact_state, checks=checks,
        )

    return LocalQualification(
        provider_id=request.provider_id, verdict=QualificationVerdict.QUALIFIED,
        execution_id=execution.execution_id, locator=locator, source=source,
        evidence=evidence, receipt=receipt, artifact_state=artifact_state, checks=checks,
    )


__all__ = ["LocalQualification", "qualify_local_provider"]
