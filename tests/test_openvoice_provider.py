import pytest

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
