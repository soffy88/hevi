"""Explicit Duix live-provider boundary.

HEVI never invents a live session.  A successful call must come from a
configured Duix WebRTC/RTMP adapter and include a playable stream URL.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class DuixUnavailable(RuntimeError):
    pass


class DuixLiveService:
    def __init__(self, *, base_url: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = (base_url if base_url is not None else os.getenv("DUIX_SERVICE_URL", "")).rstrip("/")
        self._health_path = os.getenv("DUIX_HEALTH_PATH", "/health")
        self._live_path = os.getenv("DUIX_LIVESTREAM_PATH", "").strip()
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._live_path)

    async def health(self) -> dict[str, Any]:
        if not self._base_url:
            raise DuixUnavailable("DUIX_SERVICE_URL 未配置")
        try:
            response = await self._request("GET", self._health_path)
        except httpx.HTTPError as exc:
            raise DuixUnavailable(f"Duix 健康检查失败：{exc}") from exc
        if response.status_code >= 400:
            raise DuixUnavailable(f"Duix 健康检查返回 HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError:
            payload = {"status": "ok"}
        if isinstance(payload, dict) and str(payload.get("status", "ok")).lower() not in {"ok", "ready", "healthy"}:
            raise DuixUnavailable(f"Duix 未就绪：{payload.get('status')}")
        return payload if isinstance(payload, dict) else {"status": "ok"}

    async def start(self, *, presenter_id: str | None, avatar_id: str | None, scene: str | None, script: str) -> dict[str, Any]:
        if not self.configured:
            raise DuixUnavailable("未配置 DUIX_LIVESTREAM_PATH，无法建立真实直播会话")
        await self.health()
        response = await self._request(
            "POST",
            self._live_path,
            json={"presenter_id": presenter_id, "avatar_id": avatar_id, "scene": scene, "script": script},
        )
        if response.status_code >= 400:
            raise DuixUnavailable(f"Duix 建立直播失败：HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DuixUnavailable("Duix 建立直播返回无效 JSON") from exc
        if not isinstance(payload, dict):
            raise DuixUnavailable("Duix 建立直播返回无效数据")
        session_id = payload.get("session_id")
        stream_url = payload.get("stream_url") or payload.get("webrtc_url") or payload.get("rtmp_url")
        if not session_id or not stream_url:
            raise DuixUnavailable("Duix 未返回真实 session_id 或可播放 stream_url")
        return {"session_id": str(session_id), "stream_url": str(stream_url), "provider": "duix", "status": "started"}

    async def stop(self, session_id: str) -> dict[str, Any]:
        if not self.configured:
            raise DuixUnavailable("Duix 直播 Provider 未配置")
        response = await self._request("DELETE", f"{self._live_path.rstrip('/')}/{session_id}")
        if response.status_code >= 400:
            raise DuixUnavailable(f"Duix 停止直播失败：HTTP {response.status_code}")
        return {"session_id": session_id, "status": "stopped", "provider": "duix"}

    async def status(self, session_id: str) -> dict[str, Any]:
        if not self.configured:
            raise DuixUnavailable("Duix 直播 Provider 未配置")
        response = await self._request("GET", f"{self._live_path.rstrip('/')}/{session_id}")
        if response.status_code >= 400:
            raise DuixUnavailable(f"Duix 查询直播失败：HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("session_id"):
            raise DuixUnavailable("Duix 未返回真实直播状态")
        return {**payload, "provider": "duix"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = f"{self._base_url}{path if path.startswith('/') else '/' + path}"
        if self._client is not None:
            return await self._client.request(method, url, timeout=15.0, **kwargs)
        async with httpx.AsyncClient() as client:
            return await client.request(method, url, timeout=15.0, **kwargs)
