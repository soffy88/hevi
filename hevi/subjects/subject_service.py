from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from hevi.subjects.reference_store import ReferenceStore
from hevi.subjects.repository import SUBJECT_KINDS, SubjectRepository

logger = logging.getLogger(__name__)


class SubjectService:
    def __init__(
        self,
        repo: SubjectRepository,
        ref_store: ReferenceStore | None = None,
    ) -> None:
        self._repo = repo
        self._ref_store = ref_store or ReferenceStore()

    async def create_subject(
        self,
        *,
        kind: str,
        name: str,
        reference_images: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        description: str = "",
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not name.strip():
            raise ValueError("name must not be empty")
        if kind not in SUBJECT_KINDS:
            raise ValueError(f"Invalid kind: {kind!r}. Valid: {sorted(SUBJECT_KINDS)}")

        refs = self._ref_store.validate_refs(reference_images or [])
        if reference_images is not None and len(refs) == 0:
            raise ValueError("reference_images must contain at least one non-empty path")

        subject_id = str(uuid.uuid4())
        data: dict[str, Any] = {
            "id": subject_id,
            "name": name.strip(),
            "description": description,
            "subject_type": kind,
            "reference_images": refs,
            "metadata": metadata or {},
            "tags": tags or [],
            "user_id": user_id,
            # 3O §C1:从首张参考图离线算身份向量(best-effort;失败为 None,不阻断建角色)。
            "identity_embedding": await self._compute_identity_embedding(refs),
        }
        return await self._repo.create(data)

    async def _compute_identity_embedding(self, refs: list[str]) -> list[float] | None:
        """首张参考图 → CLIP 身份向量。CPU + 重(模型加载),丢线程池避免阻塞事件循环。
        任何失败(无参考图/文件缺失/torch 缺)都降级为 None —— 身份向量是增强,非必需。"""
        if not refs:
            return None

        def _embed() -> list[float] | None:
            from hevi.subjects.subject_embed import SubjectEmbedError, subject_embed

            try:
                return subject_embed(image_path=refs[0], kind="face")
            except SubjectEmbedError as e:
                logger.warning("identity_embedding skipped: %s", e)
                return None

        try:
            return await asyncio.to_thread(_embed)
        except Exception as e:  # 线程池/导入等意外,仍不阻断建角色
            logger.warning("identity_embedding thread failed: %s", e)
            return None

    async def add_reference_upload(
        self, subject_id: str, *, filename: str, data: bytes
    ) -> dict[str, Any] | None:
        """上传一张照片作为该角色的参考图:落盘 + 追加到 reference_images。

        返回更新后的 subject(不存在返回 None)。这是"上传照片 → 角色"的落地点;
        存下的路径随后可被生成链路作为 i2v 参考图锁定角色身份。
        """
        existing = await self._repo.get(subject_id)
        if existing is None:
            return None
        if not data:
            raise ValueError("empty upload")
        path = self._ref_store.save_upload(subject_id, filename, data)
        refs = list(existing.get("reference_images") or [])
        if path not in refs:
            refs.append(path)
        return await self._repo.update(subject_id, {"reference_images": refs})

    async def get_subject(self, subject_id: str) -> dict[str, Any] | None:
        return await self._repo.get(subject_id)

    async def search_subjects(
        self,
        *,
        kind: str | None = None,
        query: str | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self._repo.list_subjects(kind=kind, query_text=query, user_id=user_id)

    async def update_subject_metadata(
        self,
        subject_id: str,
        *,
        metadata: dict[str, Any],
    ) -> dict[str, Any] | None:
        existing = await self._repo.get(subject_id)
        if existing is None:
            return None
        merged = {**existing.get("metadata", {}), **metadata}
        return await self._repo.update(subject_id, {"metadata": merged})

    async def delete_subject(self, subject_id: str) -> bool:
        return await self._repo.soft_delete(subject_id)
