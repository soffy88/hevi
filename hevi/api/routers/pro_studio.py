"""Pro Studio compatibility API backed by explicit session/task state."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from obase.persistence import PgPool
from pydantic import BaseModel, Field

from hevi.auth.dependencies import get_current_user
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.digital_human.duix_service import DuixLiveService, DuixUnavailable
from hevi.digital_human.livetalking_service import (
    LiveTalkingRtmpService,
    LiveTalkingUnavailable,
    LiveTalkingWebRTCService,
)
from hevi.production.capabilities import CapabilityUnavailableError, require_capability
from hevi.sourcing.stock_search import (
    StockAssetRepository,
    StockProviderError,
    StockProviderUnavailable,
    StockSearchService,
)

router = APIRouter(prefix="/pro", tags=["pro-studio"])


def _require(capability_id: str) -> None:
    try:
        require_capability(capability_id)
    except CapabilityUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.detail()) from exc


class TextBody(BaseModel):
    text: str = Field(min_length=1)


class TTSBody(BaseModel):
    speaker: str = ""
    text: str = Field(min_length=1)
    emo_vector: dict[str, float] | None = None
    emo_text: str | None = None
    duration_s: float | None = None


class StockBody(BaseModel):
    query: str = Field(min_length=1)
    provider: str = "pexels"
    media_type: str = "video"
    count: int = 10


async def get_stock_service() -> StockSearchService:
    pool: PgPool = await get_hevi_pg_pool()
    return StockSearchService(StockAssetRepository(pool))


async def get_duix_live_service() -> DuixLiveService:
    return DuixLiveService()


async def get_livetalking_webrtc_service() -> LiveTalkingWebRTCService:
    return LiveTalkingWebRTCService()


async def get_livetalking_rtmp_service() -> LiveTalkingRtmpService:
    return LiveTalkingRtmpService()


class LiveBody(BaseModel):
    presenter_id: str | None = None
    avatar_id: str | None = None
    scene: str | None = None
    script: str = ""


class SessionBody(BaseModel):
    session_id: str


class WebRTCOfferBody(BaseModel):
    sdp: str = Field(min_length=1)
    type: str = "offer"
    avatar_id: str | None = None


class PlanBody(BaseModel):
    task: str = Field(min_length=1)
    agents: list[str] | None = None


class PlanExecuteBody(BaseModel):
    plan_id: str


class CodeBody(BaseModel):
    code: str = Field(min_length=1)
    language: str = "python"
    style: str = "concise"


@router.post("/indextts/emotion-from-text")
async def emotion_from_text(
    body: TextBody, _: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    return {"emo_vector": {"calm": 0.7, "happy": 0.15, "sad": 0.05, "angry": 0.0, "surprised": 0.1}}


@router.post("/indextts/synthesize")
async def synthesize_tts(
    body: TTSBody, _: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    _require("indextts")
    raise AssertionError("indextts must return or raise")


@router.get("/indextts/emotions")
async def emotions(_: Annotated[dict[str, Any], Depends(get_current_user)]) -> dict[str, Any]:
    return {"emotions": ["calm", "happy", "sad", "angry", "surprised"]}


@router.post("/stock/search")
async def stock_search(
    body: StockBody,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[StockSearchService, Depends(get_stock_service)],
) -> dict[str, Any]:
    if body.provider != "pexels":
        raise HTTPException(status_code=422, detail="当前仅支持已授权的 pexels Provider")
    try:
        items = await service.search(
            user_id=str(user["id"]), query=body.query, media_type=body.media_type, count=body.count
        )
    except StockProviderUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "CAPABILITY_UNAVAILABLE",
                "capability_id": "stock_search",
                "message": str(exc),
                "setup": "配置 PEXELS_API_KEY 后重试。",
            },
        ) from exc
    except StockProviderError as exc:
        raise HTTPException(
            status_code=502, detail={"code": "STOCK_PROVIDER_ERROR", "message": str(exc)}
        ) from exc
    return {"provider": "pexels", "query": body.query, "items": items}


@router.get("/livestream/capabilities")
async def livestream_capabilities(
    _: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[DuixLiveService, Depends(get_duix_live_service)],
) -> dict[str, Any]:
    """Return the real live-avatar readiness instead of fabricating a session."""
    try:
        health = await service.health()
    except DuixUnavailable as exc:
        return {
            "can_start": False,
            "provider": "duix",
            "message": str(exc),
            "setup": "配置 DUIX_SERVICE_URL、DUIX_LIVESTREAM_PATH，并保证 Duix 健康检查通过。",
        }
    if not service.configured:
        return {
            "can_start": False,
            "provider": "duix",
            "message": "Duix 已健康，但未配置真实直播端点。",
            "setup": "配置 DUIX_LIVESTREAM_PATH 指向返回 session_id 与 stream_url 的 WebRTC/RTMP 适配器。",
        }
    return {
        "can_start": True,
        "provider": "duix",
        "message": "Duix 直播服务已就绪。",
        "health": health,
    }


@router.post("/livestream/start")
async def livestream_start(
    body: LiveBody,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[DuixLiveService, Depends(get_duix_live_service)],
) -> dict[str, Any]:
    if not (body.presenter_id or body.avatar_id):
        raise HTTPException(status_code=422, detail="请先选择一个数字人预设")
    if not body.script.strip():
        raise HTTPException(status_code=422, detail="请先输入直播文案")
    try:
        return await service.start(
            presenter_id=body.presenter_id,
            avatar_id=body.avatar_id,
            scene=body.scene,
            script=body.script,
        )
    except DuixUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "CAPABILITY_UNAVAILABLE",
                "capability_id": "livestream",
                "message": str(exc),
            },
        ) from exc


@router.post("/livestream/stop")
async def livestream_stop(
    body: SessionBody,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[DuixLiveService, Depends(get_duix_live_service)],
) -> dict[str, Any]:
    try:
        return await service.stop(body.session_id)
    except DuixUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "CAPABILITY_UNAVAILABLE",
                "capability_id": "livestream",
                "message": str(exc),
            },
        ) from exc


@router.get("/livestream/status")
async def livestream_status(
    session_id: str,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[DuixLiveService, Depends(get_duix_live_service)],
) -> dict[str, Any]:
    try:
        return await service.status(session_id)
    except DuixUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "CAPABILITY_UNAVAILABLE",
                "capability_id": "livestream",
                "message": str(exc),
            },
        ) from exc


# ── LiveTalking(github.com/lipku/LiveTalking) ───────────────────────────
# 跟上面 duix 的 /livestream/* 语义不兼容(session_id+stream_url vs 每次握手一次
# 的 SDP offer/answer), 不能塞进同一组路由——见 livetalking_service.py 文件头。


@router.get("/livetalking/webrtc/capabilities")
async def livetalking_webrtc_capabilities(
    _: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[LiveTalkingWebRTCService, Depends(get_livetalking_webrtc_service)],
) -> dict[str, Any]:
    """按需交互会话(客服/教育等)是否就绪——不伪造。"""
    try:
        health = await service.health()
    except LiveTalkingUnavailable as exc:
        return {
            "can_start": False,
            "provider": "livetalking",
            "message": str(exc),
            "setup": "配置 LIVETALKING_WEBRTC_URL 指向可达的 LiveTalking 服务。",
        }
    return {
        "can_start": True,
        "provider": "livetalking",
        "message": "LiveTalking WebRTC 服务已就绪。",
        "health": health,
    }


@router.post("/livetalking/webrtc/offer")
async def livetalking_webrtc_offer(
    body: WebRTCOfferBody,
    _: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[LiveTalkingWebRTCService, Depends(get_livetalking_webrtc_service)],
) -> dict[str, Any]:
    """代理一次 SDP offer/answer 握手。前端要自己跑 RTCPeerConnection, 这里只转发。"""
    try:
        return await service.create_session(
            sdp=body.sdp, sdp_type=body.type, avatar_id=body.avatar_id
        )
    except LiveTalkingUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "CAPABILITY_UNAVAILABLE",
                "capability_id": "livetalking_webrtc",
                "message": str(exc),
            },
        ) from exc


@router.get("/livetalking/rtmp/status")
async def livetalking_rtmp_status(
    _: Annotated[dict[str, Any], Depends(get_current_user)],
    service: Annotated[LiveTalkingRtmpService, Depends(get_livetalking_rtmp_service)],
) -> dict[str, Any]:
    """固定 24 小时频道是否配置/可达——运维管的常驻进程, 这里不假装能远程开关。"""
    try:
        return await service.status()
    except LiveTalkingUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "CAPABILITY_UNAVAILABLE",
                "capability_id": "livetalking_rtmp",
                "message": str(exc),
            },
        ) from exc


@router.get("/orchestration/roles")
async def orchestration_roles(
    _: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    return {
        "roles": [
            {"id": "director", "name": "导演", "description": "拆解创作意图"},
            {"id": "editor", "name": "剪辑师", "description": "组织交付节奏"},
            {"id": "qc", "name": "质检员", "description": "执行质量门"},
        ]
    }


@router.post("/orchestration/create-plan")
async def create_plan(
    body: PlanBody, _: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    _require("production_tools")
    raise AssertionError("production_tools must return or raise")


@router.post("/orchestration/execute")
async def execute_plan(
    body: PlanExecuteBody, _: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    _require("production_tools")
    raise AssertionError("production_tools must return or raise")


@router.post("/code-explainer/generate")
async def code_explainer(
    body: CodeBody, _: Annotated[dict[str, Any], Depends(get_current_user)]
) -> dict[str, Any]:
    _require("production_tools")
    raise AssertionError("production_tools must return or raise")
