import httpx
import pytest

from hevi.digital_human.livetalking_service import (
    LiveTalkingRtmpService,
    LiveTalkingUnavailable,
    LiveTalkingWebRTCService,
)

# ── WebRTC 按需会话 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webrtc_not_configured_raises() -> None:
    service = LiveTalkingWebRTCService(base_url="")
    with pytest.raises(LiveTalkingUnavailable, match="未配置"):
        await service.create_session(sdp="v=0...", sdp_type="offer")


@pytest.mark.asyncio
async def test_webrtc_create_session_relays_real_answer() -> None:
    transport = httpx.MockTransport(
        lambda request: (
            httpx.Response(200, json={"status": "ok"})
            if request.url.path == "/"
            else httpx.Response(
                200, json={"sdp": "v=0 answer...", "type": "answer", "sessionid": "42"}
            )
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        service = LiveTalkingWebRTCService(base_url="http://livetalking.local", client=client)
        result = await service.create_session(sdp="v=0 offer...", sdp_type="offer", avatar_id="a1")
    assert result == {
        "session_id": "42",
        "sdp": "v=0 answer...",
        "type": "answer",
        "provider": "livetalking",
        "status": "started",
    }


@pytest.mark.asyncio
async def test_webrtc_missing_answer_sdp_raises_not_fabricated() -> None:
    transport = httpx.MockTransport(
        lambda request: (
            httpx.Response(200, json={"status": "ok"})
            if request.url.path == "/"
            else httpx.Response(200, json={"sessionid": "42"})
        )  # 没有 sdp
    )
    async with httpx.AsyncClient(transport=transport) as client:
        service = LiveTalkingWebRTCService(base_url="http://livetalking.local", client=client)
        with pytest.raises(LiveTalkingUnavailable, match="sdp answer"):
            await service.create_session(sdp="v=0...", sdp_type="offer")


@pytest.mark.asyncio
async def test_webrtc_offer_http_error_raises_not_swallowed() -> None:
    transport = httpx.MockTransport(
        lambda request: (
            httpx.Response(200, json={"status": "ok"})
            if request.url.path == "/"
            else httpx.Response(500, text="internal error")
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        service = LiveTalkingWebRTCService(base_url="http://livetalking.local", client=client)
        with pytest.raises(LiveTalkingUnavailable, match="握手失败"):
            await service.create_session(sdp="v=0...", sdp_type="offer")


@pytest.mark.asyncio
async def test_webrtc_health_unreachable_raises() -> None:
    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(_boom)
    async with httpx.AsyncClient(transport=transport) as client:
        service = LiveTalkingWebRTCService(base_url="http://livetalking.local", client=client)
        with pytest.raises(LiveTalkingUnavailable, match="不可达"):
            await service.health()


# ── RTMP 固定频道 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rtmp_not_configured_raises() -> None:
    service = LiveTalkingRtmpService(playback_url="")
    with pytest.raises(LiveTalkingUnavailable, match="未配置"):
        await service.status()


@pytest.mark.asyncio
async def test_rtmp_configured_without_probe_reports_unknown_reachability(monkeypatch) -> None:
    monkeypatch.delenv("LIVETALKING_RTMP_PROBE_URL", raising=False)
    service = LiveTalkingRtmpService(playback_url="rtmp://cdn.example/live/stream1")
    result = await service.status()
    assert result["playback_url"] == "rtmp://cdn.example/live/stream1"
    assert result["reachable"] is None


@pytest.mark.asyncio
async def test_rtmp_configured_with_probe_reports_reachable(monkeypatch) -> None:
    monkeypatch.setenv("LIVETALKING_RTMP_PROBE_URL", "http://livetalking.local/metrics")
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True}))
    async with httpx.AsyncClient(transport=transport) as client:
        service = LiveTalkingRtmpService(
            playback_url="rtmp://cdn.example/live/stream1", client=client
        )
        result = await service.status()
    assert result["reachable"] is True
    assert result["http_status"] == 200


@pytest.mark.asyncio
async def test_rtmp_probe_failure_raises_not_fabricated(monkeypatch) -> None:
    monkeypatch.setenv("LIVETALKING_RTMP_PROBE_URL", "http://livetalking.local/metrics")

    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    transport = httpx.MockTransport(_boom)
    async with httpx.AsyncClient(transport=transport) as client:
        service = LiveTalkingRtmpService(
            playback_url="rtmp://cdn.example/live/stream1", client=client
        )
        with pytest.raises(LiveTalkingUnavailable, match="不可达"):
            await service.status()
