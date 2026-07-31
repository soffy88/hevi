"""发布/动效/HTML视频/本地语音/编舞 — 新能力 API 路由。

15 个端点覆盖:
  - 多平台发布 (publisher)
  - 动效模板库 (motion)
  - HTML 视频管线 (html-video)
  - OmniVoice 本地语音 (omnivoice)
  - Wan-Dancer 编舞 (dance)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/studio", tags=["studio"])


# ===================================================================
# 1. Multi-platform Publisher
# ===================================================================

class PublishRequest(BaseModel):
    platform: str  # xiaohongshu, douyin, bilibili, wechat_video, youtube
    video_path: str
    title: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    cover_path: str | None = None
    auto_publish: bool = False


class BatchPublishRequest(BaseModel):
    tasks: list[PublishRequest]
    auto_publish: bool = False
    max_parallel: int = 3


class ConfirmRequest(BaseModel):
    task_id: str


class ScheduleRequest(BaseModel):
    task_id: str
    publish_at: str  # ISO datetime


@router.post("/publish")
async def api_publish(req: PublishRequest):
    """发布单个视频到指定平台。"""
    from hevi.publisher import (
        PublishPlatform, PublishTask, publish_video, get_platform_config,
    )
    try:
        platform = PublishPlatform(req.platform)
    except ValueError:
        raise HTTPException(400, f"Unknown platform: {req.platform}")

    task = PublishTask(
        platform=platform,
        video_path=req.video_path,
        title=req.title,
        description=req.description,
        tags=req.tags,
        cover_path=req.cover_path,
        auto_publish=req.auto_publish,
    )
    config = get_platform_config(platform)
    result = await publish_video(task, config)
    return result.model_dump()


@router.post("/publish/batch")
async def api_publish_batch(req: BatchPublishRequest):
    """批量发布到多个平台。"""
    from hevi.publisher import (
        PublishPlatform, PublishTask, PublishBatchRequest, publish_batch,
    )
    tasks = []
    for t in req.tasks:
        try:
            platform = PublishPlatform(t.platform)
        except ValueError:
            raise HTTPException(400, f"Unknown platform: {t.platform}")
        tasks.append(PublishTask(
            platform=platform,
            video_path=t.video_path,
            title=t.title,
            description=t.description,
            tags=t.tags,
            cover_path=t.cover_path,
            auto_publish=req.auto_publish,
        ))
    batch = PublishBatchRequest(tasks=tasks, auto_publish=req.auto_publish, max_parallel=req.max_parallel)
    result = await publish_batch(batch)
    return result.model_dump()


@router.post("/publish/confirm")
async def api_confirm_publish(req: ConfirmRequest):
    """确认预发布任务,点击发布。"""
    from hevi.publisher import confirm_publish
    result = await confirm_publish(req.task_id)
    if not result:
        raise HTTPException(404, "Task not found")
    return result.model_dump()


@router.post("/publish/schedule")
async def api_schedule_publish(req: ScheduleRequest):
    """安排定时发布。"""
    from datetime import datetime
    from hevi.publisher import schedule_publish, _tasks
    task = _tasks.get(req.task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    dt = datetime.fromisoformat(req.publish_at)
    task_id = await schedule_publish(task, dt)
    return {"task_id": task_id, "scheduled_at": req.publish_at}


@router.get("/publish/platforms")
async def api_list_platforms():
    """列出支持的发布平台及配置。"""
    from hevi.publisher import PublishPlatform, get_platform_config
    platforms = []
    for p in PublishPlatform:
        config = get_platform_config(p)
        platforms.append({
            "platform": p.value,
            "title_limit": config.title_limit,
            "tags_limit": config.tags_limit,
            "max_file_size_mb": config.max_file_size_mb,
        })
    return {"platforms": platforms}


# ===================================================================
# 2. Motion Templates
# ===================================================================

@router.get("/motion/templates")
async def api_list_motion_templates(category: str = "", search: str = ""):
    """列出所有动效模板。"""
    from hevi.video.motion_templates import get_catalog
    catalog = get_catalog()
    if category:
        templates = catalog.get_by_category(category)
    elif search:
        templates = catalog.search(search)
    else:
        templates = catalog.templates
    return {
        "templates": [
            {"id": t.id, "name": t.name, "category": t.category,
             "description": t.description, "variables": [v.model_dump() for v in t.variables],
             "supports_transparent": t.supports_transparent}
            for t in templates
        ],
        "categories": catalog.categories,
        "total": len(templates),
    }


class MotionRenderBody(BaseModel):
    template_id: str
    preset_name: str | None = None
    variables: dict[str, Any] = Field(default_factory=dict)
    width: int = 1920
    height: int = 1080
    fps: int = 30
    duration: float = 5.0
    transparent: bool = False
    output_format: str = "mp4"


@router.post("/motion/render")
async def api_render_motion(req: MotionRenderBody):
    """渲染动效模板为视频。"""
    from hevi.video.motion_templates import MotionRenderRequest, render_motion
    request = MotionRenderRequest(
        template_id=req.template_id,
        preset_name=req.preset_name,
        variables=req.variables,
        width=req.width, height=req.height,
        fps=req.fps, duration=req.duration,
        transparent=req.transparent,
        output_format=req.output_format,
    )
    result = await render_motion(request)
    return result.model_dump()


# ===================================================================
# 3. HTML Video Pipeline
# ===================================================================

@router.get("/html-video/templates")
async def api_list_html_templates():
    """列出所有 HTML 视频模板。"""
    from hevi.video.html_templates import list_html_templates
    templates = list_html_templates()
    return {
        "templates": [
            {"id": t.id, "name": t.name, "category": t.category,
             "description": t.description, "variables": t.variables, "defaults": t.defaults}
            for t in templates
        ],
        "total": len(templates),
    }


class HtmlVideoBody(BaseModel):
    template_id: str | None = None
    raw_html: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    width: int = 1920
    height: int = 1080
    fps: int = 30
    duration: float = 5.0


@router.post("/html-video/render")
async def api_render_html_video(req: HtmlVideoBody):
    """渲染 HTML 视频。"""
    from hevi.video.html_video_pipeline import HtmlVideoRequest, render_html_video
    request = HtmlVideoRequest(
        template_id=req.template_id,
        raw_html=req.raw_html,
        data=req.data,
        width=req.width, height=req.height,
        fps=req.fps, duration=req.duration,
    )
    result = await render_html_video(request)
    return result.model_dump()


class ScriptToVideoBody(BaseModel):
    script: str
    style: str = "dark"
    aspect_ratio: str = "16:9"


@router.post("/html-video/script-to-video")
async def api_script_to_video(req: ScriptToVideoBody):
    """脚本 → 内容图 → 分镜 → 视频 (一键生成)。"""
    from hevi.video.content_graph import parse_script_to_graph, graph_to_storyboard
    from hevi.video.html_video_pipeline import render_storyboard
    from pathlib import Path

    graph = parse_script_to_graph(req.script, style=req.style, aspect_ratio=req.aspect_ratio)
    storyboard = graph_to_storyboard(graph)
    output = Path(f"/tmp/script_video_{id(req):x}.mp4")
    result = await render_storyboard(storyboard, output)
    return result.model_dump()


# ===================================================================
# 4. OmniVoice Local Voice Pipeline
# ===================================================================

class VoiceCloneBody(BaseModel):
    reference_audio_path: str
    target_text: str
    language: str = "zh"
    output_path: str = "/tmp/clone_output.wav"


@router.post("/voice/clone")
async def api_clone_voice(req: VoiceCloneBody):
    """从参考音频克隆声音。"""
    from hevi.audio.omnivoice_service import VoiceCloneRequest, clone_voice
    request = VoiceCloneRequest(
        reference_audio_path=req.reference_audio_path,
        target_text=req.target_text,
        language=req.language,
        output_path=req.output_path,
    )
    result = await clone_voice(request)
    return result.model_dump()


class DubBody(BaseModel):
    source_video_path: str
    target_language: str = "en"
    speaker_mapping: dict[str, str] = Field(default_factory=dict)
    output_path: str = "/tmp/dub_output.mp4"


@router.post("/voice/dub")
async def api_dub_video(req: DubBody):
    """视频配音。"""
    from hevi.audio.omnivoice_service import DubRequest, dub_video
    request = DubRequest(
        source_video_path=req.source_video_path,
        target_language=req.target_language,
        speaker_mapping=req.speaker_mapping,
        output_path=req.output_path,
    )
    result = await dub_video(request)
    return result.model_dump()


class AudiobookBody(BaseModel):
    text_or_path: str
    voice_id: str = "default"
    output_path: str = "/tmp/audiobook.mp3"
    format: str = "mp3"


@router.post("/voice/audiobook")
async def api_generate_audiobook(req: AudiobookBody):
    """生成有声书。"""
    from hevi.audio.omnivoice_service import AudiobookRequest, generate_audiobook
    request = AudiobookRequest(
        text_or_path=req.text_or_path,
        voice_id=req.voice_id,
        output_path=req.output_path,
        format=req.format,
    )
    result = await generate_audiobook(request)
    return result.model_dump()


class DictateBody(BaseModel):
    audio_path: str
    language: str = "auto"
    punctuation: bool = True
    output_format: str = "txt"


@router.post("/voice/dictate")
async def api_dictate(req: DictateBody):
    """语音转文字。"""
    from hevi.audio.omnivoice_service import DictationRequest, dictate
    request = DictationRequest(
        audio_path=req.audio_path,
        language=req.language,
        punctuation=req.punctuation,
        output_format=req.output_format,
    )
    result = await dictate(request)
    return result.model_dump()


class DiarizeBody(BaseModel):
    audio_path: str
    min_speakers: int = 1
    max_speakers: int = 8


@router.post("/voice/diarize")
async def api_diarize(req: DiarizeBody):
    """说话人分离。"""
    from hevi.audio.omnivoice_service import DiarizeRequest, diarize
    request = DiarizeRequest(
        audio_path=req.audio_path,
        min_speakers=req.min_speakers,
        max_speakers=req.max_speakers,
    )
    result = await diarize(request)
    return result.model_dump()


class VoiceDesignBody(BaseModel):
    description: str = ""
    gender: str = "female"
    age_range: str = "adult"
    language: str = "zh"


@router.post("/voice/design")
async def api_design_voice(req: VoiceDesignBody):
    """根据描述设计声音。"""
    from hevi.audio.omnivoice_service import VoiceDesignRequest, design_voice
    request = VoiceDesignRequest(
        description=req.description,
        gender=req.gender,
        age_range=req.age_range,
        language=req.language,
    )
    result = await design_voice(request)
    return result.model_dump()


@router.get("/voice/local-voices")
async def api_list_local_voices():
    """列出本地已克隆/设计的声音。"""
    from hevi.audio.omnivoice_service import list_local_voices
    return {"voices": list_local_voices()}


# ===================================================================
# 5. Wan-Dancer Music-to-Dance
# ===================================================================

class DanceBody(BaseModel):
    music_path: str
    genre: str = "kpop"
    duration: float = 60.0
    character_name: str = "dancer"
    resolution: str = "720p"
    fps: int = 30
    output_path: str = "/tmp/dance_output.mp4"
    camera_motion: str | None = None
    lighting_style: str | None = None


@router.post("/dance/generate")
async def api_generate_dance(req: DanceBody):
    """生成音乐编舞视频。"""
    from hevi.video.provider_wan_dancer import (
        DanceGenre, DanceCharacter, WanDancerRequest, generate_dance_video,
    )
    try:
        genre = DanceGenre(req.genre)
    except ValueError:
        raise HTTPException(400, f"Unknown genre: {req.genre}. Available: {[g.value for g in DanceGenre]}")

    request = WanDancerRequest(
        music_path=req.music_path,
        genre=genre,
        duration=req.duration,
        character=DanceCharacter(name=req.character_name),
        resolution=req.resolution,
        fps=req.fps,
        output_path=req.output_path,
        camera_motion=req.camera_motion,
        lighting_style=req.lighting_style,
    )
    result = await generate_dance_video(request)
    return result.model_dump()


@router.get("/dance/genres")
async def api_dance_genres():
    """列出支持的舞蹈类型。"""
    from hevi.video.provider_wan_dancer import supported_genres
    return {"genres": [g.value for g in supported_genres()]}


@router.get("/dance/gpu-check")
async def api_gpu_check():
    """检查 GPU 是否满足编舞要求。"""
    from hevi.video.provider_wan_dancer import check_gpu_requirements
    return check_gpu_requirements()
