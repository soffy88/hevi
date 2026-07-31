"""Pro Studio API — 第三批新能力 (IndexTTS2/素材搜索/直播/多Agent/代码解说)。

20 个端点覆盖:
  - IndexTTS2 情感语音 (indextts)
  - 素材自动搜索 (stock)
  - 数字人直播 (livestream)
  - 多 Agent 编排 (orchestration)
  - 代码解说视频 (code-explainer)
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pro", tags=["pro-studio"])


# ===================================================================
# 1. IndexTTS2 情感语音
# ===================================================================

class EmotionVectorBody(BaseModel):
    happy: float = 0.0
    angry: float = 0.0
    sad: float = 0.0
    afraid: float = 0.0
    disgusted: float = 0.0
    melancholic: float = 0.0
    surprised: float = 0.0
    calm: float = 0.0


class IndexTTSBody(BaseModel):
    text: str
    speaker_audio_path: str
    emotion_vector: EmotionVectorBody | None = None
    emotion_audio_path: str | None = None
    emotion_text: str | None = None
    emotion_alpha: float = 1.0
    use_emo_text: bool = False
    target_duration_sec: float | None = None
    language: str = "zh"
    output_path: str = "/tmp/indextts_output.wav"


@router.post("/indextts/synthesize")
async def api_indextts_synthesize(req: IndexTTSBody):
    """IndexTTS2 情感语音合成。"""
    from hevi.audio.indextts_service import (
        IndexTTSRequest, EmotionVector, synthesize_indextts,
    )
    emo = None
    if req.emotion_vector:
        emo = EmotionVector(**req.emotion_vector.model_dump())

    request = IndexTTSRequest(
        text=req.text,
        speaker_audio_path=req.speaker_audio_path,
        emotion_vector=emo,
        emotion_audio_path=req.emotion_audio_path,
        emotion_text=req.emotion_text,
        emotion_alpha=req.emotion_alpha,
        use_emo_text=req.use_emo_text,
        target_duration_sec=req.target_duration_sec,
        language=req.language,
        output_path=req.output_path,
    )
    result = await synthesize_indextts(request)
    return result.model_dump()


@router.post("/indextts/emotion-from-text")
async def api_emotion_from_text(body: dict):
    """从文本提取情绪向量。"""
    from hevi.audio.indextts_service import emotion_from_text
    text = body.get("text", "")
    vector = emotion_from_text(text)
    return {"text": text, "emotion_vector": vector.model_dump()}


@router.get("/indextts/emotions")
async def api_list_emotions():
    """列出支持的情绪维度。"""
    from hevi.audio.indextts_service import supported_emotions
    return {"emotions": supported_emotions()}


# ===================================================================
# 2. 素材自动搜索
# ===================================================================

class StockSearchBody(BaseModel):
    query: str
    media_type: str = "video"
    provider: str = "pexels"
    count: int = 5
    min_width: int = 1280
    min_height: int = 720
    orientation: str = "landscape"
    color: str | None = None


@router.post("/stock/search")
async def api_search_stock(req: StockSearchBody):
    """搜索素材。"""
    from hevi.image.stock_footage import (
        StockSearchRequest, StockMediaType, StockProvider, search_stock,
    )
    request = StockSearchRequest(
        query=req.query,
        media_type=StockMediaType(req.media_type),
        provider=StockProvider(req.provider),
        count=req.count,
        min_width=req.min_width,
        min_height=req.min_height,
        orientation=req.orientation,
        color=req.color,
    )
    result = await search_stock(request)
    return result.model_dump()


class ScriptToClipsBody(BaseModel):
    script: str
    clips_count: int = 5
    provider: str = "pexels"
    output_dir: str = "/tmp/stock_clips"


@router.post("/stock/script-to-clips")
async def api_script_to_clips(req: ScriptToClipsBody):
    """脚本 → 自动提取关键词 → 搜索素材 → 下载。"""
    from hevi.image.stock_footage import StockProvider, script_to_stock_clips
    result = await script_to_stock_clips(
        req.script,
        clips_count=req.clips_count,
        provider=StockProvider(req.provider),
        output_dir=req.output_dir,
    )
    return result


# ===================================================================
# 3. 数字人直播
# ===================================================================

class LiveStreamBody(BaseModel):
    platform: str = "douyin"
    rtmp_url: str = ""
    stream_key: str = ""
    portrait_path: str = ""
    voice_id: str = "default"
    title: str = ""
    script: str = ""
    products: list[str] = Field(default_factory=list)
    max_duration_min: int = 120


@router.post("/livestream/start")
async def api_start_livestream(req: LiveStreamBody):
    """启动数字人直播。"""
    from hevi.livestream import (
        LiveStreamConfig, LiveStreamPlatform, LiveStreamRequest, start_livestream,
    )
    config = LiveStreamConfig(
        platform=LiveStreamPlatform(req.platform),
        rtmp_url=req.rtmp_url,
        stream_key=req.stream_key,
        portrait_path=req.portrait_path,
        voice_id=req.voice_id,
        title=req.title,
    )
    request = LiveStreamRequest(
        config=config,
        script=req.script,
        products=req.products,
        max_duration_min=req.max_duration_min,
    )
    status = await start_livestream(request)
    return status.model_dump()


@router.post("/livestream/stop")
async def api_stop_livestream(body: dict):
    """停止直播。"""
    from hevi.livestream import stop_livestream
    stream_id = body.get("stream_id", "")
    status = await stop_livestream(stream_id)
    if not status:
        raise HTTPException(404, "Stream not found")
    return status.model_dump()


@router.get("/livestream/status")
async def api_livestream_status():
    """获取所有活跃直播状态。"""
    from hevi.livestream import list_active_streams
    streams = list_active_streams()
    return {"active_streams": [s.model_dump() for s in streams]}


class ProductBody(BaseModel):
    name: str
    price: str = ""
    description: str = ""
    script: str = ""
    keywords: list[str] = Field(default_factory=list)


@router.post("/livestream/products")
async def api_add_product(req: ProductBody):
    """添加直播产品。"""
    from hevi.livestream import ProductItem, add_product
    product = ProductItem(**req.model_dump())
    result = add_product(product)
    return result.model_dump()


@router.get("/livestream/products")
async def api_list_products():
    """列出所有产品。"""
    from hevi.livestream import list_products
    return {"products": [p.model_dump() for p in list_products()]}


class ChatReplyBody(BaseModel):
    stream_id: str
    message_id: str
    reply_text: str


@router.post("/livestream/chat-reply")
async def api_chat_reply(req: ChatReplyBody):
    """回复弹幕。"""
    from hevi.livestream import send_chat_reply
    result = await send_chat_reply(req.stream_id, req.message_id, req.reply_text)
    if not result:
        raise HTTPException(404, "Message not found")
    return result.model_dump()


# ===================================================================
# 4. 多 Agent 编排
# ===================================================================

class PlanBody(BaseModel):
    script: str
    style: str = "default"
    platforms: list[str] | None = None


@router.post("/orchestration/create-plan")
async def api_create_plan(req: PlanBody):
    """创建视频制作计划。"""
    from hevi.agent.orchestration import create_video_plan
    plan = create_video_plan(req.script, req.style, req.platforms)
    return plan.model_dump()


@router.post("/orchestration/execute")
async def api_execute_plan(body: dict):
    """执行计划。"""
    from hevi.agent.orchestration import AgentOrchestrator
    plan_id = body.get("plan_id", "")
    orchestrator = AgentOrchestrator()
    result = await orchestrator.execute_plan(plan_id)
    if not result:
        raise HTTPException(404, "Plan not found")
    return result.model_dump()


@router.get("/orchestration/roles")
async def api_list_roles():
    """列出 Agent 角色。"""
    from hevi.agent.orchestration import AgentRole
    return {"roles": [r.value for r in AgentRole]}


# ===================================================================
# 5. 代码解说视频
# ===================================================================

class CodeBlockBody(BaseModel):
    code: str
    language: str = "python"
    narration: str = ""
    highlight_lines: list[int] = Field(default_factory=list)
    animation: str = "typewriter"


class CodeExplainerBody(BaseModel):
    blocks: list[CodeBlockBody]
    title: str = ""
    voice_id: str = "default"
    theme: str = "monokai"
    font_size: int = 24
    output_path: str = "/tmp/code_explainer.mp4"
    resolution: str = "1080x1920"
    add_subtitles: bool = True


@router.post("/code-explainer/generate")
async def api_generate_code_explainer(req: CodeExplainerBody):
    """生成代码解说视频。"""
    from hevi.assembly.code_explainer import (
        CodeBlock, CodeExplainerRequest, generate_code_explainer,
    )
    blocks = [CodeBlock(**b.model_dump()) for b in req.blocks]
    request = CodeExplainerRequest(
        blocks=blocks,
        title=req.title,
        voice_id=req.voice_id,
        theme=req.theme,
        font_size=req.font_size,
        output_path=req.output_path,
        resolution=req.resolution,
        add_subtitles=req.add_subtitles,
    )
    result = await generate_code_explainer(request)
    return result.model_dump()


@router.post("/code-explainer/highlight")
async def api_highlight_code(body: dict):
    """代码语法高亮预览。"""
    from hevi.assembly.code_explainer import _highlight_code
    code = body.get("code", "")
    language = body.get("language", "python")
    theme = body.get("theme", "monokai")
    html = _highlight_code(code, language, theme)
    return {"html": html}
