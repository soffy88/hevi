from dataclasses import dataclass

from obase.provider_registry import ProviderRegistry

__all__ = ["PROVIDER_LIMITS", "CapabilityError", "ProviderLimits", "validate_request"]


class CapabilityError(ValueError):
    """Raised when a request exceeds a provider's declared capability."""


@dataclass(frozen=True)
class ProviderLimits:
    """A read-only projection of one ``ProviderProfile``'s capability facts.

    P0-4.2.2 moved the authoritative data into ``hevi.providers.facts``, which is
    also where identity, locality, licence and adoption state live. This type exists
    so the many call sites that read ``limits.modes`` or ``limits.max_duration_s`` keep
    working; it is derived, never declared.

    Do not add fields here and do not extend ``PROVIDER_LIMITS``. A second writable
    capability table is what let the catalogue and the limits disagree for 9 of 14
    shared providers; see ``docs/architecture/provider_authority.md``. Add to
    ``ProviderProfile`` and this projection follows automatically.
    """

    modes: frozenset[str]
    max_resolution: tuple[int, int]  # (width, height)
    max_duration_s: float
    fps_options: frozenset[int]
    native_audio: bool = False
    lip_sync: bool = False
    last_verified: str = ""

    def supports(self, capability: str) -> bool:
        """Whether this provider offers ``capability``.

        A capability has two shapes in this schema and callers used to have to know
        which: generation modes live in ``modes`` (``t2v``, ``i2v``, ``code_scene``),
        while feature flags are booleans (``native_audio``, ``lip_sync``). The
        admission policy used to do ``getattr(limits, capability, False)``, which only
        ever worked for the second shape -- so every ``t2v``/``i2v`` requirement
        failed against every provider and was reported as ``capability_missing``: a
        gate that could not open, looking like a deliberate refusal.
        """
        if capability in self.modes:
            return True
        return getattr(self, capability, None) is True


def _project_limits() -> dict[str, ProviderLimits]:
    """Derive the legacy limits view from the canonical catalogue.

    Only providers with a declared ceiling appear. A provider the catalogue leaves
    undeclared is *absent* rather than present-with-zero-limits, because ``validate_request``
    distinguishes "unknown provider" from "provider cannot do this", and inventing a
    zero ceiling would collapse those two different refusals into one.
    """
    from hevi.providers.facts import PROVIDER_CATALOGUE

    projected: dict[str, ProviderLimits] = {}
    for provider_id in PROVIDER_CATALOGUE.list_ids():
        profile = PROVIDER_CATALOGUE.resolve(provider_id)
        if profile.max_resolution is None or profile.max_duration_s is None:
            continue
        projected[provider_id] = ProviderLimits(
            modes=frozenset(profile.capabilities),
            max_resolution=profile.max_resolution,
            max_duration_s=profile.max_duration_s,
            fps_options=profile.fps_options or frozenset(),
            native_audio=profile.native_audio,
            lip_sync=profile.lip_sync,
            last_verified=profile.last_verified,
        )
    return projected


#: Derived from ``PROVIDER_CATALOGUE``. Read-only by convention: nothing writes here,
#: and adding to it is no longer possible without editing the catalogue.
PROVIDER_LIMITS: dict[str, ProviderLimits] = _project_limits()


async def validate_request(
    *,
    provider: str,
    mode: str,
    resolution: tuple[int, int],
    duration_s: float,
    fps: int,
) -> None:
    """Validate a video-generation request against provider capability limits.

    Checks obase-registered capability tags first; falls back to PROVIDER_LIMITS.
    Raises CapabilityError on any violation so invalid requests are caught before
    consuming an API call.
    """
    if provider not in PROVIDER_LIMITS:
        raise CapabilityError(f"Unknown provider: {provider!r}")

    limits = PROVIDER_LIMITS[provider]

    # Use obase-registered tags for mode check when available.
    # v0.15.8: capabilities() is an instance method, returns dict {modes: [...]} or {}.
    cap_meta = ProviderRegistry.get().capabilities(provider)
    registered_modes = cap_meta.get("modes", []) if cap_meta else []
    if registered_modes:
        if mode not in registered_modes:
            raise CapabilityError(
                f"Provider {provider!r} registered capabilities {registered_modes!r} "
                f"do not include mode {mode!r}"
            )
    elif mode not in limits.modes:
        raise CapabilityError(
            f"Provider {provider!r} does not support mode {mode!r} (supported: {set(limits.modes)})"
        )

    # 朝向无关的分辨率比较: 把请求与上限各自按长短边排序后逐边比较,
    # 这样 1280×720(横) 不会被 1080×1920(竖) 的上限误拒。
    req_long, req_short = sorted(resolution, reverse=True)
    max_long, max_short = sorted(limits.max_resolution, reverse=True)
    if req_long > max_long or req_short > max_short:
        raise CapabilityError(
            f"Resolution {resolution} exceeds {provider!r} max {limits.max_resolution}"
        )

    if duration_s > limits.max_duration_s:
        raise CapabilityError(
            f"Duration {duration_s}s exceeds {provider!r} max {limits.max_duration_s}s"
        )

    if fps not in limits.fps_options:
        raise CapabilityError(
            f"fps={fps} not in {provider!r} fps_options {set(limits.fps_options)}"
        )
