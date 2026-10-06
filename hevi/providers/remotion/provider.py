"""HEVI P9.1.c — Remotion's provider declaration.

Declaration only. This module renders nothing, inspects nothing and decides nothing.

Remotion arrived in HEVI as ``hevi/renderers/remotion.py`` — a renderer that was never
a provider. It had no catalogue entry, so it was invisible to ``ProviderPolicy``: a
renderer invocable by ~60 modules without ever appearing in a decision record. Promoting
it means giving it an identity row so policy can reason about it.

The declaration below is a *fact about Remotion*, not a capability HEVI wishes it had:

* ``LOCAL_PROCESS`` — it is a node process driven as a subprocess, declared in
  ``hevi/providers/runtime_specs.py`` like every other observed provider.
* ``GENERATED`` — it synthesises frames. It does not license stock, so its licence
  class is not ``LICENSED``.
* ``NOT_ADOPTED`` — the locked composition variant is declared but never routed.

The taxonomy itself lives in ``hevi/providers/facts.py`` and is frozen by P7.3. This
module references it; it does not extend it, and adding Remotion changed no policy code.
"""

from __future__ import annotations

from hevi.providers.facts import (
    ProviderCapabilityState,
    ProviderKind,
    ProviderLicenseClass,
    ProviderLocality,
    ProviderProfile,
)

#: The provider id used everywhere: catalogue, runtime spec, driver, decision records.
PROVIDER_ID = "remotion"

#: Where Remotion runs. Declared from how it is invoked — a node subprocess — not from
#: the fact that its name contains no locality word.
LOCALITY = ProviderLocality.LOCAL

#: Remotion renders video and nothing else. Stated as a tuple so a later addition is a
#: visible contract change rather than an invisible widening.
MEDIA_TYPES: tuple[str, ...] = ("VIDEO",)

LICENSE_CLASS = ProviderLicenseClass.GENERATED

#: The frozen P7.2 taxonomy allows one capability state per profile, so the per-capability
#: map collapses to a single declared state here.
CAPABILITY_STATE = ProviderCapabilityState.AVAILABLE

KIND = ProviderKind.VIDEO


def profile() -> ProviderProfile:
    """Remotion's declared facts. The single construction site for its identity."""
    return ProviderProfile(
        provider_id=PROVIDER_ID,
        kind=KIND,
        locality=LOCALITY,
        license_class=LICENSE_CLASS,
        capability_state=CAPABILITY_STATE,
        capabilities=("t2v", "motion_graphics", "explainer", "captions"),
    )


def declaration() -> dict[str, str]:
    """A serialisable summary, for audit records."""
    return {
        "provider_id": PROVIDER_ID,
        "kind": KIND.value,
        "locality": LOCALITY.value,
        "license_class": LICENSE_CLASS.value,
        "runtime_mechanism": "local_process",
        "media_types": ",".join(MEDIA_TYPES),
    }


__all__ = [
    "CAPABILITY_STATE",
    "KIND",
    "LICENSE_CLASS",
    "LOCALITY",
    "MEDIA_TYPES",
    "PROVIDER_ID",
    "declaration",
    "profile",
]
