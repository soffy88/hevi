import httpx
import pytest

from hevi.digital_human.duix_service import DuixLiveService, DuixUnavailable


@pytest.mark.asyncio
async def test_live_start_requires_provider_stream_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DUIX_LIVESTREAM_PATH", "/live/sessions")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/health"
        else httpx.Response(200, json={"session_id": "provider-session"})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        service = DuixLiveService(base_url="http://duix.local", client=client)
        with pytest.raises(DuixUnavailable, match="stream_url"):
            await service.start(presenter_id="p1", avatar_id=None, scene=None, script="hello")


@pytest.mark.asyncio
async def test_live_start_returns_only_real_provider_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DUIX_LIVESTREAM_PATH", "/live/sessions")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"status": "ready"})
        if request.url.path == "/health"
        else httpx.Response(
            200, json={"session_id": "provider-session", "webrtc_url": "webrtc://provider/session"}
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        service = DuixLiveService(base_url="http://duix.local", client=client)
        result = await service.start(
            presenter_id="p1", avatar_id=None, scene="studio", script="hello"
        )
    assert result == {
        "session_id": "provider-session",
        "stream_url": "webrtc://provider/session",
        "provider": "duix",
        "status": "started",
    }
