"""HEVI P9.0 — Live runtime status: an observation of a call that was actually made.

This is **not** :class:`~hevi.runtime.provider.models.ProviderRuntimeStatus`, and the
distinction is the point.

```
ProviderRuntimeStatus   "we asked, here is the answer"     P8.1, declared mechanism
LiveRuntimeStatus       "we asked a REAL provider"          P9.0, real answer
```

P8.1 established that observing a provider is a third question, separate from what it
is and whether it may be used. P9.0 does not change that separation — it fills it in
with evidence that a real endpoint answered.

So this model carries no ``locality``, no ``license_class``, no ``capabilities`` and no
opinion about eligibility. It records what came back, when, and how long it took. A
provider that answers does not thereby become local, licensed or approved.

It also records *what was asked*, because a live observation without a subject is not
evidence of anything: ``request_kind`` and ``endpoint_kind`` travel with the outcome so
a record can be read without trusting the reader.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class LiveOutcome(StrEnum):
    """What happened when a real provider was asked.

    ``CREDENTIAL_MISSING`` is a distinct member rather than a flavour of ``FAILED``.
    A missing token is an environment condition; a provider returning 503 is a provider
    condition; a driver raising is a code condition. Collapsing them is how "we never
    tried" gets reported as "the provider is broken" — which would put a fact about the
    provider into a record that has no standing to make one.
    """

    OK = "ok"
    CREDENTIAL_MISSING = "credential_missing"
    UNREACHABLE = "unreachable"
    REJECTED = "rejected"
    DRIVER_ERROR = "driver_error"
    NOT_ATTEMPTED = "not_attempted"
    #: The mechanism is declared and the driver exists, but the local runtime is not
    #: installed. Distinct from NOT_ATTEMPTED: nothing was tried because something
    #: specific is known to be missing, which is a different statement from "we did
    #: not try" and names a fixable cause.
    RUNTIME_UNAVAILABLE = "runtime_unavailable"

    @property
    def is_live(self) -> bool:
        """True only when a real request produced this answer."""
        return self is LiveOutcome.OK


@dataclass(frozen=True)
class LiveRuntimeStatus:
    """One real call's outcome. An observation, never a fact."""

    provider_id: str
    outcome: LiveOutcome
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    latency_ms: int | None = None
    status_code: int | None = None
    request_kind: str = ""
    reason: str = ""
    #: names of the credentials the runtime spec required, never their values
    credential_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("LIVE_STATUS_WITHOUT_PROVIDER:provider_id required")
        if not isinstance(self.outcome, LiveOutcome):
            raise ValueError(f"UNKNOWN_LIVE_OUTCOME:{self.outcome!r}")
        if self.outcome is LiveOutcome.OK and self.latency_ms is None:
            raise ValueError(
                f"LIVE_OK_WITHOUT_LATENCY:{self.provider_id}; a successful live call "
                "must record how long it took"
            )
        if self.outcome is not LiveOutcome.OK and not self.reason:
            raise ValueError(
                f"LIVE_FAILURE_WITHOUT_REASON:{self.provider_id}; every unsuccessful "
                "observation must say why"
            )
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError(f"NEGATIVE_LATENCY:{self.provider_id}")

    @property
    def is_live_usable(self) -> bool:
        """Fail-closed: only a real, timed, successful call is usable."""
        return self.outcome.is_live

    @property
    def was_attempted(self) -> bool:
        """Whether anything was actually run.

        ``RUNTIME_UNAVAILABLE`` did not run either — the binary is not installed — so
        it counts as not attempted, like ``NOT_ATTEMPTED``.
        """
        return self.outcome not in (
            LiveOutcome.NOT_ATTEMPTED, LiveOutcome.RUNTIME_UNAVAILABLE,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "outcome": self.outcome.value,
            "checked_at": self.checked_at.isoformat(),
            "latency_ms": self.latency_ms,
            "status_code": self.status_code,
            "request_kind": self.request_kind,
            "reason": self.reason,
            "credential_names": list(self.credential_names),
        }


__all__ = ["LiveOutcome", "LiveRuntimeStatus"]
