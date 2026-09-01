"""Truthful capability catalog for production-facing entry points.

The catalog is deliberately conservative: a capability is advertised as
available only when HEVI has a real execution adapter.  UI/API callers receive
one stable ``CAPABILITY_UNAVAILABLE`` shape instead of fabricated task IDs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class CapabilityDescriptor:
    id: str
    name: str
    routes: tuple[str, ...]
    available: bool
    message: str
    setup: str | None = None
    execution_ready: bool | None = None
    quality_gate_ready: bool | None = None
    production_ready: bool | None = None

    def public(self) -> dict[str, Any]:
        execution_ready = self.available if self.execution_ready is None else self.execution_ready
        quality_gate_ready = (
            self.available if self.quality_gate_ready is None else self.quality_gate_ready
        )
        production_ready = (
            self.available and execution_ready and quality_gate_ready
            if self.production_ready is None
            else self.production_ready
        )
        if not self.available:
            readiness = "unavailable"
        elif not execution_ready:
            readiness = "planning_only"
        elif not quality_gate_ready:
            readiness = "execution_only"
        elif self.setup:
            readiness = "conditional"
        else:
            readiness = "ready"
        return {
            "id": self.id,
            "name": self.name,
            "routes": list(self.routes),
            "available": self.available,
            "interface_available": self.available,
            "execution_ready": execution_ready,
            "quality_gate_ready": quality_gate_ready,
            "production_ready": production_ready,
            "readiness": readiness,
            # ``available`` is retained as the interface-compatibility field;
            # status now reflects whether the route can actually deliver.
            "interface_status": "available" if self.available else "unavailable",
            "status": readiness,
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
    "lot": CapabilityDescriptor(
        "lot",
        "制片厂排产",
        ("/api/studio/slates", "/api/studio/lines", "/api/studio/timelines", "/api/studio/tools"),
        True,
        "100+ 工具 + 13 条配方签发交接单,日更/Veya 调成品,HyperFrames 第二运行时,时间线改镜后 nle.recut。",
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
    "voice_platform": CapabilityDescriptor(
        "voice_platform",
        "统一本地语音平台",
        (
            "/api/voice-studio/catalog",
            "/api/voice-studio/profiles",
            "/api/voice-studio/batch/plan",
            "/api/voice-studio/platform/models",
            "/api/voice-studio/platform/voices",
            "/v1/audio/speech",
            "/v1/audio/speech/stream",
            "/v1/audio/transcriptions",
            "/api/voice-studio/diagnostics",
        ),
        True,
        "统一返回 TTS/ASR/声线/工作流目录；每个引擎单独报告真实安装状态，不加载模型。",
        "在语音工作台选择已 available 的引擎；sidecar 引擎需先启动对应服务。",
        execution_ready=True,
        quality_gate_ready=False,
        production_ready=False,
    ),
    "voice_streaming_asr": CapabilityDescriptor(
        "voice_streaming_asr",
        "流式语音识别",
        ("/v1/audio/transcriptions/stream",),
        bool(os.getenv("VOICE_ASR_STREAM_WS_URL", "").strip()),
        "ASR streaming sidecar 已配置，可转发实时音频与 partial/final 结果。"
        if os.getenv("VOICE_ASR_STREAM_WS_URL", "").strip()
        else "流式 ASR sidecar 未配置；批量本地转写仍可按引擎状态使用。",
        None
        if os.getenv("VOICE_ASR_STREAM_WS_URL", "").strip()
        else "配置 VOICE_ASR_STREAM_WS_URL 并启动兼容 WebSocket ASR 服务。",
    ),
    "voice_dubbing": CapabilityDescriptor(
        "voice_dubbing",
        "多语种配音/译制",
        ("/api/voice-studio/platform/dubbing/plan",),
        True,
        "提供抽音频、转写、说话人、翻译、合成、混音和封装的可审查工作流计划。",
        "真实执行依赖可用 ASR/TTS；pyannote 未就绪时会明确降级为启发式 speaker 标签。",
        execution_ready=False,
        quality_gate_ready=False,
        production_ready=False,
    ),
    "voice_audiobook": CapabilityDescriptor(
        "voice_audiobook",
        "章节有声书",
        ("/api/voice-studio/platform/audiobook/plan",),
        True,
        "支持 EPUB/PDF/TXT/Markdown 章节化、声线映射、批量合成和 M4B 封装计划。",
        "封装前需要真实 TTS 音频产物；接口不会伪造 M4B 文件。",
        execution_ready=False,
        quality_gate_ready=False,
        production_ready=False,
    ),
    "voice_watermark": CapabilityDescriptor(
        "voice_watermark",
        "音频水印",
        ("/api/voice-studio/platform/watermark/plan",),
        True,
        "AudioSeal embed/detect 工作流已纳入 3O 计划边界。",
        "未安装 AudioSeal 时只返回 blocked/plan，不声称水印已写入。",
        execution_ready=False,
        quality_gate_ready=False,
        production_ready=False,
    ),
    "streaming_v2v": CapabilityDescriptor(
        "streaming_v2v",
        "JoyAI 因果实时 V2V",
        (
            "/api/stream-edit/capabilities",
            "/api/stream-edit/sessions",
            "/api/stream-edit/sessions/{session_id}/stream",
        ),
        bool(os.getenv("JOYAI_STREAM_WS_URL", "").strip() or os.getenv("JOYAI_BASE_URL", "").strip()),
        "JoyAI-compatible WebSocket Provider 已配置，可进行 live/upload 因果帧编辑。"
        if os.getenv("JOYAI_STREAM_WS_URL", "").strip() or os.getenv("JOYAI_BASE_URL", "").strip()
        else "JoyAI streaming Provider 未配置；可创建 blocked session 供审计，不会生成伪造帧。",
        None
        if os.getenv("JOYAI_STREAM_WS_URL", "").strip() or os.getenv("JOYAI_BASE_URL", "").strip()
        else "配置 JOYAI_STREAM_WS_URL，或配置 JOYAI_BASE_URL + JOYAI_STREAM_WS_PATH。",
        execution_ready=bool(os.getenv("JOYAI_STREAM_WS_URL", "").strip() or os.getenv("JOYAI_BASE_URL", "").strip()),
        quality_gate_ready=False,
        production_ready=False,
    ),
    "voice_workspace": CapabilityDescriptor(
        "voice_workspace",
        "Voice-Pro 配音工作台",
        ("/api/voice-studio/catalog", "/api/voice-studio/tts/synthesize"),
        True,
        "Voice-Pro 的字幕时钟、翻译、混音内核已接入；当前工作台提供目录、批量计划和任务入口。",
        "需要具体 TTS/ASR 引擎 available 才能执行对应任务。",
        execution_ready=True,
        quality_gate_ready=False,
        production_ready=False,
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
        execution_ready=True,
        quality_gate_ready=False,
        production_ready=False,
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
        execution_ready=bool(os.getenv("DUIX_SERVICE_URL", "").strip() and os.getenv("DUIX_LIVESTREAM_PATH", "").strip()),
        quality_gate_ready=False,
        production_ready=False,
    ),
    "production_tools": CapabilityDescriptor(
        "production_tools",
        "Production Tools V2",
        ("/api/production/v2",),
        True,
        "Seedance、解说配方、数字人和本地智能拆条均创建真实统一 Task；拆条产物回写 ArtifactManifest。",
    ),
    "clip_video": CapabilityDescriptor(
        "clip_video",
        "本地智能拆条",
        ("/api/production/v2/clip-video",),
        True,
        "字幕/Whisper 转写、病毒点候选、FFmpeg 竖屏重构和批量 ArtifactManifest 已接入。",
        "需要本地视频、FFmpeg，以及字幕段或 faster-whisper；未提供转写时不会伪造完成状态。",
    ),
    "ai_shorts": CapabilityDescriptor(
        "ai_shorts",
        "OpenShorts 从零短视频",
        ("/api/openshorts/ai-short/run",),
        True,
        "描述/网页快照 → 脚本 → HEVI 语音 → 注入或本地 talking-head → FFmpeg 合成，并返回 ArtifactManifest。",
        "要完成出片必须提供 talking_head_path 或 talking_head/video provider；缺少真实视频时返回 failed，不生成假路径。",
    ),
    "localize_video": CapabilityDescriptor(
        "localize_video",
        "视频译制与配音",
        ("/api/production/v2/localize-video",),
        True,
        "3O 事务执行转写、术语翻译、双语 ASS/SRT、可选时钟对齐配音、混音和字幕烧录。",
        "需要本地视频；未提供译文时需安装并配置 translation provider，配音需对应 TTS 引擎。",
    ),
    "screenshot_studio": CapabilityDescriptor(
        "screenshot_studio",
        "产品截图合成器",
        (
            "/api/studio/screenshot/projects",
            "/api/studio/screenshot/projects/{id}/export",
        ),
        True,
        "本地截图可套浏览器/设备外框、标注和模糊并导出 PNG/JPG；动画关键帧输出可交给 Remotion。",
        "导出静态图需要 Pillow；动画渲染使用返回的关键帧契约。",
    ),
    "shortdrama_writer": CapabilityDescriptor(
        "shortdrama_writer",
        "短剧编剧 Skill",
        ("/api/shortdrama/writer/draft", "/api/shortdrama/writer/review"),
        True,
        "提供 script-only 短剧剧本草稿、Markdown 格式和审核报告，不伪装生成分镜或视频。",
        "剧本可审核通过后交接 storyboard/video-prompts。",
        execution_ready=True,
        quality_gate_ready=False,
        production_ready=False,
    ),
    "nle_workspace": CapabilityDescriptor(
        "nle_workspace",
        "本地 NLE 工作区",
        ("/api/studio/nle/projects", "/api/studio/timelines/{id}"),
        True,
        "时间线支持项目归属、版本快照、速度/倒放/转场/效果元数据和本地 FFmpeg 重剪。",
        "跨平台桌面壳仍是后续产品形态；当前入口是本地优先 Web 工作区。",
    ),
    "longcat_agent": CapabilityDescriptor(
        "longcat_agent",
        "LongCat 长上下文 Agent",
        ("/api/agent/longcat/capabilities", "/api/agent/longcat/run"),
        bool(os.getenv("LONGCAT_BASE_URL", "").strip()),
        "HEVI 已具备百万 token 上下文打包、推理内容保留和多轮工具循环；LongCat-compatible Provider 已配置。"
        if os.getenv("LONGCAT_BASE_URL", "").strip()
        else "HEVI 的 LongCat agent 契约已就绪，但未配置 LongCat-compatible 推理端点；不会伪造模型回答。",
        None
        if os.getenv("LONGCAT_BASE_URL", "").strip()
        else "配置 LONGCAT_BASE_URL 指向 vLLM/兼容服务；权重由服务端管理，不由 HEVI 安装。",
    ),
    "montage_agentic": CapabilityDescriptor(
        "montage_agentic",
        "Agentic Montage 制片闭环",
        ("/api/montage/pipelines", "/api/montage/run"),
        True,
        "HEVI 原生执行 research/brief→script→scene→assets→edit→compose→publish，带检查点、人工审批、Backlot 事件和真实产物闸。",
        "execute=true 才执行生产；默认先规划并在 checkpoint 处等待审批。缺少真实媒体/渲染器时返回 blocked/failed。",
    ),
    "video_agent": CapabilityDescriptor(
        "video_agent",
        "VideoAgent 证据驱动视频 Agent",
        (
            "/api/montage/video-agent/plan",
            "/api/montage/video-agent/run",
            "/api/studio/tools/video.agent.plan",
            "/api/studio/tools/video.agent.run",
        ),
        True,
        "自然语言意图→类型化 DAG→本地 EvidenceRef 检索→HEVI 时间线；计划、反思、报告和真实产物均可追溯。",
        "语义视频检索需要本地视频及字幕/视觉描述，VLM/ASR 可通过 provider 注入；缺少证据时明确 blocked，不伪造匹配。",
        execution_ready=True,
        quality_gate_ready=False,
        production_ready=False,
    ),
    "mpt": CapabilityDescriptor(
        "mpt",
        "MoneyPrinterTurbo canonical 生成",
        ("/api/mpt/production",),
        True,
        "MPT 由 Hevi TaskService 排队/轮询，多视频结果统一回流 ArtifactManifest。",
        "启动 MPT API，并配置可被 Hevi 读取的 MPT 输出目录。",
    ),
}


class CapabilityUnavailableError(RuntimeError):
    def __init__(self, descriptor: CapabilityDescriptor):
        self.descriptor = descriptor
        super().__init__(descriptor.message)

    def detail(self) -> dict[str, Any]:
        return {"code": "CAPABILITY_UNAVAILABLE", **self.descriptor.public()}


def _runtime_descriptor(descriptor: CapabilityDescriptor) -> CapabilityDescriptor:
    """Refresh capabilities whose configuration is supplied by ``.env``.

    API entrypoints load dotenv before importing this module, but CLI/tests may
    compose the catalog before dotenv is loaded. Reading these six switches at
    call time keeps the catalog truthful in both processes without changing
    the immutable descriptor contract.
    """

    configured: bool | None = None
    if descriptor.id == "voice_studio_tts":
        configured = bool(
            os.getenv("VOICEBOX_BASE_URL", "").strip()
            or os.getenv("GEN_ENGINE_BASE_URL", "").strip()
        )
        return replace(
            descriptor,
            available=configured,
            message=(
                "Voicebox 已配置，可创建可查询、可下载的音频任务。"
                if configured
                else "Voicebox 服务地址未配置；不会创建无法执行的音频任务。"
            ),
            setup=(
                None
                if configured
                else "配置 VOICEBOX_BASE_URL 或 GEN_ENGINE_BASE_URL 并启动 hevi-gen-engine。"
            ),
        )
    if descriptor.id == "voice_streaming_asr":
        configured = bool(os.getenv("VOICE_ASR_STREAM_WS_URL", "").strip())
    elif descriptor.id == "streaming_v2v":
        configured = bool(
            os.getenv("JOYAI_STREAM_WS_URL", "").strip()
            or os.getenv("JOYAI_BASE_URL", "").strip()
        )
    elif descriptor.id == "stock_search":
        configured = bool(os.getenv("PEXELS_API_KEY", "").strip())
    elif descriptor.id == "livestream":
        configured = bool(
            os.getenv("DUIX_SERVICE_URL", "").strip()
            and os.getenv("DUIX_LIVESTREAM_PATH", "").strip()
        )
    elif descriptor.id == "longcat_agent":
        configured = bool(os.getenv("LONGCAT_BASE_URL", "").strip())

    if configured is None:
        return descriptor
    return replace(descriptor, available=configured)


def capability_catalog() -> list[dict[str, Any]]:
    return [_runtime_descriptor(descriptor).public() for descriptor in _CATALOG.values()]


def require_capability(capability_id: str) -> CapabilityDescriptor:
    descriptor = _runtime_descriptor(_CATALOG[capability_id])
    if not descriptor.available:
        raise CapabilityUnavailableError(descriptor)
    return descriptor


def require_production_capability(capability_id: str) -> CapabilityDescriptor:
    """Require a capability with an execution path and delivery gate."""

    descriptor = _runtime_descriptor(_CATALOG[capability_id])
    public = descriptor.public()
    if not public["production_ready"]:
        raise CapabilityUnavailableError(descriptor)
    return descriptor
