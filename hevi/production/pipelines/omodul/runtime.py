"""Twelve production pipelines and a common research-to-compose handoff."""

from __future__ import annotations

from typing import Any

from hevi.production.multimodal_refs import validate_multimodal_references
from hevi.production.pipelines.oprim.contracts import PipelineRequest, PipelineSpec

_COMMON_STAGES = ("research", "proposal", "script", "scene_plan", "assets", "edit", "compose")
_REPO = "https://github.com/"

_SPECS: tuple[PipelineSpec, ...] = (
    PipelineSpec("animated_explainer", "Animated Explainer", "概念解说与图形动画", _COMMON_STAGES, ("researcher", "script_writer", "storyboard_breaker"), ("explainer", "longvideo"), (_REPO + "calesthio/OpenMontage",)),
    PipelineSpec("animation", "Animation", "动画/Manim/HyperFrames", _COMMON_STAGES, ("script_writer", "prompt_generator"), ("cinematic",), (_REPO + "calesthio/OpenMontage",)),
    PipelineSpec("avatar_spokesperson", "Avatar Spokesperson", "数字人和口播视频", _COMMON_STAGES, ("script_rewriter", "voice_director"), ("voice_platform", "presenters"), (_REPO + "calesthio/OpenMontage", _REPO + "waooAI/waoowaoo")),
    PipelineSpec("cinematic", "Cinematic", "电影化叙事与多镜头生成", _COMMON_STAGES, ("researcher", "director", "prompt_generator"), ("director_graph", "longvideo"), (_REPO + "calesthio/OpenMontage", _REPO + "MemeCalculate/moyin-creator")),
    PipelineSpec("clip_factory", "Clip Factory", "长视频拆条与短视频批量", ("ingest", "transcribe", "select", "edit", "compose"), ("extractor", "clip_editor"), ("clip_video",), (_REPO + "calesthio/OpenMontage", _REPO + "YILS-LIN/short-video-factory")),
    PipelineSpec("documentary_montage", "Documentary Montage", "资料研究、引语与纪录片剪辑", _COMMON_STAGES, ("researcher", "quote_extractor", "director"), ("stock_search", "director_graph"), (_REPO + "calesthio/OpenMontage",)),
    PipelineSpec("hybrid", "Hybrid", "真人、素材、动画混合", _COMMON_STAGES, ("director", "prompt_generator", "voice_director"), ("longvideo", "voice_platform"), (_REPO + "calesthio/OpenMontage",)),
    PipelineSpec("localization_dub", "Localization & Dub", "翻译、配音、字幕和混音", ("ingest", "transcribe", "translate", "dub", "compose"), ("translator", "voice_director", "qc"), ("voice_dubbing",), (_REPO + "calesthio/OpenMontage", _REPO + "jamiepine/voicebox")),
    PipelineSpec("podcast_repurpose", "Podcast Repurpose", "播客转短内容/字幕/切片", ("ingest", "transcribe", "select", "caption", "edit", "compose"), ("extractor", "clip_editor"), ("clip_video", "voice_platform"), (_REPO + "calesthio/OpenMontage", _REPO + "Anil-matcha/AI-Youtube-Shorts-Generator")),
    PipelineSpec("screen_demo", "Screen Demo", "产品截图/录屏与交互演示", _COMMON_STAGES, ("researcher", "screen_director", "motion_designer"), ("screenshot_studio", "nle_workspace"), (_REPO + "calesthio/OpenMontage", _REPO + "opennookorg/screenshot-studio")),
    PipelineSpec("talking_head", "Talking Head", "口播驱动镜头与字幕", ("script", "voiceover", "word_timing", "camera_plan", "edit", "compose"), ("script_rewriter", "voice_director", "camera_director"), ("voice_platform",), (_REPO + "calesthio/OpenMontage", _REPO + "Vincentwei1021/video-talkcraft")),
    PipelineSpec("short_drama", "Short Drama", "角色、场景、分镜到短剧成片", _COMMON_STAGES, ("script_rewriter", "extractor", "storyboard_breaker", "prompt_generator"), ("shortdrama", "director_graph", "voice_platform"), (_REPO + "chatfire-AI/huobao-drama", _REPO + "waooAI/waoowaoo")),
)


def list_pipelines() -> list[dict[str, Any]]:
    return [spec.to_dict() for spec in _SPECS]


def get_pipeline(pipeline_id: str) -> PipelineSpec | None:
    return next((spec for spec in _SPECS if spec.pipeline_id == pipeline_id), None)


def compile_pipeline_request(request: PipelineRequest) -> dict[str, Any]:
    spec = get_pipeline(request.pipeline_id)
    errors = [] if spec else [f"unknown pipeline: {request.pipeline_id}"]
    errors.extend(
        validate_multimodal_references(
            images=list(request.images), videos=list(request.videos), audios=list(request.audios), prompt=request.brief
        )
    )
    if not request.brief.strip():
        errors.append("brief is required")
    return {
        "status": "blocked" if errors else "planned",
        "pipeline": spec.to_dict() if spec else None,
        "request": request.to_dict(),
        "stages": list(spec.stages) if spec else [],
        "roles": list(spec.roles) if spec else [],
        "provider_menu": list(spec.required_capabilities) if spec else [],
        "errors": errors,
        "artifact_policy": "only verified local artifacts may advance to compose",
    }


__all__ = ["compile_pipeline_request", "get_pipeline", "list_pipelines"]
