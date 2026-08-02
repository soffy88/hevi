"""Truthful capability catalog for production-facing entry points.

The catalog is deliberately conservative: a capability is advertised as
available only when HEVI has a real execution adapter.  UI/API callers receive
one stable ``CAPABILITY_UNAVAILABLE`` shape instead of fabricated task IDs.
"""
# ruff: noqa: E501

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CapabilityDescriptor:
    id: str
    name: str
    routes: tuple[str, ...]
    available: bool
    message: str
    setup: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "routes": list(self.routes),
            "available": self.available,
            "status": "available" if self.available else "unavailable",
            "message": self.message,
            "setup": self.setup,
        }


_CATALOG: dict[str, CapabilityDescriptor] = {
    "longvideo": CapabilityDescriptor(
        "longvideo",
        "统一长视频生产",
        ("/api/pipeline/productions", "/api/tasks"),
        True,
        "通过统一 Task 生命周期执行。",
    ),
    "director_graph": CapabilityDescriptor(
        "director_graph",
        "导演台逐镜渲染",
        ("/api/director/render",),
        True,
        "用户锁定的画布分镜通过统一 Task 生命周期执行，并验证最终成片。",
    ),
    "explainer": CapabilityDescriptor(
        "explainer",
        "一句话解说",
        ("/api/explainer/run",),
        True,
        "通过统一 Task 生命周期执行。",
    ),
    "tongjian": CapabilityDescriptor(
        "tongjian",
        "通鉴出片",
        ("/api/tongjian/run",),
        True,
        "通过统一 Task 生命周期执行。",
    ),
    "shortdrama": CapabilityDescriptor(
        "shortdrama",
        "短剧",
        ("/api/shortdrama/runs",),
        True,
        "通过统一 Task 生命周期执行。",
    ),
    "voice_studio_tts": CapabilityDescriptor(
        "voice_studio_tts",
        "Voice Studio 合成",
        ("/api/voice-studio/tts/synthesize",),
        bool(os.getenv("VOICEBOX_BASE_URL", "").strip()),
        "Voicebox 已配置，可创建可查询、可下载的音频任务。"
        if os.getenv("VOICEBOX_BASE_URL", "").strip()
        else "Voicebox 服务地址未配置；不会创建无法执行的音频任务。",
        None
        if os.getenv("VOICEBOX_BASE_URL", "").strip()
        else "配置 VOICEBOX_BASE_URL 并启动 hevi-voicebox 服务后自动开放。",
    ),
    "voice_studio_rewrite": CapabilityDescriptor(
        "voice_studio_rewrite",
        "Voice Studio 人格改写",
        ("/api/voice-studio/personality/rewrite",),
        False,
        "人格改写尚未接入真实模型任务；不会把原文伪装成改写结果。",
        "接入可审计的文本改写任务适配器后自动开放。",
    ),
    "indextts": CapabilityDescriptor(
        "indextts",
        "情感语音",
        ("/api/pro/indextts/synthesize",),
        False,
        "情感语音尚未接入可交付的任务适配器。",
        "接入真实 TTS Provider 和音频产物下载后自动开放。",
    ),
    "stock_search": CapabilityDescriptor(
        "stock_search",
        "素材搜索",
        ("/api/pro/stock/search",),
        bool(os.getenv("PEXELS_API_KEY", "").strip()),
        "Pexels 已配置；搜索结果会持久化来源与许可证快照。"
        if os.getenv("PEXELS_API_KEY", "").strip()
        else "Pexels Provider 未配置；不会返回伪造素材。",
        None
        if os.getenv("PEXELS_API_KEY", "").strip()
        else "配置 PEXELS_API_KEY 后自动开放。",
    ),
    "livestream": CapabilityDescriptor(
        "livestream",
        "数字人直播",
        ("/api/pro/livestream/start",),
        bool(os.getenv("DUIX_SERVICE_URL", "").strip() and os.getenv("DUIX_LIVESTREAM_PATH", "").strip()),
        "Duix 直播端点已配置；启动前仍会执行健康检查并要求 Provider 返回真实播放地址。"
        if os.getenv("DUIX_SERVICE_URL", "").strip() and os.getenv("DUIX_LIVESTREAM_PATH", "").strip()
        else "数字人直播 Provider 未完整配置；不会创建伪直播会话。",
        None
        if os.getenv("DUIX_SERVICE_URL", "").strip() and os.getenv("DUIX_LIVESTREAM_PATH", "").strip()
        else "配置 DUIX_SERVICE_URL 与 DUIX_LIVESTREAM_PATH，并接入返回 stream_url 的 WebRTC/RTMP 适配器。",
    ),
    "production_tools": CapabilityDescriptor(
        "production_tools",
        "Production Tools V2",
        ("/api/production/v2",),
        True,
        "Seedance 文生视频、解说配方与数字人预览/成片均创建真实统一 Task；智能切片单独保持不可用。",
    ),
}


class CapabilityUnavailableError(RuntimeError):
    def __init__(self, descriptor: CapabilityDescriptor):
        self.descriptor = descriptor
        super().__init__(descriptor.message)

    def detail(self) -> dict[str, Any]:
        return {"code": "CAPABILITY_UNAVAILABLE", **self.descriptor.public()}


def capability_catalog() -> list[dict[str, Any]]:
    return [descriptor.public() for descriptor in _CATALOG.values()]


def require_capability(capability_id: str) -> CapabilityDescriptor:
    descriptor = _CATALOG[capability_id]
    if not descriptor.available:
        raise CapabilityUnavailableError(descriptor)
    return descriptor
