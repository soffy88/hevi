"""HEVI P8.1 — Probing, and the separation it must preserve.

This module turns a transport-level answer into a :class:`ProviderRuntimeStatus`.
It contains no network code of its own: the existing probe in
``hevi.provider_policy.runtime.probe_provider`` already performs the HTTP request
and already owns per-provider endpoint and credential handling. Duplicating it would
create a second probe authority — the same class of fork P7.3 just closed for facts.

What this module adds is only the mapping, and the rules about what may be observed:

* A probe **never** writes to ``ProviderCatalogue``. Facts are declared once, in one
  place, and observation cannot edit them.
* A probe **never** fills a fact field. A provider that is unreachable is not thereby
  remote; a provider that answers quickly is not thereby licensed.
* A provider with no probe configuration is ``UNKNOWN``, not ``UNAVAILABLE``. Those
  are different facts: one is "we asked and it did not answer", the other is "we
  cannot ask".
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from hevi.provider_policy.runtime import PROVIDER_SPECS, probe_provider
from hevi.runtime.provider.models import ProviderRuntimeStatus, RuntimeAvailability

#: Transport seam. The default implementation delegates to the existing probe
#: authority; tests substitute a scripted one so no network is required.
ProbeFn = Callable[[str], Awaitable[dict[str, Any]]]


class _Probe(Protocol):
    async def __call__(self, provider_id: str) -> dict[str, Any]: ...


#: Providers with a declared probe configuration. This is the existing authority
#: (``PROVIDER_SPECS``); P8.1 does not maintain a second list of what is probeable.
PROBEABLE: frozenset[str] = frozenset(spec.provider_id for spec in PROVIDER_SPECS)


def is_probeable(provider_id: str) -> bool:
    """Whether a probe configuration exists for this provider."""
    return provider_id in PROBEABLE


def unknown_status(
    provider_id: str, reason: str, *, checked_at: datetime | None = None
) -> ProviderRuntimeStatus:
    """A provider we could not ask about. Fail-closed, and says so."""
    return ProviderRuntimeStatus(
        provider_id=provider_id,
        availability=RuntimeAvailability.UNKNOWN,
        reachable=False,
        latency_ms=None,
        checked_at=checked_at or datetime.now(UTC),
        failure_reason=reason,
    )


async def _default_probe(provider_id: str) -> dict[str, Any]:
    """Delegate to the existing probe authority. No second implementation."""
    return await probe_provider(provider_id)


async def observe_provider(
    provider_id: str,
    *,
    probe: ProbeFn | None = None,
    checked_at: datetime | None = None,
) -> ProviderRuntimeStatus:
    """Probe one provider and record what happened.

    Never raises for an unreachable or unconfigured provider: an observation is not
    an assertion, and "it did not answer" is a legitimate result to record.
    """
    probe_fn = probe or _default_probe

    if not is_probeable(provider_id):
        return unknown_status(
            provider_id,
            "no_probe_configuration:runtime observation is not defined for this provider",
            checked_at=checked_at,
        )

    try:
        raw = await probe_fn(provider_id)
    except Exception as exc:
        return ProviderRuntimeStatus(
            provider_id=provider_id,
            availability=RuntimeAvailability.UNAVAILABLE,
            reachable=False,
            latency_ms=None,
            checked_at=checked_at or datetime.now(UTC),
            failure_reason=f"probe_error:{type(exc).__name__}:{exc}",
        )

    return _status_from_probe_result(provider_id, raw, checked_at=checked_at)


def _status_from_probe_result(
    provider_id: str, raw: dict[str, Any], *, checked_at: datetime | None = None
) -> ProviderRuntimeStatus:
    """Map an existing probe result onto the observation model.

    Deliberately narrow: ``reachable`` is the only field read out of the raw result
    that survives. The raw dict also carries provider *configuration* — endpoints,
    required env vars, setup text — and none of that is an observation, so none of it
    is copied across. A model that grew a ``locality`` field would be a second fact
    source; this function is the place that would have to grow it, which is why it
    reads exactly one key.
    """
    reachable = bool(raw.get("reachable", False))
    latency = raw.get("latency_ms")
    if latency is not None:
        latency = int(latency)
    return ProviderRuntimeStatus(
        provider_id=provider_id,
        availability=(
            RuntimeAvailability.AVAILABLE
            if reachable
            else RuntimeAvailability.UNAVAILABLE
        ),
        reachable=reachable,
        latency_ms=latency,
        checked_at=checked_at or datetime.now(UTC),
        failure_reason=None if reachable else (raw.get("error") or "unreachable"),
    )


__all__ = [
    "PROBEABLE",
    "ProbeFn",
    "is_probeable",
    "observe_provider",
    "unknown_status",
]
