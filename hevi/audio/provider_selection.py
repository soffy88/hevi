"""Optional TTS provider selection with explicit provenance."""

from __future__ import annotations

from typing import Any

from hevi.audio.providers.openvoice import OpenVoiceProvider

OPENVOICE_LINES = frozenset({"localization_dub", "avatar_spokesperson", "talking_head"})


async def select_tts_provider(
    requested: str,
    *,
    line: str | None = None,
    existing: str = "existing",
    openvoice: OpenVoiceProvider | None = None,
) -> tuple[str, dict[str, Any]]:
    """Resolve existing/openvoice/auto without silent provider changes."""
    requested = requested.strip().lower() or "existing"
    if requested == "existing":
        return existing, {"requested_provider": requested, "provider_selection": existing}
    if requested == "openvoice":
        return "openvoice", {"requested_provider": requested, "provider_selection": "openvoice"}
    if requested != "auto":
        raise ValueError(f"unsupported TTS provider selection: {requested}")
    if line not in OPENVOICE_LINES:
        return existing, {"requested_provider": requested, "provider_selection": existing, "fallback_reason": "line_not_openvoice_enabled"}
    provider = openvoice or OpenVoiceProvider()
    readiness = await provider.readiness()
    if readiness.get("status") == "READY":
        return "openvoice", {"requested_provider": requested, "provider_selection": "openvoice", "readiness": readiness}
    return existing, {"requested_provider": requested, "provider_selection": existing, "fallback_reason": readiness.get("blocker", readiness.get("status", "unavailable")), "openvoice_readiness": readiness}
