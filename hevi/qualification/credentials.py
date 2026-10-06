"""HEVI P9.2 — credential resolution, without ever resolving a secret.

A credential resolver that *returns* the value is one leak away from a log line. This
one reports **presence only**:

    CredentialResolution(provider_id="wan_2_7", required=("WAVESPEED_API_KEY",),
                         resolved=("WAVESPEED_API_KEY",))

Names are configuration; values are secrets. ``resolved`` lists which names were found,
never what they contain, and the class has no field in which a value could be placed.

Sources, in order: explicit injection, then the process environment. Which source
supplied a credential is recorded as ``source`` so a qualification report can say
"injected" or "environment" without revealing anything.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CredentialResolution:
    """Presence, never value."""

    provider_id: str
    required: tuple[str, ...] = ()
    resolved: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    source: str = "environment"

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("CREDENTIAL_RESOLUTION_WITHOUT_PROVIDER:provider_id required")
        overlap = set(self.resolved) & set(self.missing)
        if overlap:
            raise ValueError(
                f"CREDENTIAL_NAME_BOTH_PRESENT_AND_MISSING:{sorted(overlap)}"
            )

    @property
    def complete(self) -> bool:
        """True only when every required name was found."""
        return not self.missing and bool(self.required)

    def to_dict(self) -> dict[str, object]:
        # Names only. There is deliberately no value field to leak.
        return {
            "provider_id": self.provider_id,
            "required": list(self.required),
            "resolved": list(self.resolved),
            "missing": list(self.missing),
            "complete": self.complete,
            "source": self.source,
        }


class CredentialSource(Protocol):
    """Supplies credential *presence*. Implementations may hold values privately."""

    def present(self) -> tuple[str, ...]: ...


class EnvironmentCredentials:
    """Presence from the process environment."""

    name = "environment"

    def __init__(self, environ: dict[str, str] | None = None) -> None:
        self._environ = environ if environ is not None else dict(os.environ)

    def present(self) -> tuple[str, ...]:
        return tuple(name for name, value in self._environ.items() if value)


class InjectedCredentials:
    """Presence from names supplied at construction. No value is ever accepted.

    A test, a secret store, or a config loader can all be reduced to a set of *names*.
    That is deliberate: the narrower this seam is, the less it can leak.
    """

    name = "injected"

    def __init__(self, names: tuple[str, ...]) -> None:
        self._names = tuple(names)

    def present(self) -> tuple[str, ...]:
        return self._names


def resolve(
    provider_id: str,
    required: tuple[str, ...],
    *,
    source: CredentialSource | None = None,
) -> CredentialResolution:
    """Report which required names are present. Never returns a value."""
    if not required:
        return CredentialResolution(provider_id=provider_id, source="none")
    chosen = source or EnvironmentCredentials()
    available = set(chosen.present())
    resolved = tuple(name for name in required if name in available)
    missing = tuple(name for name in required if name not in available)
    return CredentialResolution(
        provider_id=provider_id, required=tuple(required), resolved=resolved,
        missing=missing, source=getattr(chosen, "name", "custom"),
    )


__all__ = [
    "CredentialResolution",
    "CredentialSource",
    "EnvironmentCredentials",
    "InjectedCredentials",
    "resolve",
]
