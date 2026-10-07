"""HEVI P7.2 — The provider catalogue: the single source of provider facts.

What a provider *is* — where it runs, what kind of material it yields, whether
it can currently be used — is a fact. Before P7.2 that fact had no home, so
consumers guessed it from the provider's name:

    provider_id.startswith("local")      # locality
    "local" ⇒ unlicensed                 # licence

P7.1 removed the guessing from P7. This module supplies the facts it now reads.

Why a catalogue was unavoidable
-------------------------------
The two registries that already existed carry *limits and configuration*, not
identity:

* ``hevi.video.capability_guard.PROVIDER_LIMITS`` — 14 video generators, with
  modes, resolution, duration, fps.
* ``hevi.provider_policy.runtime.PROVIDER_SPECS`` — 8 runtime/infra providers
  (audio, llm) with health paths and env requirements.

Neither says where anything runs. And the names are useless as a substitute:
of the 14 generators, only **5** carry any locality hint in their name and
**9** carry none at all — ``manim``, ``veo3``, ``kling_v2``, ``hailuo``,
``happyhorse_1_1``, ``wan_2_7`` and the MaaS variants. A name-based rule would
leave two thirds of the fleet undecidable.

Import direction
-----------------
This module imports nothing from ``hevi``. It is a leaf, so
``hevi.provider_policy.policy`` may import it without a cycle.
``hevi.provider_policy.policy`` re-exports the enums, so the path P7.1 introduced
keeps working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ProviderLocality(StrEnum):
    """Where a provider runs. A declared fact, never read from a name.

    Added in P7.1, defined here in P7.2 alongside the catalogue that produces it.
    A consumer that needs locality reads it; it does not inspect
    ``provider_id``. ``acme.internal-image`` is LOCAL because the catalogue says
    so, not because of what it is called.
    """

    LOCAL = "LOCAL"
    REMOTE = "REMOTE"


class ProviderLicenseClass(StrEnum):
    """What kind of material a provider yields.

    Not derivable from locality: a local pipeline can fetch licensed stock, and a
    remote generator can be unlicensed. Declared per provider.
    """

    LICENSED = "LICENSED"
    GENERATED = "GENERATED"
    UNKNOWN = "UNKNOWN"


class ProviderCapabilityState(StrEnum):
    """Whether a provider can currently be used.

    ``NOT_ADOPTED`` previously existed only as a key in diagnostic output, so
    "we chose not to use this" and "we cannot use this" were indistinguishable to
    any consumer that did not parse a report.
    """

    AVAILABLE = "AVAILABLE"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    NOT_ADOPTED = "NOT_ADOPTED"


class ProviderKind(StrEnum):
    """What the provider does. Coarse, and not a locality signal."""

    VIDEO = "video"
    IMAGE = "image"
    AUDIO = "audio"
    LLM = "llm"
    INFRA = "infra"
    # P9.1.d: what a provider *does*, as distinct from what it emits.
    # GENERATOR produces content, RENDERER produces visual/animation output,
    # ENCODER transforms media. Coarse, and still not a locality signal.
    GENERATOR = "generator"
    RENDERER = "renderer"
    ENCODER = "encoder"


class RuntimeClass(StrEnum):
    """How a provider is executed. P9.1.d.

    Declared once, here, so the catalogue and the runtime specs cannot drift into
    two vocabularies for the same mechanism. ``hevi/providers/runtime_specs.py`` keeps
    its finer ``HealthCheckKind`` because it also describes how to *observe*; this is
    what a provider *is*.
    """

    LOCAL_PROCESS = "local_process"
    CLI = "cli"
    HTTP = "http"
    QUEUE = "queue"


@dataclass(frozen=True)
class ArtifactContract:
    """What a provider is expected to emit.

    A declaration of *shape*, never of validity. Nothing here proves an artifact is
    correct — that is P8.4's job, and a provider owning a contract must not also own
    the proof (audit R1).
    """

    media_types: tuple[str, ...] = ("VIDEO",)
    container: str = ""
    #: capabilities this provider must NOT claim, stated so widening is visible
    excluded_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.media_types:
            raise ValueError(
                f"ARTIFACT_CONTRACT_WITHOUT_MEDIA_TYPE:{self}; a provider that "
                "declares no output shape cannot be qualified against one"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "media_types": list(self.media_types),
            "container": self.container,
            "excluded_capabilities": list(self.excluded_capabilities),
        }


@dataclass(frozen=True)
class ProviderProfile:
    """One provider's declared facts.

    Deliberately holds no ``provider_id.startswith`` logic and performs no
    derivation. Everything here is stated.
    """

    provider_id: str
    kind: ProviderKind
    locality: ProviderLocality
    license_class: ProviderLicenseClass = ProviderLicenseClass.UNKNOWN
    capability_state: ProviderCapabilityState = ProviderCapabilityState.AVAILABLE
    capabilities: tuple[str, ...] = ()
    notes: str = ""
    #: P9.1.d. Defaults keep every existing profile valid without a rewrite.
    runtime_class: RuntimeClass = RuntimeClass.LOCAL_PROCESS
    artifact_contract: ArtifactContract = field(
        default_factory=lambda: ArtifactContract(media_types=("VIDEO",))
    )

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValueError("PROVIDER_PROFILE_WITHOUT_ID:provider_id required")
        if not isinstance(self.locality, ProviderLocality):
            raise ValueError(f"UNKNOWN_PROVIDER_LOCALITY:{self.locality!r}")
        if not isinstance(self.license_class, ProviderLicenseClass):
            raise ValueError(f"UNKNOWN_LICENSE_CLASS:{self.license_class!r}")
        if not isinstance(self.capability_state, ProviderCapabilityState):
            raise ValueError(f"UNKNOWN_CAPABILITY_STATE:{self.capability_state!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "kind": self.kind.value,
            "locality": self.locality.value,
            "license_class": self.license_class.value,
            "capability_state": self.capability_state.value,
            "capabilities": list(self.capabilities),
            "notes": self.notes,
        }


_LOCAL = ProviderLocality.LOCAL
_REMOTE = ProviderLocality.REMOTE
_GEN = ProviderLicenseClass.GENERATED
_ADOPTED = ProviderCapabilityState.AVAILABLE

#: The declared fleet. Every entry is a statement about what the provider *is*.
#:
#: Locality is asserted from what the provider does — a local diffusion runtime
#: runs on your hardware, a hosted endpoint does not. Licence class is
#: ``GENERATED`` for every video generator here because they synthesise frames
#: rather than license stock; ``LICENSED`` appears for the audio/infra entries
#: whose material is licensed or self-hosted respectively.
_SEED: tuple[ProviderProfile, ...] = (
    # ── local diffusion runtimes ──
    ProviderProfile("wan_local", ProviderKind.VIDEO, _LOCAL, _GEN, _ADOPTED,
                    ("t2v", "i2v"), "self-hosted diffusion runtime"),
    ProviderProfile("ltx2_local", ProviderKind.VIDEO, _LOCAL, _GEN, _ADOPTED,
                    ("t2v", "i2v"), "self-hosted LTX-2 runtime"),
    # ── node-process video renderer (P9.1.c) ──
    # Remotion runs as a node process driven as a subprocess. Declared LOCAL because
    # that is where it runs — asserted from the mechanism, never from the name.
    # Found by the P9.1.c R3 fix: `hyperframes` was named as a render runtime by
    # hevi/qualification/framework.py but had NO catalogue identity — a real renderer
    # invisible to provider policy, which is audit finding R2. Declared here so the
    # catalogue stops under-reporting the fleet. Declared only: it has NOT been
    # qualified, unlike manim and remotion.
    # ── encoders (P9.1.d) ──
    # ffmpeg is not a content generator. It is included because a real renderer exists
    # here and leaving it out is what produced audit finding R2 (renderer without
    # identity). Its capabilities are declared narrowly and negatively: transcode,
    # containerize, audio merge — and explicitly NOT text-to-video or image
    # generation, so widening it is a visible contract change.
    ProviderProfile(
        "ffmpeg", ProviderKind.ENCODER, _LOCAL,
        ProviderLicenseClass.LICENSED, _ADOPTED,
        ("video_transcode", "video_containerize", "audio_merge"),
        "media transformer; encodes and muxes, does not synthesise",
        runtime_class=RuntimeClass.CLI,
        artifact_contract=ArtifactContract(
            media_types=("VIDEO", "AUDIO"),
            excluded_capabilities=("text_to_video", "image_generation"),
        ),
    ),
    # html_gsap: a browser-driven HTML/GSAP renderer. Playwright + ffmpeg under the
    # hood; still a LOCAL_PROCESS renderer from the provider's point of view.
    ProviderProfile(
        "html_gsap", ProviderKind.RENDERER, _LOCAL, _GEN, _ADOPTED,
        ("t2v", "motion_graphics", "html_render"),
        "Playwright-driven HTML/GSAP renderer",
    ),
    ProviderProfile("hyperframes", ProviderKind.VIDEO, _LOCAL, _GEN, _ADOPTED,
                    ("t2v", "motion_graphics", "html_render"),
                    "in-process HTML renderer; declared, not yet qualified"),
    ProviderProfile("remotion", ProviderKind.VIDEO, _LOCAL, _GEN, _ADOPTED,
                    ("t2v", "motion_graphics", "explainer", "captions"),
                    "node process under hevi-remotion/"),
    ProviderProfile("h3_local", ProviderKind.VIDEO, _LOCAL, _GEN, _ADOPTED,
                    ("t2v",), "self-hosted H3 runtime"),
    ProviderProfile("manim", ProviderKind.VIDEO, _LOCAL, _GEN, _ADOPTED,
                    ("t2v",), "library render: no inference, generated frames"),
    # ── hosted endpoints ──
    ProviderProfile("wan_cloud", ProviderKind.VIDEO, _REMOTE, _GEN, _ADOPTED,
                    ("t2v", "i2v"), "hosted inference"),
    ProviderProfile("ltx2_cloud", ProviderKind.VIDEO, _REMOTE, _GEN, _ADOPTED,
                    ("t2v", "i2v"), "hosted inference"),
    ProviderProfile("veo3", ProviderKind.VIDEO, _REMOTE, _GEN, _ADOPTED,
                    ("t2v", "i2v"), "third-party model API"),
    ProviderProfile("kling_v2", ProviderKind.VIDEO, _REMOTE, _GEN, _ADOPTED,
                    ("t2v", "i2v"), "third-party model API"),
    ProviderProfile("hailuo", ProviderKind.VIDEO, _REMOTE, _GEN, _ADOPTED,
                    ("t2v", "i2v"), "third-party model API"),
    ProviderProfile("happyhorse_1_1", ProviderKind.VIDEO, _REMOTE, _GEN, _ADOPTED,
                    ("t2v", "i2v"), "third-party model API"),
    ProviderProfile("wan_2_7", ProviderKind.VIDEO, _REMOTE, _GEN, _ADOPTED,
                    ("t2v", "i2v"), "third-party model API"),
    ProviderProfile("happyhorse_1_1_maas", ProviderKind.VIDEO, _REMOTE, _GEN, _ADOPTED,
                    ("t2v", "i2v"), "MaaS endpoint"),
    ProviderProfile("happyhorse_1_1_maas_lock", ProviderKind.VIDEO, _REMOTE, _GEN,
                    _ADOPTED, ("t2v", "i2v"),
                    "locked MaaS variant: single-reference-image calling convention, "
                    "the mainline create_episode/Series/orchestrate_longvideo path "
                    "(registry.py, longvideo_orchestrator, director/shortdrama "
                    "routers). It was previously NOT_ADOPTED with the note 'not for "
                    "general routing', which contradicted both that code and the "
                    "admission policy treating NOT_ADOPTED as informational."),
    ProviderProfile("wan_2_7_maas", ProviderKind.VIDEO, _REMOTE, _GEN, _ADOPTED,
                    ("t2v", "i2v"), "MaaS endpoint"),
    # ── runtime / infra providers (PROVIDER_SPECS fleet) ──
    ProviderProfile("voicebox", ProviderKind.AUDIO, _LOCAL,
                    ProviderLicenseClass.LICENSED, _ADOPTED, ("tts",),
                    "self-hosted TTS engine"),
    ProviderProfile("longcat", ProviderKind.LLM, _REMOTE,
                    ProviderLicenseClass.LICENSED, _ADOPTED, ("llm",),
                    "OpenAI-compatible agent endpoint"),
)


class ProviderCatalogue:
    """The sole fact source for provider identity.

    Lookup only. No scoring, no ranking, no derivation — those belong to
    ``hevi.provider_policy``. A provider absent from the catalogue has *no*
    declared facts, and consumers report ``UNRESOLVED`` rather than inferring one.
    """

    def __init__(self, profiles: tuple[ProviderProfile, ...] = ()) -> None:
        self._profiles: dict[str, ProviderProfile] = {}
        for profile in profiles:
            self.register(profile)

    def register(self, profile: ProviderProfile) -> ProviderProfile:
        if profile.provider_id in self._profiles:
            raise ValueError(f"PROVIDER_PROFILE_DUPLICATE:{profile.provider_id}")
        self._profiles[profile.provider_id] = profile
        return profile

    def get(self, provider_id: str) -> ProviderProfile | None:
        return self._profiles.get(provider_id)

    def resolve(self, provider_id: str) -> ProviderProfile:
        profile = self.get(provider_id)
        if profile is None:
            raise KeyError(f"PROVIDER_NOT_IN_CATALOGUE:{provider_id}")
        return profile

    def has(self, provider_id: str) -> bool:
        return provider_id in self._profiles

    def list_ids(self) -> list[str]:
        return sorted(self._profiles)

    def by_locality(self, locality: ProviderLocality) -> tuple[ProviderProfile, ...]:
        return tuple(p for p in self._profiles.values() if p.locality is locality)

    def by_capability_state(
        self, state: ProviderCapabilityState
    ) -> tuple[ProviderProfile, ...]:
        return tuple(p for p in self._profiles.values() if p.capability_state is state)

    def facts_for(self, provider_id: str) -> dict[str, Any]:
        """Declared facts, or empty dicts when the provider is unknown.

        The empty case is meaningful: it is what makes ``UNRESOLVED`` reachable,
        and therefore what makes the absence of a fact observable instead of
        silently guessed.
        """
        profile = self.get(provider_id)
        if profile is None:
            return {"locality": {}, "license_class": {}, "capability_states": {}}
        return {
            "locality": {profile.provider_id: profile.locality},
            "license_class": {profile.provider_id: profile.license_class},
            "capability_states": {profile.provider_id: profile.capability_state},
        }

    def local_ids(self) -> tuple[str, ...]:
        return tuple(sorted(p.provider_id for p in self.by_locality(_LOCAL)))

    def remote_ids(self) -> tuple[str, ...]:
        return tuple(sorted(p.provider_id for p in self.by_locality(_REMOTE)))

    def stats(self) -> dict[str, Any]:
        return {
            "providers": len(self._profiles),
            "local": len(self.local_ids()),
            "remote": len(self.remote_ids()),
            "not_adopted": len(
                self.by_capability_state(ProviderCapabilityState.NOT_ADOPTED)
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {k: self._profiles[k].to_dict() for k in self.list_ids()}


#: The single provider fact source.
PROVIDER_CATALOGUE = ProviderCatalogue(_SEED)


def get_profile(provider_id: str) -> ProviderProfile | None:
    """The catalogue's lookup for a provider, or ``None``."""
    return PROVIDER_CATALOGUE.get(provider_id)


def facts_for(provider_id: str) -> dict[str, Any]:
    """Declared facts for a provider. Empty when unknown — never inferred."""
    return PROVIDER_CATALOGUE.facts_for(provider_id)


__all__ = [
    "PROVIDER_CATALOGUE",
    "ProviderCapabilityState",
    "ProviderCatalogue",
    "ProviderKind",
    "ProviderLicenseClass",
    "ProviderLocality",
    "ProviderProfile",
    "facts_for",
    "get_profile",
]
