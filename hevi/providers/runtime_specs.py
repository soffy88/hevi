"""HEVI P8.1.5 — Runtime observation coverage.

P8.1 established that runtime observation is a *third* question, separate from what a
provider is and whether it may be used. It also exposed the reason that separation
was worth enforcing: of the 16 providers in the catalogue, only 2 had any way to be
observed at all.

    probeable   2   longcat, voicebox
    unobserved 14   every video generator

This module closes that gap. It declares **how to observe** each provider — the same
question ``hevi/provider_policy/runtime.py::PROVIDER_SPECS`` answers for the
infrastructure fleet — and nothing else.

Two boundaries, both deliberate
--------------------------------

**This is not provider identity.** ``ProviderProfile`` (in ``hevi/providers/facts.py``)
says what a provider is: locality, licence class, capability. This module may not
restate any of it, and a ``locality`` field here would be a second fact source. Local
providers are declared as ``LOCAL_PROCESS``/``CLI`` *because that is how they are
observed*, not because of what they are.

**This is not a second probe client.** This file is data. It says which kind of check
applies and what an operator must configure; the existing probe in
``hevi/provider_policy/runtime.py`` and P8.1's ``observe_provider`` remain the only
things that perform a check.

Every entry below is grounded in how the provider is actually invoked in this
codebase, not inferred from its name — the inference P7.1 deleted:

    wan_local      subprocess (Wan2GP + CausVid)          -> CLI
    ltx2_local     routes to wan_local                     -> CLI
    h3_local       loopback service on 127.0.0.1           -> LOCAL_PROCESS
    manim          in-process library render               -> LOCAL_PROCESS
    veo3, kling_v2, hailuo   fal.ai queue submission       -> QUEUE
    happyhorse_1_1, wan_2_7  WaveSpeed HTTP                -> HTTP
    *_maas                     Alibaba Bailian HTTP        -> HTTP

``auth_requirements`` holds environment variable **names** only, exactly as
``ProviderSpec.required_env`` already does. Names are configuration; values are
secrets, and a secret must never reach a status, a log or a document.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from hevi.providers.facts import PROVIDER_CATALOGUE


class HealthCheckKind(StrEnum):
    """How a provider is checked.

    Not unified behind HTTP. A video model may be a hosted API, a local daemon, a
    subprocess on the render host, or a queue that reports liveness out of band.
    Forcing all four into one HTTP shape would mean probing a subprocess with an HTTP
    request, and declaring victory or failure based on the wrong mechanism.
    """

    HTTP = "http"
    CLI = "cli"
    LOCAL_PROCESS = "local_process"
    QUEUE = "queue"


@dataclass(frozen=True)
class ProviderRuntimeSpec:
    """How to observe one provider. Never what it is.

    Field names are restricted on purpose: no ``locality``, no ``license_class``, no
    ``capabilities``, no ``quality``. Those belong to ``ProviderProfile``.
    """

    provider_id: str
    health_check: HealthCheckKind
    auth_requirements: tuple[str, ...] = ()
    target: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("RUNTIME_SPEC_WITHOUT_ID:provider_id required")
        if not isinstance(self.health_check, HealthCheckKind):
            raise ValueError(f"UNKNOWN_HEALTH_CHECK_KIND:{self.health_check!r}")
        for name in self.auth_requirements:
            if not name.isupper():
                raise ValueError(
                    f"AUTH_REQUIREMENT_MUST_BE_A_NAME:{name!r}; this registry holds "
                    "variable names, never values"
                )

    @property
    def requires_credentials(self) -> bool:
        return bool(self.auth_requirements)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "health_check": self.health_check.value,
            "auth_requirements": list(self.auth_requirements),
            "target": self.target,
            "notes": self.notes,
        }


_HTTP = HealthCheckKind.HTTP
_CLI = HealthCheckKind.CLI
_LOCAL = HealthCheckKind.LOCAL_PROCESS
_QUEUE = HealthCheckKind.QUEUE

#: Observation coverage for the video fleet, which PROVIDER_SPECS never covered.
#: Declared per provider because each is genuinely a different mechanism — the point
#: of P8.1.5 is that they are not interchangeable, not that they share one probe.
_VIDEO_RUNTIME_SPECS: tuple[ProviderRuntimeSpec, ...] = (
    ProviderRuntimeSpec(
        "wan_local", _CLI, (), "wan2gp",
        "Wan2GP + CausVid driven through subprocess on the render host",
    ),
    ProviderRuntimeSpec(
        "ltx2_local", _CLI, (), "wan2gp",
        "no local LTX-2 implementation exists; routes to wan_local",
    ),
    # ── node-process video renderer (P9.1.c) ──
    ProviderRuntimeSpec(
        "hyperframes", _LOCAL, (), "in_process",
        "in-process HTML renderer; observation mechanism is the render call itself",
    ),
    ProviderRuntimeSpec(
        "remotion", _LOCAL, (), "npx",
        "node project under hevi-remotion/; rendered via `npx remotion render`",
    ),
    ProviderRuntimeSpec(
        "h3_local", _LOCAL, ("POST_INTERP", "POST_UPSCALE"), "127.0.0.1",
        "loopback service; stage toggles are read from the environment",
    ),
    ProviderRuntimeSpec(
        "manim", _LOCAL, (), "manim",
        "in-process library render; nothing to dial",
    ),
    ProviderRuntimeSpec(
        "veo3", _QUEUE, ("FAL_API_KEY",), "fal.ai",
        "fal.ai queue submission; liveness is out of band from the response",
    ),
    ProviderRuntimeSpec(
        "kling_v2", _QUEUE, ("FAL_API_KEY",), "fal.ai",
        "fal.ai queue submission",
    ),
    ProviderRuntimeSpec(
        "hailuo", _QUEUE, ("FAL_API_KEY",), "fal.ai",
        "fal.ai queue submission",
    ),
    ProviderRuntimeSpec(
        "ltx2_cloud", _QUEUE, ("FAL_API_KEY",), "fal.run",
        "endpoint resolved from hevi.cost.pricing_table.LTX2_ENDPOINTS",
    ),
    ProviderRuntimeSpec(
        "happyhorse_1_1", _HTTP, ("WAVESPEED_API_KEY",), "api.wavespeed.ai",
        "WaveSpeed resale of HappyHorse 1.1",
    ),
    ProviderRuntimeSpec(
        "wan_2_7", _HTTP, ("WAVESPEED_API_KEY",), "api.wavespeed.ai",
        "WaveSpeed resale of Wan 2.7",
    ),
    ProviderRuntimeSpec(
        "happyhorse_1_1_maas", _HTTP, ("ALIBABA_MAAS_API_KEY",), "ALIBABA_MAAS_HOST",
        "Alibaba Bailian direct",
    ),
    ProviderRuntimeSpec(
        "happyhorse_1_1_maas_lock", _HTTP, ("ALIBABA_MAAS_API_KEY",), "ALIBABA_MAAS_HOST",
        "locked variant: declared for coverage, never routed",
    ),
    ProviderRuntimeSpec(
        "wan_2_7_maas", _HTTP, ("ALIBABA_MAAS_API_KEY",), "ALIBABA_MAAS_HOST",
        "Alibaba Bailian direct",
    ),
)


class RuntimeSpecRegistry:
    """Lookup only. Coverage accounting lives here; probing does not."""

    def __init__(self, specs: tuple[ProviderRuntimeSpec, ...] = ()) -> None:
        self._specs: dict[str, ProviderRuntimeSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: ProviderRuntimeSpec) -> ProviderRuntimeSpec:
        if spec.provider_id in self._specs:
            raise ValueError(f"RUNTIME_SPEC_DUPLICATE:{spec.provider_id}")
        self._specs[spec.provider_id] = spec
        return spec

    def get(self, provider_id: str) -> ProviderRuntimeSpec | None:
        return self._specs.get(provider_id)

    def resolve(self, provider_id: str) -> ProviderRuntimeSpec:
        spec = self.get(provider_id)
        if spec is None:
            raise KeyError(f"NO_RUNTIME_SPEC:{provider_id}")
        return spec

    def has(self, provider_id: str) -> bool:
        return provider_id in self._specs

    def list_ids(self) -> list[str]:
        return sorted(self._specs)

    def by_kind(self, kind: HealthCheckKind) -> tuple[ProviderRuntimeSpec, ...]:
        return tuple(s for s in self._specs.values() if s.health_check is kind)

    def credentialed_ids(self) -> tuple[str, ...]:
        return tuple(sorted(s.provider_id for s in self._specs.values()
                            if s.requires_credentials))

    def coverage_report(self) -> dict[str, Any]:
        """Which catalogue providers can be observed, and which cannot.

        Reported rather than assumed, because P8.1's gap was invisible until someone
        asked the question. Unknown entries are named explicitly: a silent default
        would recreate the exact problem this module exists to close.
        """
        catalogue = set(PROVIDER_CATALOGUE.list_ids())
        covered = catalogue & set(self._specs)
        uncovered = sorted(catalogue - set(self._specs))
        spec_only = sorted(set(self._specs) - catalogue)
        return {
            "total_catalogue": len(catalogue),
            "probeable": len(covered),
            "unobserved": len(uncovered),
            "unobserved_ids": uncovered,
            "spec_without_catalogue_entry": spec_only,
            "by_kind": {
                kind.value: sorted(s.provider_id for s in self.by_kind(kind))
                for kind in HealthCheckKind
            },
            "full_coverage": not uncovered,
        }

    def to_dict(self) -> dict[str, Any]:
        return {pid: self._specs[pid].to_dict() for pid in self.list_ids()}


#: The observation-coverage authority for the video fleet.
RUNTIME_SPECS = RuntimeSpecRegistry(_VIDEO_RUNTIME_SPECS)


def get_runtime_spec(provider_id: str) -> ProviderRuntimeSpec | None:
    """Declared observation coverage for a provider, or ``None``."""
    return RUNTIME_SPECS.get(provider_id)


def coverage_report() -> dict[str, Any]:
    """See :meth:`RuntimeSpecRegistry.coverage_report`."""
    return RUNTIME_SPECS.coverage_report()


def observed_provider_ids() -> frozenset[str]:
    """Every provider with *some* declared way to observe it.

    Two authorities answer this question and neither is complete alone:
    ``PROVIDER_SPECS`` covers the infrastructure fleet, this registry covers the
    video fleet. P8.1's gap was visible only because the two were never added up —
    2 of 16 observed, from one registry, while the other had never been consulted.
    """
    from hevi.provider_policy.runtime import PROVIDER_SPECS

    return frozenset(RUNTIME_SPECS.list_ids()) | frozenset(
        spec.provider_id for spec in PROVIDER_SPECS
    )


def combined_coverage_report() -> dict[str, Any]:
    """Observation coverage across every provider, from both registries.

    This is the report R2 asks for. Unobserved providers are named, not counted away,
    and each gap carries its reason so it can be acted on rather than merely noted.
    """
    catalogue = PROVIDER_CATALOGUE.list_ids()
    observed = observed_provider_ids()
    unobserved = [pid for pid in catalogue if pid not in observed]
    return {
        "total_catalogue": len(catalogue),
        "observed": len([pid for pid in catalogue if pid in observed]),
        "unobserved": len(unobserved),
        "unobserved_ids": unobserved,
        "unobserved_reasons": dict.fromkeys(unobserved, "no observation declared by PROVIDER_SPECS or RUNTIME_SPECS"),
        "by_source": {
            "provider_specs": sorted(
                s.provider_id for s in __import__(
                    "hevi.provider_policy.runtime", fromlist=["PROVIDER_SPECS"]
                ).PROVIDER_SPECS
            ),
            "runtime_specs": RUNTIME_SPECS.list_ids(),
        },
        "health_check_kinds": {
            kind.value: sorted(s.provider_id for s in RUNTIME_SPECS.by_kind(kind))
            for kind in HealthCheckKind
        },
        "full_coverage": not unobserved,
    }


__all__ = [
    "RUNTIME_SPECS",
    "HealthCheckKind",
    "ProviderRuntimeSpec",
    "RuntimeSpecRegistry",
    "combined_coverage_report",
    "coverage_report",
    "get_runtime_spec",
    "observed_provider_ids",
]
