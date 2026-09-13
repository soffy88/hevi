import pytest

from hevi.audio.provider_selection import select_tts_provider
from hevi.audio.providers.openvoice import OpenVoiceProvider


def test_openvoice_is_optional_and_isolated() -> None:
    provider = OpenVoiceProvider(base_url="")
    assert not provider.configured
    assert provider.license_metadata["bundled"] is False
    assert provider.capabilities.voice_clone


@pytest.mark.asyncio
async def test_openvoice_readiness_blocks_without_service() -> None:
    result = await OpenVoiceProvider(base_url="").readiness()
    assert result["status"] == "BLOCKED_SERVICE"


@pytest.mark.asyncio
async def test_auto_selection_records_existing_fallback_for_unavailable_openvoice() -> None:
    provider, provenance = await select_tts_provider("auto", line="localization_dub", existing="edge_tts", openvoice=OpenVoiceProvider(base_url=""))
    assert provider == "edge_tts"
    assert provenance["provider_selection"] == "edge_tts"
    assert provenance["fallback_reason"] == "OPENVOICE_SERVICE_URL missing"
