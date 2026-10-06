"""HEVI P9.0 — Credential access, and the boundary it may not cross.

A credential is the most dangerous string in the system. It is the one value that must
never reach a catalogue entry, a decision record, a receipt, a log line or a document,
because every one of those gets serialised and shared.

So this module is shaped to make leaking awkward rather than merely discouraged:

* :class:`Credential` never renders itself. ``repr``/``str``/``to_dict`` all redact, so
  a stray ``f"{credential}"`` in a log yields ``***`` and not a token.
* Values are handed to a driver through :meth:`Credential.resolve`, which returns a
  plain ``str`` for the driver to use and nothing else. A driver cannot put the value
  into a record it did not already have.
* Resolution is by **name**, taken from the declared ``auth_requirements``. Nothing here
  knows a provider's credentials; it only reads what the runtime spec already said was
  required.

What this may never do
----------------------
Write a credential — or its presence, or its absence — into ``ProviderCatalogue``,
``ProviderDecision`` or ``ProviderRuntimeStatus``. Those describe what a provider *is*
or what it may do; a credential is neither. Recording "this provider has no token" in
the catalogue would make a transient environment condition look like a permanent fact,
which is precisely the conflation P7.3 closed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

REDACTED = "***"

#: Environment variable names that must never be read as a credential, whatever a
#: runtime spec asks for. Reading these would put a credential into an outbound header.
FORBIDDEN_ENV_NAMES = frozenset({"PATH", "HOME", "PWD", "SHELL", "USER", "TERM"})


@dataclass(frozen=True)
class Credential:
    """One named secret. Its value is reachable only by explicit resolution."""

    name: str
    value: str

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("CREDENTIAL_WITHOUT_NAME:name required")
        if self.name in FORBIDDEN_ENV_NAMES:
            raise ValueError(
                f"CREDENTIAL_NAME_NOT_A_SECRET:{self.name}; refusing to treat a "
                "non-secret environment variable as a credential"
            )

    def resolve(self) -> str:
        """The value, for a driver to use. Do not store it."""
        return self.value

    def __repr__(self) -> str:
        return f"Credential(name={self.name!r}, value={REDACTED!r})"

    __str__ = __repr__

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "value": REDACTED}

    @property
    def is_present(self) -> bool:
        return bool(self.value)


class CredentialMissing(Exception):
    """Raised when a required credential is absent.

    Distinct from a probe failure on purpose. "There is no token" is an environment
    condition; "the endpoint refused the request" is a provider condition. P9.0 reports
    them separately so a missing credential is never mistaken for a broken provider.
    """

    def __init__(self, name: str) -> None:
        super().__init__(f"CREDENTIAL_MISSING:{name}")
        self.name = name


class CredentialProvider(Protocol):
    """Supplies credentials by name. Implementations may read any secret store."""

    def get(self, name: str) -> Credential | None: ...


class EnvironmentCredentialProvider:
    """Reads credentials from the process environment.

    The default, because it needs no infrastructure and keeps secrets out of source.
    Values are read on demand and never cached in a record.
    """

    def __init__(self, environ: dict[str, str] | None = None) -> None:
        self._environ = environ if environ is not None else dict(os.environ)

    def get(self, name: str) -> Credential | None:
        value = self._environ.get(name)
        if not value:
            return None
        return Credential(name=name, value=value)

    def require(self, names: tuple[str, ...]) -> dict[str, Credential]:
        """Resolve every name, or name the first one that is missing.

        Raises :class:`CredentialMissing` rather than returning a partial set, so a
        driver can never proceed with half its credentials and report a confusing
        failure from the other half.
        """
        resolved: dict[str, Credential] = {}
        for name in names:
            credential = self.get(name)
            if credential is None:
                raise CredentialMissing(name)
            resolved[name] = credential
        return resolved

    def missing(self, names: tuple[str, ...]) -> tuple[str, ...]:
        """Which required names are absent — safe to record, contains no values."""
        return tuple(name for name in names if not self._environ.get(name))


class StaticCredentialProvider:
    """An in-memory provider, for tests and for injecting values from a secret store."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = dict(values)

    def get(self, name: str) -> Credential | None:
        value = self._values.get(name)
        return Credential(name=name, value=value) if value else None

    def missing(self, names: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(name for name in names if not self._values.get(name))


__all__ = [
    "REDACTED",
    "Credential",
    "CredentialMissing",
    "CredentialProvider",
    "EnvironmentCredentialProvider",
    "StaticCredentialProvider",
]
