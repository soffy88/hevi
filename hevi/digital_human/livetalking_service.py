"""LiveTalking(github.com/lipku/LiveTalking) 直播数字人边界。

对标 duix_service.py 的纪律: HEVI never invents a live session。LiveTalking
提供两种真实契约, 语义不同, 不能塞进同一个类:

- LiveTalkingWebRTCService: 按需会话。每次调用做一次 SDP offer/answer 握手
  (POST /offer), 拿到 sessionid + SDP answer。没有共享 stream_url——每个
  观看者要自己单独握手, 前端要跑真实 RTCPeerConnection, 不是 <video src=...>。
  对应"AI数字人客服/在线教育"这类按会话交互场景。
- LiveTalkingRtmpService: 固定频道。LiveTalking 进程用 --transport rtmp
  启动时才存在, 是运维管的常驻服务, 不是按调用开的会话——LiveTalking 本身
  没有提供"远程 start/stop 一路 RTMP 频道"的 REST 接口, 这里只做"配置了没
  有、能不能连上"的健康检查。对应"24小时无人直播"场景。
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class LiveTalkingUnavailable(RuntimeError):
    pass


class LiveTalkingWebRTCService:
    """按需 WebRTC 会话: 每次调用代理一次 SDP offer/answer 握手。"""

    def __init__(
        self, *, base_url: str | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        self._base_url = (
            base_url if base_url is not None else os.getenv("LIVETALKING_WEBRTC_URL", "")
        ).rstrip("/")
        self._offer_path = os.getenv("LIVETALKING_OFFER_PATH", "/offer")
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self._base_url)

    async def health(self) -> dict[str, Any]:
        """LiveTalking 没有专门的健康检查路由, 用能否连通根路径判断可达性。"""
        if not self._base_url:
            raise LiveTalkingUnavailable("LIVETALKING_WEBRTC_URL 未配置")
        try:
            response = await self._request("GET", "/")
        except httpx.HTTPError as exc:
            raise LiveTalkingUnavailable(f"LiveTalking 不可达：{exc}") from exc
        if response.status_code >= 500:
            raise LiveTalkingUnavailable(f"LiveTalking 健康检查返回 HTTP {response.status_code}")
        return {"status": "ok", "http_status": response.status_code}

    async def create_session(
        self, *, sdp: str, sdp_type: str = "offer", avatar_id: str | None = None
    ) -> dict[str, Any]:
        """代理一次 offer/answer 握手, 返回真实 sessionid + SDP answer(不伪造)。"""
        if not self.configured:
            raise LiveTalkingUnavailable("未配置 LIVETALKING_WEBRTC_URL，无法建立真实会话")
        await self.health()
        payload: dict[str, Any] = {"sdp": sdp, "type": sdp_type}
        if avatar_id:
            payload["avatar_id"] = avatar_id
        response = await self._request("POST", self._offer_path, json=payload)
        if response.status_code >= 400:
            raise LiveTalkingUnavailable(f"LiveTalking offer 握手失败：HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as exc:
            raise LiveTalkingUnavailable("LiveTalking offer 返回无效 JSON") from exc
        if not isinstance(body, dict):
            raise LiveTalkingUnavailable("LiveTalking offer 返回无效数据")
        answer_sdp = body.get("sdp")
        session_id = body.get("sessionid") or body.get("session_id")
        if not answer_sdp or session_id is None:
            raise LiveTalkingUnavailable("LiveTalking 未返回真实 sdp answer 或 sessionid")
        return {
            "session_id": str(session_id),
            "sdp": str(answer_sdp),
            "type": body.get("type", "answer"),
            "provider": "livetalking",
            "status": "started",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self._base_url}{path if path.startswith('/') else '/' + path}"
        if self._client is not None:
            return await self._client.request(method, url, timeout=15.0, **kwargs)
        async with httpx.AsyncClient() as client:
            return await client.request(method, url, timeout=15.0, **kwargs)


class LiveTalkingRtmpService:
    """固定 RTMP 频道: 运维管的常驻进程, 这里只做配置/可达性核实, 不假装能远程开关。"""

    def __init__(
        self, *, playback_url: str | None = None, client: httpx.AsyncClient | None = None
    ) -> None:
        self._playback_url = (
            playback_url
            if playback_url is not None
            else os.getenv("LIVETALKING_RTMP_PLAYBACK_URL", "")
        ).strip()
        self._probe_url = os.getenv("LIVETALKING_RTMP_PROBE_URL", "").strip()
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self._playback_url)

    async def status(self) -> dict[str, Any]:
        """只报告"配置了没有、能不能连上探测端点"——不验证 RTMP 流本身正在推流
        (那需要 RTMP 客户端, 超出这个边界类的职责)。没配置 probe 就只报告配置状态。
        """
        if not self._playback_url:
            raise LiveTalkingUnavailable(
                "未配置 LIVETALKING_RTMP_PLAYBACK_URL，RTMP 频道未就绪(需运维先用 --transport rtmp 启动 LiveTalking 进程)"
            )
        result: dict[str, Any] = {"provider": "livetalking", "playback_url": self._playback_url}
        if not self._probe_url:
            result["reachable"] = None
            result["message"] = "已配置播放地址，未配置探测端点，无法验证进程是否存活"
            return result
        try:
            response = await self._request("GET", self._probe_url)
        except httpx.HTTPError as exc:
            raise LiveTalkingUnavailable(f"LiveTalking RTMP 探测端点不可达：{exc}") from exc
        result["reachable"] = response.status_code < 400
        result["http_status"] = response.status_code
        return result

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._client is not None:
            return await self._client.request(method, url, timeout=15.0, **kwargs)
        async with httpx.AsyncClient() as client:
            return await client.request(method, url, timeout=15.0, **kwargs)
