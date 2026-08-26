"""MoneyPrinterTurbo 集成层 - hevi 调用 MPT 服务的 Python 客户端

注意：MPT 以独立容器运行，hevi 通过此客户端调用 MPT 的 API / WebUI 能力。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

import httpx


@dataclass
class MPTConfig:
    api_base: str = "http://mpt-api:8080"
    webui_base: str = "http://mpt-webui:8501"
    timeout: float = 300.0  # MPT 生成视频可能需要几分钟


class MPTClient:
    """hevi 侧调用 MPT 服务的客户端"""

    def __init__(self, config: Optional[MPTConfig] = None):
        self.config = config or MPTConfig(
            api_base=os.getenv("MPT_API_BASE", "http://localhost:8080"),
            webui_base=os.getenv("MPT_WEBUI_BASE", "http://localhost:8501"),
        )
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self.config.timeout)
        return self

    async def __aexit__(self, *args):
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
            "topic": topic,
            "video_count": video_count,
            "video_aspect": aspect,
            "voice_name": voice,
            "bgm": bgm,
            "subtitle": subtitle,
            "material_mode": material_mode,
        }

        response = await self._client.post(f"{self.config.api_base}/api/v1/video/generate", json=payload)
        response.raise_for_status()
        return response.json()

    async def check_task_status(self, task_id: str) -> dict[str, Any]:
        """查询任务状态"""
        if not self._client:
            raise RuntimeError("Client not initialized.")

        response = await self._client.get(f"{self.config.api_base}/api/v1/task/status/{task_id}")
        response.raise_for_status()
        return response.json()

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

        params = {
            "query": query,
            "source": source,
            "count": count,
            "min_duration": min_duration,
        }
        response = await self._client.get(f"{self.config.api_base}/api/v1/material/search", params=params)
        response.raise_for_status()
        return response.json()

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
        response = await self._client.post(f"{self.config.api_base}/api/v1/cross-post", json=payload)
        response.raise_for_status()
        return response.json()

    async def analyze_reference_video(self, url: str) -> dict[str, Any]:
        """参考视频分析（若 MPT 支持）"""
        if not self._client:
            raise RuntimeError("Client not initialized.")

        response = await self._client.post(
            f"{self.config.api_base}/api/v1/reference/analyze",
            json={"url": url}
        )
        response.raise_for_status()
        return response.json()


async def submit_mpt_job_from_hevi(
    production_id: str,
    revision_id: str,
    topic: str,
    **kwargs,
) -> str:
    """
    从 hevi 工作流提交 MPT 生成任务
    返回 MPT task_id，hevi 可轮询状态
    """
    async with MPTClient() as client:
        result = await client.generate_video(topic, **kwargs)
        return result.get("task_id", "")


__all__ = [
    "MPTConfig",
    "MPTClient",
    "submit_mpt_job_from_hevi",
]
