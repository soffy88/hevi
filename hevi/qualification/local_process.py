"""HEVI P9.1.a — LOCAL_PROCESS qualification, end to end.

This closes the loop for a declared local runtime:

```
ProviderCatalogue(spec)  ->  driver  ->  renderer  ->  artifact bytes
                                                      |
                            AcquiredSource (P8.2) <-+  (checksum + evidence)
                                    |
                            ProductionReceipt (P8.3)
                                    |
                            ArtifactValidation (P8.4)
                                    |
                                 verdict
```

The layering is the whole point, and it is the one the P8.4 note demanded:

```
renderer  ->  artifact bytes  ->  validator
```

A renderer never returns a ``ValidationResult``. It returns **bytes**. The receipt is
issued from those bytes, and the validator consumes those bytes. If a
``ManimProvider`` could hand back a ``ValidationResult`` the provider would own
artifact truth again — the exact regression P8.4 closed by taking validation away from
anything that can touch the artifact.

What this does **not** claim
----------------------------
The harness is complete and the runtime may be absent. ``manim`` is a declared
``LOCAL_PROCESS`` provider whose executable is not installed here, so this module
reports ``BLOCKED_BY_RUNTIME`` rather than a pass. A working harness and a missing
runtime are different problems, and only one of them is P9's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hevi.acquisition.models import AcquiredSource, AcquisitionState
from hevi.artifact.checks import CheckRequirement
from hevi.artifact.qualify import ArtifactState, describe, qualify
from hevi.evidence.acquisition import (
    AcquisitionEvidence,
    AcquisitionMethod,
    checksum_bytes,
)
from hevi.execution.execute import issue_receipt
from hevi.execution.models import ExecutionRun
from hevi.providers.runtime_specs import ProviderRuntimeSpec
from hevi.qualification.live_run import LiveQualificationRun, QualificationVerdict
from hevi.runtime.live.credentials import CredentialProvider
from hevi.runtime.live.drivers import DriverRegistry, LocalLiveDriver, default_registry
from hevi.runtime.live.status import LiveOutcome
from hevi.validation.artifact import ValidationResult


@dataclass(frozen=True)
class LocalProcessQualification:
    """The result of qualifying one LOCAL_PROCESS provider."""

    provider_id: str
    verdict: QualificationVerdict
    live: LiveQualificationRun
    source: AcquiredSource | None = None
    evidence: AcquisitionEvidence | None = None
    receipt: Any | None = None
    artifact_state: ArtifactState | None = None
    validation: ValidationResult | None = None
    reason: str = ""
    observations: dict[str, Any] = field(default_factory=dict)

    @property
    def qualified(self) -> bool:
        return self.verdict is QualificationVerdict.QUALIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "verdict": self.verdict.value,
            "reason": self.reason,
            "live": self.live.to_dict(),
            "source": self.source.to_dict() if self.source else None,
            "evidence": self.evidence.to_dict() if self.evidence else None,
            "receipt": self.receipt.to_dict() if self.receipt else None,
            "artifact_state": self.artifact_state.value if self.artifact_state else None,
            "validation": self.validation.to_dict() if self.validation else None,
            "observations": self.observations,
        }


def run_local_process_qualification(
    spec: ProviderRuntimeSpec,
    *,
    command: tuple[str, ...] | None = None,
    runner: Any | None = None,
    read_artifact: Any | None = None,
    requirements: tuple[CheckRequirement, ...] = (),
    media_type: str = "VIDEO",
    registry: DriverRegistry | None = None,
    credentials: CredentialProvider | None = None,
    artifact_id: str = "artifact-1",
    expected_checksum: str = "",
    cwd: str | None = None,
    artifact_locator: str = "",
    producer: str = "",
    validator_name: str = "ffprobe",
) -> LocalProcessQualification:
    """Qualify one LOCAL_PROCESS provider. Never fabricates a verdict."""
    from hevi.qualification.live_runner import run_live_qualification

    drivers = registry or default_registry(credentials=credentials)
    if registry is None and command is not None:
        drivers = DriverRegistry(
            drivers={
                kind: LocalLiveDriver(credentials=credentials, command=command,
                                      runner=runner, cwd=cwd,
                                      artifact_path=artifact_locator)
                for kind in (spec.health_check,)
            }
        )

    live = run_live_qualification(spec, registry=drivers, credentials=credentials)

    # ── gate 1: the runtime ──
    if live.verdict is QualificationVerdict.BLOCKED_BY_RUNTIME:
        return LocalProcessQualification(
            provider_id=spec.provider_id, verdict=live.verdict, live=live,
            reason=live.failure_reason,
        )
    if live.observed_runtime is None or not live.observed_runtime.is_live_usable:
        if live.verdict is QualificationVerdict.NOT_RUN:
            verdict = QualificationVerdict.NOT_RUN
        elif live.observed_runtime is not None and (
            live.observed_runtime.outcome is LiveOutcome.REJECTED
        ):
            # the runtime ran and declined to produce an artifact: that is a rejection
            # of the run, not an unexplained failure
            verdict = QualificationVerdict.REJECTED
        else:
            verdict = QualificationVerdict.QUALIFICATION_FAILED
        return LocalProcessQualification(
            provider_id=spec.provider_id, verdict=verdict, live=live,
            reason=live.failure_reason,
        )

    # ── gate 2: bytes ──
    # The renderer produced a locator; the proof is the bytes behind it.
    if read_artifact is None:
        return LocalProcessQualification(
            provider_id=spec.provider_id, verdict=QualificationVerdict.REJECTED, live=live,
            reason="no artifact reader supplied; a locator is not proof",
        )
    try:
        # the locator is what identifies the artifact; the request kind is not
        payload = read_artifact(artifact_locator)
    except (OSError, LookupError) as exc:
        return LocalProcessQualification(
            provider_id=spec.provider_id, verdict=QualificationVerdict.REJECTED, live=live,
            reason=f"artifact unreadable: {type(exc).__name__}",
        )
    if not payload:
        return LocalProcessQualification(
            provider_id=spec.provider_id, verdict=QualificationVerdict.REJECTED, live=live,
            reason="renderer produced no artifact bytes",
        )

    # ── P8.2: acquisition evidence from the bytes ──
    evidence = AcquisitionEvidence(
        evidence_id=f"ev-{spec.provider_id}",
        provider_id=spec.provider_id,
        source_id=artifact_id,
        checksum=checksum_bytes(payload),
        acquisition_method=AcquisitionMethod.LOCAL_READ,
    )
    source = AcquiredSource(
        source_id=artifact_id,
        provider_id=spec.provider_id,
        uri=f"render://{spec.provider_id}/{artifact_id}",
        checksum=evidence.checksum,
        evidence_id=evidence.evidence_id,
        state=AcquisitionState.ACQUIRED,
    )

    # ── P8.4: validation, from the same bytes ──
    if expected_checksum and evidence.checksum != expected_checksum:
        # bytes arrived but are not the artifact they claim to be
        return LocalProcessQualification(
            provider_id=spec.provider_id,
            verdict=QualificationVerdict.INVALID_ARTIFACT, live=live,
            source=source, evidence=evidence, reason=(
                f"artifact bytes do not match the declared digest: "
                f"expected {expected_checksum}, got {evidence.checksum}"
            ),
        )

    descriptor = describe(
        artifact_id, payload, location=source.uri, media_type=media_type
    )
    validation, artifact_state = qualify(
        descriptor, payload, requirements, validator=validator_name
    )

    if artifact_state is ArtifactState.INVALID_ARTIFACT:
        return LocalProcessQualification(
            provider_id=spec.provider_id,
            verdict=QualificationVerdict.INVALID_ARTIFACT, live=live,
            source=source, evidence=evidence, artifact_state=artifact_state,
            validation=validation, reason="artifact bytes are not the declared artifact",
        )
    if artifact_state is not ArtifactState.QUALIFIED:
        return LocalProcessQualification(
            provider_id=spec.provider_id, verdict=QualificationVerdict.REJECTED, live=live,
            source=source, evidence=evidence, artifact_state=artifact_state,
            validation=validation,
            reason=f"artifact did not qualify: {artifact_state.value}",
        )

    # ── P8.3: receipt, from the validated bytes ──
    run = ExecutionRun(f"run-{spec.provider_id}", source.source_id,
                       producer or spec.provider_id).completed()
    receipt, failure, why = issue_receipt(
        run,
        source_id=source.source_id,
        artifact_id=descriptor.artifact_id,
        read_artifact=lambda _aid: payload,
        validate=lambda _aid, body: validation
        if validation.verify_payload(body)
        else None,
        producer=producer or spec.provider_id,
    )
    if receipt is None:
        return LocalProcessQualification(
            provider_id=spec.provider_id, verdict=QualificationVerdict.REJECTED, live=live,
            source=source, evidence=evidence, artifact_state=artifact_state,
            validation=validation, reason=f"receipt refused: {failure} {why}".strip(),
        )

    # The live run only covers observation; acquisition, execution and artifact are
    # proven here. The links must be rebuilt to say so, or a qualified run would
    # report three pending links while asserting QUALIFIED.
    from hevi.qualification.live_run import LinkName, LinkState, QualificationLink

    proven = (
        QualificationLink(name=LinkName.OBSERVATION, state=LinkState.PROVEN,
                          detail=live.observed_runtime.request_kind,
                          evidence_id=f"live-{spec.provider_id}"),
        QualificationLink(name=LinkName.ACQUISITION, state=LinkState.PROVEN,
                          detail="acquisition evidence minted from the artifact bytes",
                          evidence_id=evidence.evidence_id),
        QualificationLink(name=LinkName.EXECUTION, state=LinkState.PROVEN,
                          detail="production receipt issued from the validated bytes",
                          evidence_id=receipt.receipt_id),
        QualificationLink(name=LinkName.ARTIFACT, state=LinkState.PROVEN,
                          detail=f"artifact {artifact_state.value}",
                          evidence_id=descriptor.artifact_id),
    )
    final_live = LiveQualificationRun(
        provider_id=spec.provider_id, declared_profile=spec,
        verdict=QualificationVerdict.QUALIFIED, observed_runtime=live.observed_runtime,
        execution_result=receipt.receipt_id, artifact_result=artifact_state.value,
        links=proven, differences=live.differences,
    )

    return LocalProcessQualification(
        provider_id=spec.provider_id,
        verdict=QualificationVerdict.QUALIFIED, live=final_live,
        source=source, evidence=evidence, receipt=receipt,
        artifact_state=artifact_state, validation=validation,
        observations={"bytes": len(payload)},
    )


__all__ = ["LocalProcessQualification", "run_local_process_qualification"]
