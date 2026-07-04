from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from obase.persistence import PgPool
from pydantic import BaseModel

from hevi.auth.dependencies import get_current_user
from hevi.auth.jwt_handler import decode_access_token
from hevi.db.pg_pool import get_hevi_pg_pool
from hevi.subjects.repository import SubjectRepository
from hevi.subjects.subject_service import SubjectService

router = APIRouter(prefix="/subjects", tags=["subjects"])

_MAX_IMAGE_BYTES = 12 * 1024 * 1024  # 12MB 单张参考图上限
_MAX_AUDIO_BYTES = 20 * 1024 * 1024  # 20MB 声音参考片段上限


async def _read_image_upload(file: UploadFile) -> bytes:
    """校验并读取上传的图片(类型/大小),返回字节。"""
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=422, detail="只接受图片文件")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="空文件")
    if len(data) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="图片过大(上限 12MB)")
    return data


async def _read_audio_upload(file: UploadFile) -> bytes:
    """校验并读取上传的声音参考片段(类型/大小),返回字节。"""
    if not (file.content_type or "").startswith("audio/"):
        raise HTTPException(status_code=422, detail="只接受音频文件")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="空文件")
    if len(data) > _MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="音频过大(上限 20MB)")
    return data


def _check_owner(resource: dict[str, Any], user: dict[str, Any]) -> None:
    """404 (not 403, to avoid leaking existence) if the resource belongs to
    someone else. Legacy rows with no owner stay accessible."""
    if resource.get("user_id") and resource["user_id"] != str(user["id"]):
        raise HTTPException(status_code=404, detail="Subject not found")


def _serialize_subject(s: dict[str, Any]) -> dict[str, Any]:
    return {**s, "subject_id": s.get("id"), "kind": s.get("subject_type")}


class SubjectCreateRequest(BaseModel):
    kind: str
    name: str
    description: str = ""
    reference_images: list[str] = []
    metadata: dict[str, Any] = {}
    tags: list[str] = []
    user_id: str | None = None


class SubjectUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class ReferenceOrderRequest(BaseModel):
    """整体替换参考图列表 —— 覆盖设封面(选中的挪到第 0 位)/ 删除(去掉某项)/
    排序(给新顺序)三种操作,前端把算好的目标顺序整体传回来。"""

    reference_images: list[str]


async def get_pg_pool() -> PgPool:
    return await get_hevi_pg_pool()


async def get_subject_service(
    pool: Annotated[PgPool, Depends(get_pg_pool)],
) -> SubjectService:
    return SubjectService(SubjectRepository(pool))


@router.post("", status_code=201)
@router.post("/", status_code=201)
async def create_subject(
    body: SubjectCreateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SubjectService, Depends(get_subject_service)],
) -> dict[str, Any]:
    try:
        return _serialize_subject(
            await svc.create_subject(
                kind=body.kind,
                name=body.name,
                description=body.description,
                reference_images=body.reference_images if body.reference_images else None,
                metadata=body.metadata,
                tags=body.tags,
                user_id=str(user["id"]),  # owner is the authenticated user, not client-supplied
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/from-photo", status_code=201)
async def create_subject_from_photo(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SubjectService, Depends(get_subject_service)],
    file: Annotated[UploadFile, File(description="角色照片")],
    name: Annotated[str, Form()] = "我的角色",
    kind: Annotated[str, Form()] = "character",
    description: Annotated[str, Form()] = "",
) -> dict[str, Any]:
    """上传一张照片 → 直接建一个角色(把照片存为其参考图)。

    这是"我上传一张照片,生成此照片的角色"的落地入口。存下的照片随后可在生成时选中,
    作为每个镜头的 i2v 参考图锁定角色身份,让视频里始终是同一个人。
    """
    data = await _read_image_upload(file)
    try:
        subject = await svc.create_subject(
            kind=kind, name=name, description=description, user_id=str(user["id"])
        )
        updated = await svc.add_reference_upload(
            str(subject["id"]), filename=file.filename or "photo.jpg", data=data
        )
        return _serialize_subject(updated or subject)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{subject_id}/reference", status_code=201)
async def upload_subject_reference(
    subject_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SubjectService, Depends(get_subject_service)],
    file: Annotated[UploadFile, File(description="参考图")],
) -> dict[str, Any]:
    """给已有角色再上传一张参考图(多角度参考提升锁定效果)。"""
    subject = await svc.get_subject(subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    _check_owner(subject, user)
    data = await _read_image_upload(file)
    updated = await svc.add_reference_upload(
        subject_id, filename=file.filename or "photo.jpg", data=data
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return _serialize_subject(updated)


@router.post("/{subject_id}/references", status_code=201)
async def upload_subject_references_batch(
    subject_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SubjectService, Depends(get_subject_service)],
    files: Annotated[list[UploadFile], File(description="多张参考图,一次全传")],
) -> dict[str, Any]:
    """一次上传多张参考图(替代此前只能一张张调 /reference)。全部落盘后只重算一次
    身份向量(多角度参考让识别更稳)。"""
    subject = await svc.get_subject(subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    _check_owner(subject, user)
    payload = [(f.filename or "photo.jpg", await _read_image_upload(f)) for f in files]
    updated = await svc.add_reference_uploads(subject_id, files=payload)
    if updated is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return _serialize_subject(updated)


@router.put("/{subject_id}/references")
async def reorder_subject_references(
    subject_id: str,
    body: ReferenceOrderRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SubjectService, Depends(get_subject_service)],
) -> dict[str, Any]:
    """整体替换参考图列表 —— 设封面(挪到第 0 位,下游锁脸/评分卡都用 reference_images[0])
    / 删除 / 排序,前端传目标顺序。重算身份向量。"""
    subject = await svc.get_subject(subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    _check_owner(subject, user)
    updated = await svc.update_references(subject_id, reference_images=body.reference_images)
    if updated is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return _serialize_subject(updated)


@router.post("/{subject_id}/voice", status_code=201)
async def upload_subject_voice(
    subject_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SubjectService, Depends(get_subject_service)],
    file: Annotated[UploadFile, File(description="声音参考片段(几秒到十几秒人声)")],
) -> dict[str, Any]:
    """上传角色声音参考 → VibeVoice 零样本声音克隆(仅该配音引擎生效)。"""
    subject = await svc.get_subject(subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    _check_owner(subject, user)
    data = await _read_audio_upload(file)
    updated = await svc.add_voice_reference(
        subject_id, filename=file.filename or "voice.wav", data=data
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return _serialize_subject(updated)


@router.post("/{subject_id}/wardrobe", status_code=201)
async def upload_subject_wardrobe(
    subject_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SubjectService, Depends(get_subject_service)],
    file: Annotated[UploadFile, File(description="造型/服装参考图")],
) -> dict[str, Any]:
    """上传造型参考图 —— 与身份参考图分开管理(不参与脸部锁定/身份向量)。"""
    subject = await svc.get_subject(subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    _check_owner(subject, user)
    data = await _read_image_upload(file)
    updated = await svc.add_wardrobe_upload(
        subject_id, filename=file.filename or "outfit.jpg", data=data
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    return _serialize_subject(updated)


@router.get("")
@router.get("/")
async def list_subjects(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SubjectService, Depends(get_subject_service)],
    kind: str | None = None,
    query: str | None = None,
) -> list[dict[str, Any]]:
    # Scope to the caller — never honor a client-supplied user_id.
    results = await svc.search_subjects(kind=kind, query=query, user_id=str(user["id"]))
    return [_serialize_subject(s) for s in results]


@router.get("/{subject_id}/image")
async def get_subject_image(
    subject_id: str,
    svc: Annotated[SubjectService, Depends(get_subject_service)],
    token: Annotated[str | None, Query(description="JWT (<img> can't send headers)")] = None,
    idx: int = 0,
    source: str = "reference",
) -> FileResponse:
    """返回角色的第 idx 张图(供前端 <img> 显示)。<img> 不能带 header,token 走 ?token=,
    同成片视频端点。source="reference"(默认,身份参考图)或 "wardrobe"(造型参考图,
    存在 metadata.wardrobe_images,与身份参考图分开管理)。"""
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        user_id = decode_access_token(token).get("sub")
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from exc
    subject = await svc.get_subject(subject_id)
    if not subject or (subject.get("user_id") and subject["user_id"] != str(user_id)):
        raise HTTPException(status_code=404, detail="Subject not found")
    if source == "wardrobe":
        refs = (subject.get("metadata") or {}).get("wardrobe_images") or []
    else:
        refs = subject.get("reference_images") or []
    if not (0 <= idx < len(refs)):
        raise HTTPException(status_code=404, detail="Reference image not found")
    path = Path(refs[idx])
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file missing")
    return FileResponse(str(path))


@router.get("/{subject_id}")
async def get_subject(
    subject_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SubjectService, Depends(get_subject_service)],
) -> dict[str, Any]:
    subject = await svc.get_subject(subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    _check_owner(subject, user)
    return _serialize_subject(subject)


@router.patch("/{subject_id}")
async def update_subject(
    subject_id: str,
    body: SubjectUpdateRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SubjectService, Depends(get_subject_service)],
) -> dict[str, Any]:
    """编辑角色。此前只能改 metadata(Phase 1 前);现在姓名/描述/标签也能改 —— 建号后
    发现名字打错了也不用删了重建。两类更新分别落库(字段一次,metadata 一次),最终
    结果都读一次最新记录返回。"""
    existing = await svc.get_subject(subject_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    _check_owner(existing, user)
    result = existing
    if body.name is not None or body.description is not None or body.tags is not None:
        try:
            updated = await svc.update_subject_fields(
                subject_id, name=body.name, description=body.description, tags=body.tags
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="Subject not found")
        result = updated
    if body.metadata is not None:
        updated = await svc.update_subject_metadata(subject_id, metadata=body.metadata)
        if updated is None:
            raise HTTPException(status_code=404, detail="Subject not found")
        result = updated
    return _serialize_subject(result)


@router.delete("/{subject_id}", status_code=200)
async def delete_subject(
    subject_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    svc: Annotated[SubjectService, Depends(get_subject_service)],
) -> dict[str, str]:
    existing = await svc.get_subject(subject_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Subject not found")
    _check_owner(existing, user)
    deleted = await svc.delete_subject(subject_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Subject not found")
    return {"status": "deleted", "subject_id": subject_id}
