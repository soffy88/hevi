"""MoneyPrinterTurbo 集成层 - hevi 调用 MPT 服务的 Python 客户端

注意：MPT 以独立容器运行，hevi 通过此客户端调用 MPT 的 API / WebUI 能力。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx


@dataclass
class MPTConfig:
    api_base: str = "http://mpt-api:8080"
    webui_base: str = "http://mpt-webui:8501"
    timeout: float = 300.0  # MPT 生成视频可能需要几分钟


def _response_data(payload: Any) -> Any:
    """Accept both current ``{status,data}`` and legacy bare responses."""

    if isinstance(payload, dict) and "data" in payload and payload["data"] is not None:
        return payload["data"]
    return payload


class MPTClient:
    """hevi 侧调用 MPT 服务的客户端"""

    def __init__(self, config: MPTConfig | None = None):
        self.config = config or MPTConfig(
            api_base=os.getenv("MPT_API_BASE", "http://localhost:8080"),
            webui_base=os.getenv("MPT_WEBUI_BASE", "http://localhost:8501"),
        )
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> MPTClient:
        headers = {}
        api_key = os.getenv("MPT_API_KEY", "").strip()
        if api_key:
            headers["x-api-key"] = api_key
        self._client = httpx.AsyncClient(timeout=self.config.timeout, headers=headers)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: Any,
    ) -> None:
        if self._client:
            await self._client.aclose()

    async def generate_video(
        self,
        topic: str,
        *,
        video_count: int = 1,
        aspect: str = "9:16",
        voice: str = "zh-CN-XiaoxiaoNeural",
        bgm: bool = True,
        subtitle: bool = True,
        material_mode: str = "pexels",
    ) -> dict[str, Any]:
        """调用 MPT API 生成视频"""
        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        payload = {
            # Current MPT names this required field video_subject.  Keep the
            # legacy endpoint fallback below for older sidecar images.
            "video_subject": topic,
            "topic": topic,
            "video_count": video_count,
            "video_aspect": aspect,
            "voice_name": voice,
            "bgm_type": "random" if bgm else "",
            "subtitle_enabled": subtitle,
            "video_source": material_mode,
            "bgm": bgm,
            "subtitle": subtitle,
            "material_mode": material_mode,
        }
        # MPT 1.3 exposes the controller under ``/api/v1/videos``.  Keep the
        # legacy paths as a compatibility probe for older sidecar images, but
        # always try the current contract first.
        endpoints = ("/api/v1/videos", "/api/v1/video/videos", "/api/v1/video/generate")
        last_payload: Any = {}
        for endpoint in endpoints:
            try:
                response = await self._client.post(
                    f"{self.config.api_base}{endpoint}", json=payload
                )
                response.raise_for_status()
                last_payload = _response_data(response.json())
            except httpx.HTTPStatusError:
                if endpoint == endpoints[-1]:
                    raise
                continue
            if isinstance(last_payload, dict) and (
                last_payload.get("task_id") or last_payload.get("id")
            ):
                return cast(dict[str, Any], last_payload)
        return cast(dict[str, Any], last_payload)

    async def check_task_status(self, task_id: str) -> dict[str, Any]:
        """查询任务状态"""
        if not self._client:
            raise RuntimeError("Client not initialized.")

        endpoints = (
            f"{self.config.api_base}/api/v1/tasks/{task_id}",
            f"{self.config.api_base}/api/v1/video/tasks/{task_id}",
            f"{self.config.api_base}/api/v1/task/status/{task_id}",
        )
        last_payload: Any = {}
        for endpoint in endpoints:
            try:
                response = await self._client.get(endpoint)
                response.raise_for_status()
                last_payload = _response_data(response.json())
            except httpx.HTTPStatusError:
                if endpoint == endpoints[-1]:
                    raise
                continue
            if isinstance(last_payload, dict) and "state" in last_payload:
                return cast(dict[str, Any], last_payload)
        return cast(dict[str, Any], last_payload)

    async def download_artifact(self, uri: str, destination: str | Path) -> Path:
        """Download an MPT task file when Hevi and MPT use different volumes."""

        if not self._client:
            raise RuntimeError("Client not initialized.")
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        if uri.startswith(("http://", "https://")):
            urls: tuple[str, ...] = (uri,)
        else:
            relative = uri.lstrip("/")
            urls = (
                f"{self.config.api_base.rstrip('/')}/api/v1/download/{relative}",
                f"{self.config.api_base.rstrip('/')}/{relative}",
            )
        last_error: Exception | None = None
        for url in urls:
            try:
                response = await self._client.get(url)
                response.raise_for_status()
                target.write_bytes(response.content)
                break
            except Exception as exc:
                last_error = exc
        else:
            raise RuntimeError(f"MPT artifact download failed: {uri}") from last_error
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError(f"MPT artifact download was empty: {uri}")
        return target

    async def get_materials(
        self,
        query: str,
        *,
        source: str = "pexels",
        count: int = 10,
        min_duration: int = 5,
    ) -> list[dict[str, Any]]:
        """搜索素材"""
        if not self._client:
            raise RuntimeError("Client not initialized.")

        params: dict[str, str | int] = {
            "query": query,
            "source": source,
            "count": count,
            "min_duration": min_duration,
        }
        response = await self._client.get(
            f"{self.config.api_base}/api/v1/material/search", params=params
        )
        response.raise_for_status()
        return cast(list[dict[str, Any]], _response_data(response.json()))

    async def cross_post(
        self,
        video_path: str,
        title: str,
        platforms: list[str],
    ) -> dict[str, Any]:
        """一键发布"""
        if not self._client:
            raise RuntimeError("Client not initialized.")

        payload = {
            "video_path": video_path,
            "title": title,
            "platforms": platforms,
        }
        response = await self._client.post(
            f"{self.config.api_base}/api/v1/cross-post", json=payload
        )
        response.raise_for_status()
        return cast(dict[str, Any], _response_data(response.json()))

    async def analyze_reference_video(self, url: str) -> dict[str, Any]:
        """参考视频分析（若 MPT 支持）"""
        if not self._client:
            raise RuntimeError("Client not initialized.")

        response = await self._client.post(
            f"{self.config.api_base}/api/v1/reference/analyze", json={"url": url}
        )
        response.raise_for_status()
        return cast(dict[str, Any], _response_data(response.json()))


async def submit_mpt_job_from_hevi(
    production_id: str,
    revision_id: str,
    topic: str,
    **kwargs: Any,
) -> str:
    """
    从 hevi 工作流提交 MPT 生成任务
    返回 MPT task_id，hevi 可轮询状态
    """
    async with MPTClient() as client:
        result = await client.generate_video(topic, **kwargs)
        return str(result.get("task_id", ""))


__all__ = [
    "MPTClient",
    "MPTConfig",
    "submit_mpt_job_from_hevi",
]
