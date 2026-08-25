"""LiveTalking /pro/livetalking/* 路由测试。"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.api.routers import pro_studio
from hevi.auth.dependencies import get_current_user

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fake_auth():
    app.dependency_overrides[get_current_user] = lambda: {"id": "test-user"}
    yield
    app.dependency_overrides.clear()


def test_webrtc_capabilities_not_configured_reports_cannot_start(monkeypatch):
    monkeypatch.delenv("LIVETALKING_WEBRTC_URL", raising=False)
    r = client.get("/api/pro/livetalking/webrtc/capabilities")
    assert r.status_code == 200
    body = r.json()
    assert body["can_start"] is False
    assert body["provider"] == "livetalking"


def test_webrtc_offer_not_configured_returns_503(monkeypatch):
    monkeypatch.delenv("LIVETALKING_WEBRTC_URL", raising=False)
    r = client.post("/api/pro/livetalking/webrtc/offer", json={"sdp": "v=0...", "type": "offer"})
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "CAPABILITY_UNAVAILABLE"


def test_webrtc_offer_relays_real_answer(monkeypatch):
    monkeypatch.setenv("LIVETALKING_WEBRTC_URL", "http://livetalking.local")

    def _fake_service():
        transport = httpx.MockTransport(
            lambda request: (
                httpx.Response(200, json={"status": "ok"})
                if request.url.path == "/"
                else httpx.Response(
                    200, json={"sdp": "v=0 answer...", "type": "answer", "sessionid": "7"}
                )
            )
        )
        return pro_studio.LiveTalkingWebRTCService(
            base_url="http://livetalking.local", client=httpx.AsyncClient(transport=transport)
        )

    app.dependency_overrides[pro_studio.get_livetalking_webrtc_service] = _fake_service
    try:
        r = client.post(
            "/api/pro/livetalking/webrtc/offer", json={"sdp": "v=0 offer...", "type": "offer"}
        )
    finally:
        del app.dependency_overrides[pro_studio.get_livetalking_webrtc_service]
    assert r.status_code == 200
    assert r.json() == {
        "session_id": "7",
        "sdp": "v=0 answer...",
        "type": "answer",
        "provider": "livetalking",
        "status": "started",
    }


def test_rtmp_status_not_configured_returns_503(monkeypatch):
    monkeypatch.delenv("LIVETALKING_RTMP_PLAYBACK_URL", raising=False)
    r = client.get("/api/pro/livetalking/rtmp/status")
    assert r.status_code == 503
    assert r.json()["detail"]["capability_id"] == "livetalking_rtmp"


def test_rtmp_status_configured_reports_playback_url(monkeypatch):
    monkeypatch.setenv("LIVETALKING_RTMP_PLAYBACK_URL", "rtmp://cdn.example/live/s1")
    monkeypatch.delenv("LIVETALKING_RTMP_PROBE_URL", raising=False)
    r = client.get("/api/pro/livetalking/rtmp/status")
    assert r.status_code == 200
    body = r.json()
    assert body["playback_url"] == "rtmp://cdn.example/live/s1"
    assert body["reachable"] is None
