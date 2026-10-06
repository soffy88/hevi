"""HEVI P9.0 — A live qualification run: the declared provider beside the real answer.

    declared_profile  +  observed_runtime  =  a verdict, and a record of every gap

The whole purpose is to **not** collapse two things into one boolean. P8 proved that
*if* a provider works *then* the result is provable; it could not prove any provider
works. P9.0 is where that gap becomes visible, and the answer is not a verdict but a
**diff**.

```
declared:  veo3, QUEUE, requires FAL_API_KEY
observed:  credential_missing
verdict:   QUALIFICATION_FAILED      (not UNKNOWN — we know why)
```

Three verdicts, and the middle one is the point:

* ``NOT_RUN`` — nothing was attempted. No driver, no command configured. The absence of
  an attempt is recorded as an absence.
* ``QUALIFICATION_FAILED`` — something was attempted and did not hold, *including*
  ``credential_missing``. This is deliberately not ``UNKNOWN``: we know exactly what we
  do not have, and calling that unknown would hide a fixable environment condition
  behind an unfalsifiable state.
* ``QUALIFIED`` — every link was proven live: a real call answered, an artifact was
  acquired with evidence, a receipt was issued, and the artifact qualified.

``QUALIFIED`` is unreachable without all four. There is no parameter, flag or
``force=True`` that produces it without the evidence behind it — that is the whole
NO_FAKE_SUCCESS property, enforced structurally rather than by convention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from hevi.providers.runtime_specs import ProviderRuntimeSpec
from hevi.runtime.live.credentials import REDACTED
from hevi.runtime.live.status import LiveRuntimeStatus


class QualificationVerdict(StrEnum):
    """The outcome of comparing a declaration against a real answer."""

    #: nothing was attempted — no driver, or no command configured
    NOT_RUN = "not_run"
    #: the driver exists and the mechanism is declared, but the local runtime is not
    #: installed. Knows what is needed; the environment lacks it. Reported separately
    #: from NOT_RUN so a missing binary is never filed as "we did not try".
    BLOCKED_BY_RUNTIME = "blocked_by_runtime"
    #: the credential is absent, so nothing was attempted. Distinct from a *rejected*
    #: credential: one was never offered, the other was offered and refused.
    BLOCKED_BY_CREDENTIAL = "blocked_by_credential"
    #: the provider answered 5xx: it is there and it is broken. Not an auth problem and
    #: not an invalid artifact, so it must not be reported as either.
    PROVIDER_UNREACHABLE = "provider_unreachable"
    QUALIFICATION_FAILED = "qualification_failed"
    #: execution completed but produced nothing usable — non-zero exit, or no artifact
    REJECTED = "rejected"
    #: bytes arrived but are not the artifact they claim to be (checksum mismatch)
    INVALID_ARTIFACT = "invalid_artifact"
    QUALIFIED = "qualified"


class LinkName(StrEnum):
    """The four links a qualification must prove."""

    OBSERVATION = "observation"
    ACQUISITION = "acquisition"
    EXECUTION = "execution"
    ARTIFACT = "artifact"


class LinkState(StrEnum):
    PENDING = "pending"
    PROVEN = "proven"
    FAILED = "failed"
    #: proven in structure, but never against a real provider
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class DeclaredVsObserved:
    """One declaration beside one observation, and whether they agreed.

    Kept as a structure rather than a boolean so the *disagreement* is the record. A
    qualification report whose only output is ``PASS`` cannot be reviewed; one that
    prints ``declared=QUEUE observed=UNREACHABLE`` can.
    """

    field_name: str
    declared: Any
    observed: Any

    def __post_init__(self) -> None:
        if not self.field_name:
            raise ValueError("DIFF_WITHOUT_FIELD:field_name required")

    @property
    def agrees(self) -> bool:
        if self.observed is None:
            return False
        if isinstance(self.declared, tuple) and isinstance(self.observed, (list, tuple)):
            return tuple(self.declared) == tuple(self.observed)
        return bool(self.declared == self.observed)

    def describe(self) -> str:
        mark = "=" if self.agrees else "!="
        return f"{self.field_name}: declared {self.declared!r} {mark} observed {self.observed!r}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field_name,
            "declared": self.declared,
            "observed": self.observed,
            "agrees": self.agrees,
        }


@dataclass(frozen=True)
class QualificationLink:
    """One link in the chain, and the evidence that it held."""

    name: LinkName
    state: LinkState
    detail: str = ""
    evidence_id: str = ""

    def __post_init__(self) -> None:
        if self.state is LinkState.PROVEN and not self.evidence_id:
            raise ValueError(
                f"LINK_PROVEN_WITHOUT_EVIDENCE:{self.name.value}; a link may only be "
                "marked proven with something to point at"
            )

    @property
    def holds(self) -> bool:
        return self.state is LinkState.PROVEN

    def to_dict(self) -> dict[str, Any]:
        return {
            "link": self.name.value,
            "state": self.state.value,
            "detail": self.detail,
            "evidence_id": self.evidence_id,
        }


@dataclass(frozen=True)
class LiveQualificationRun:
    """One provider's declared profile beside its live result."""

    provider_id: str
    declared_profile: ProviderRuntimeSpec
    verdict: QualificationVerdict = QualificationVerdict.NOT_RUN
    observed_runtime: LiveRuntimeStatus | None = None
    execution_result: str = ""
    artifact_result: str = ""
    links: tuple[QualificationLink, ...] = ()
    differences: tuple[DeclaredVsObserved, ...] = ()
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    #: what stopped it, if anything. Never a credential value.
    failure_reason: str = ""

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("LIVE_RUN_WITHOUT_PROVIDER:provider_id required")
        if self.declared_profile.provider_id != self.provider_id:
            raise ValueError(
                f"LIVE_RUN_PROFILE_MISMATCH:{self.provider_id}; the declared profile "
                f"is for {self.declared_profile.provider_id}"
            )
        if not isinstance(self.verdict, QualificationVerdict):
            raise ValueError(f"UNKNOWN_VERDICT:{self.verdict!r}")
        if self.verdict is QualificationVerdict.NOT_RUN and self.observed_runtime is not None:
            raise ValueError(
                f"NOT_RUN_WITH_OBSERVATION:{self.provider_id}; a run that observed "
                "something was attempted"
            )
        if (
            self.verdict is QualificationVerdict.QUALIFIED
            and self.observed_runtime is None
        ):
            raise ValueError(
                f"QUALIFIED_WITHOUT_OBSERVATION:{self.provider_id}; no real call, "
                "no qualification"
            )
        if self.verdict is QualificationVerdict.QUALIFIED:
            proven = {link.name for link in self.links if link.holds}
            missing = {
                LinkName.OBSERVATION, LinkName.ACQUISITION,
                LinkName.EXECUTION, LinkName.ARTIFACT,
            } - proven
            if missing:
                raise ValueError(
                    f"QUALIFIED_WITHOUT_ALL_LINKS:{self.provider_id}: "
                    f"{sorted(link.value for link in missing)}"
                )
        if self.verdict is QualificationVerdict.QUALIFICATION_FAILED and not self.failure_reason:
            raise ValueError(
                f"FAILED_WITHOUT_REASON:{self.provider_id}; a failure must be explicable"
            )

    @property
    def agrees_with_declaration(self) -> bool:
        """Whether every declared field matched what was observed."""
        return bool(self.differences) and all(d.agrees for d in self.differences)

    @property
    def disagreements(self) -> tuple[DeclaredVsObserved, ...]:
        return tuple(d for d in self.differences if not d.agrees)

    def diff_report(self) -> str:
        if not self.differences:
            return "no comparison recorded"
        return "; ".join(d.describe() for d in self.differences)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "verdict": self.verdict.value,
            "declared_profile": self.declared_profile.to_dict(),
            "observed_runtime": (
                self.observed_runtime.to_dict() if self.observed_runtime else None
            ),
            "execution_result": self.execution_result,
            "artifact_result": self.artifact_result,
            "links": [link.to_dict() for link in self.links],
            "differences": [d.to_dict() for d in self.differences],
            "agrees_with_declaration": self.agrees_with_declaration,
            "failure_reason": self.failure_reason,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "credential_values": REDACTED,
        }


def compare_to_declaration(
    spec: ProviderRuntimeSpec, status: LiveRuntimeStatus
) -> tuple[DeclaredVsObserved, ...]:
    """Record where reality and the catalogue disagree.

    ``auth_requirements`` is compared as *presence*, never as value — comparing values
    would put a credential into a record. Presence is also the only thing a
    qualification can legitimately assert about a secret.
    """
    declared_creds = tuple(sorted(spec.auth_requirements))
    observed_creds = tuple(sorted(status.credential_names))
    return (
        DeclaredVsObserved("health_check", spec.health_check.value, status.request_kind),
        DeclaredVsObserved(
            "credentials_present", bool(declared_creds), bool(observed_creds)
        ),
        DeclaredVsObserved(
            "live_outcome", "reachable", "reachable" if status.is_live_usable else status.outcome.value
        ),
    )


__all__ = [
    "DeclaredVsObserved",
    "LinkName",
    "LinkState",
    "LiveQualificationRun",
    "QualificationLink",
    "QualificationVerdict",
    "compare_to_declaration",
]
