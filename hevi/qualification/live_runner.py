"""HEVI P9.0 — Running one live qualification, honestly.

The runner makes exactly one decision: given what was declared and what actually
happened, what may be reported?

Everything else is fail-closed, and the order of the gates is what stops a harness from
manufacturing a pass:

    no driver for the declared mechanism  -> NOT_RUN              (honest absence)
    driver attempted, credential absent   -> QUALIFICATION_FAILED (known cause)
    driver attempted, call failed         -> QUALIFICATION_FAILED (known cause)
    call answered                         -> compare declared vs observed
    all four links proven                 -> QUALIFIED

The one thing that matters structurally: ``QUALIFIED`` requires four ``PROVEN`` links,
each carrying an ``evidence_id``, and the model refuses to be constructed otherwise.
There is no flag that relaxes it. A harness that can be told to report success is not a
harness, it is a press release generator.

And the diff is always recorded — including when everything agrees — so a report can be
reviewed rather than believed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from hevi.providers.runtime_specs import ProviderRuntimeSpec
from hevi.qualification.live_run import (
    LinkName,
    LinkState,
    LiveQualificationRun,
    QualificationLink,
    QualificationVerdict,
    compare_to_declaration,
)
from hevi.runtime.live.credentials import CredentialProvider
from hevi.runtime.live.drivers import DriverRegistry, default_registry, redact
from hevi.runtime.live.status import LiveOutcome, LiveRuntimeStatus


def _pending_links(detail: str) -> tuple[QualificationLink, ...]:
    return tuple(
        QualificationLink(name=name, state=LinkState.PENDING, detail=detail)
        for name in (LinkName.OBSERVATION, LinkName.ACQUISITION,
                     LinkName.EXECUTION, LinkName.ARTIFACT)
    )


def run_live_qualification(
    spec: ProviderRuntimeSpec,
    *,
    registry: DriverRegistry | None = None,
    credentials: CredentialProvider | None = None,
    acquisition_evidence_id: str = "",
    production_receipt_id: str = "",
    artifact_state: str = "",
    execute: Any | None = None,
    started_at: datetime | None = None,
) -> LiveQualificationRun:
    """Attempt one provider against reality and report what differed.

    ``acquisition_evidence_id``, ``production_receipt_id`` and ``artifact_state`` are
    supplied by the caller because P9.1 is what performs those steps. Passing nothing
    leaves those links pending, and a run with pending links is never ``QUALIFIED`` —
    so an incomplete qualification reports itself as incomplete rather than as a pass.
    """
    moment = started_at or datetime.now(UTC)
    drivers = registry or default_registry(credentials=credentials)
    driver = drivers.driver_for(spec)

    if driver is None:
        reason = (
            f"no live driver for declared mechanism {spec.health_check.value}; "
            "nothing was attempted"
        )
        return LiveQualificationRun(
            provider_id=spec.provider_id,
            declared_profile=spec,
            verdict=QualificationVerdict.NOT_RUN,
            links=_pending_links(reason),
            failure_reason=reason,
            started_at=moment,
            finished_at=datetime.now(UTC),
        )

    result = driver.attempt(spec)
    status = result.status
    differences = compare_to_declaration(spec, status)

    if status.outcome is LiveOutcome.RUNTIME_UNAVAILABLE:
        # Knows what is needed; the environment lacks it. Filed separately from
        # NOT_RUN so a missing binary is never reported as "we did not try".
        reason = redact(status.reason)
        return LiveQualificationRun(
            provider_id=spec.provider_id,
            declared_profile=spec,
            verdict=QualificationVerdict.BLOCKED_BY_RUNTIME,
            links=_pending_links(f"blocked by a missing local runtime: {reason}"),
            failure_reason=reason,
            started_at=moment,
            finished_at=datetime.now(UTC),
        )

    if not status.was_attempted:
        reason = redact(status.reason or status.outcome.value)
        return LiveQualificationRun(
            provider_id=spec.provider_id,
            declared_profile=spec,
            verdict=QualificationVerdict.NOT_RUN,
            links=_pending_links(f"nothing was attempted: {reason}"),
            failure_reason=reason,
            started_at=moment,
            finished_at=datetime.now(UTC),
        )

    if not status.is_live_usable:
        reason = redact(status.reason or status.outcome.value)
        failed_links = (
            QualificationLink(
                name=LinkName.OBSERVATION, state=LinkState.FAILED,
                detail=f"{status.outcome.value}: {reason}",
            ),
            *(
                QualificationLink(name=name, state=LinkState.PENDING,
                                  detail="not attempted: the live call did not succeed")
                for name in (LinkName.ACQUISITION, LinkName.EXECUTION, LinkName.ARTIFACT)
            ),
        )
        return LiveQualificationRun(
            provider_id=spec.provider_id,
            declared_profile=spec,
            verdict=QualificationVerdict.QUALIFICATION_FAILED,
            observed_runtime=status,
            links=failed_links,
            differences=differences,
            failure_reason=f"{status.outcome.value}: {reason}",
            started_at=moment,
            finished_at=datetime.now(UTC),
        )

    execution_result, execution_detail = "", "execution not performed"
    if execute is not None:
        execution_result, execution_detail = execute(spec, result)

    links: list[QualificationLink] = [
        QualificationLink(
            name=LinkName.OBSERVATION, state=LinkState.PROVEN,
            detail=f"{status.request_kind} answered in {status.latency_ms}ms",
            evidence_id=f"live-{spec.provider_id}-{status.checked_at.timestamp():.0f}",
        ),
        QualificationLink(
            name=LinkName.ACQUISITION,
            state=LinkState.PROVEN if acquisition_evidence_id else LinkState.PENDING,
            detail="acquisition evidence supplied" if acquisition_evidence_id
            else "no acquisition evidence supplied",
            evidence_id=acquisition_evidence_id,
        ),
        QualificationLink(
            name=LinkName.EXECUTION,
            state=LinkState.PROVEN if production_receipt_id else LinkState.PENDING,
            detail=execution_detail,
            evidence_id=production_receipt_id,
        ),
        QualificationLink(
            name=LinkName.ARTIFACT,
            state=LinkState.PROVEN if artifact_state else LinkState.PENDING,
            detail=artifact_result_or_detail(artifact_state, execution_result),
            evidence_id=artifact_state,
        ),
    ]
    frozen = tuple(links)
    qualified = all(link.holds for link in frozen)

    return LiveQualificationRun(
        provider_id=spec.provider_id,
        declared_profile=spec,
        verdict=QualificationVerdict.QUALIFIED if qualified
        else QualificationVerdict.QUALIFICATION_FAILED,
        observed_runtime=status,
        execution_result=execution_result,
        artifact_result=artifact_state,
        links=frozen,
        differences=differences,
        failure_reason="" if qualified else "one or more links are not proven",
        started_at=moment,
        finished_at=datetime.now(UTC),
    )


def artifact_result_or_detail(artifact_state: str, execution_result: str) -> str:
    if artifact_state:
        return f"artifact {artifact_state}"
    return f"execution reported: {execution_result or 'nothing'}"


def qualify_many(
    specs: tuple[ProviderRuntimeSpec, ...],
    *,
    registry: DriverRegistry | None = None,
    credentials: CredentialProvider | None = None,
    **kwargs: Any,
) -> tuple[LiveQualificationRun, ...]:
    """Run a batch, preserving every result including the failures.

    A batch that filtered out failures would report a healthier fleet than exists, which
    is the error this harness exists to avoid.
    """
    return tuple(
        run_live_qualification(
            spec, registry=registry, credentials=credentials, **kwargs
        )
        for spec in specs
    )


__all__ = ["LiveRuntimeStatus", "qualify_many", "run_live_qualification"]
