from __future__ import annotations

import asyncio
import logging
import os
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
        voice_store: ReferenceStore | None = None,
    ) -> None:
        self._repo = repo
        self._ref_store = ref_store or ReferenceStore()
        # 声音参考片段单独存(与身份参考图分区),复用同一套字节存储实现(ReferenceStore
        # 内部就是纯字节落盘,不区分文件类型 —— 只是路由到不同目录)。
        self._voice_store = voice_store or ReferenceStore(
            base_dir=os.getenv("HEVI_VOICE_REFERENCE_DIR", "output/voice_references")
        )

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

    # 平均前 N 张参考图的向量(L2 重归一化)—— 多角度参考图本该让识别更稳,此前
    # 永远只用建号时那一张、之后加图从不重算。取前 5 张封顶,避免角色攒几十张图后
    # 每次改动都线性变慢。
    _MAX_EMBED_REFS = 5

    async def _compute_identity_embedding(self, refs: list[str]) -> list[float] | None:
        """参考图(可多张)→ 平均后 L2 归一化的 CLIP 身份向量。CPU + 重(模型加载),
        丢线程池避免阻塞事件循环。任何失败(无参考图/文件缺失/torch 缺)都降级为
        None —— 身份向量是增强,非必需。"""
        if not refs:
            return None
        sample = refs[: self._MAX_EMBED_REFS]

        def _embed_all() -> list[float] | None:
            import math

            from hevi.subjects.subject_embed import SubjectEmbedError, subject_embed

            vecs: list[list[float]] = []
            for p in sample:
                try:
                    vecs.append(subject_embed(image_path=p, kind="face"))
                except SubjectEmbedError as e:
                    logger.warning("identity_embedding: skip %s: %s", p, e)
            if not vecs:
                return None
            dim = len(vecs[0])
            mean = [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]
            norm = math.sqrt(sum(x * x for x in mean))
            if norm == 0.0:
                return None
            return [x / norm for x in mean]

        try:
            return await asyncio.to_thread(_embed_all)
        except Exception as e:  # 线程池/导入等意外,仍不阻断建角色
            logger.warning("identity_embedding thread failed: %s", e)
            return None

    async def add_reference_upload(
        self, subject_id: str, *, filename: str, data: bytes
    ) -> dict[str, Any] | None:
        """上传一张照片作为该角色的参考图:落盘 + 追加到 reference_images + 重算身份向量
        (纳入新图,多角度更稳)。返回更新后的 subject(不存在返回 None)。
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
        embedding = await self._compute_identity_embedding(refs)
        return await self._repo.update(
            subject_id, {"reference_images": refs, "identity_embedding": embedding}
        )

    async def add_reference_uploads(
        self, subject_id: str, *, files: list[tuple[str, bytes]]
    ) -> dict[str, Any] | None:
        """一次上传多张参考图(批量,替代逐张调用 add_reference_upload)。全部落盘追加后
        只重算一次身份向量(而非每张图都重算一遍)。"""
        existing = await self._repo.get(subject_id)
        if existing is None:
            return None
        refs = list(existing.get("reference_images") or [])
        for filename, data in files:
            if not data:
                continue
            path = self._ref_store.save_upload(subject_id, filename, data)
            if path not in refs:
                refs.append(path)
        embedding = await self._compute_identity_embedding(refs)
        return await self._repo.update(
            subject_id, {"reference_images": refs, "identity_embedding": embedding}
        )

    async def update_references(
        self, subject_id: str, *, reference_images: list[str]
    ) -> dict[str, Any] | None:
        """整体替换参考图列表(前端算好的目标顺序/取舍)—— 覆盖"设封面"(把选中的图挪到
        第 0 位,下游锁脸/评分卡全用 reference_images[0])、删除(列表里去掉该项)、
        排序(给新顺序)三种操作,重算一次身份向量。"""
        existing = await self._repo.get(subject_id)
        if existing is None:
            return None
        refs = self._ref_store.validate_refs(reference_images)
        embedding = await self._compute_identity_embedding(refs)
        return await self._repo.update(
            subject_id, {"reference_images": refs, "identity_embedding": embedding}
        )

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

    async def update_subject_fields(
        self,
        subject_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """编辑角色的姓名/描述/标签(建号后仍可改 —— 此前只有 metadata 能改,基础字段
        没有编辑口子)。None 的字段不动;传空字符串会真的清空该字段。"""
        existing = await self._repo.get(subject_id)
        if existing is None:
            return None
        updates: dict[str, Any] = {}
        if name is not None:
            if not name.strip():
                raise ValueError("name must not be empty")
            updates["name"] = name.strip()
        if description is not None:
            updates["description"] = description
        if tags is not None:
            updates["tags"] = tags
        if not updates:
            return existing
        return await self._repo.update(subject_id, updates)

    async def add_voice_reference(
        self, subject_id: str, *, filename: str, data: bytes
    ) -> dict[str, Any] | None:
        """上传角色声音参考片段(几秒到十几秒人声)→ 存进 metadata.voice_ref。

        用于 VibeVoice 零样本声音克隆(hevi.pipeline.longvideo_orchestrator 的
        character_voices 映射读这个字段)——仅该引擎生效,edge_tts 不支持逐行换音色。
        """
        existing = await self._repo.get(subject_id)
        if existing is None:
            return None
        if not data:
            raise ValueError("empty upload")
        path = self._voice_store.save_upload(subject_id, filename, data)
        metadata = {**existing.get("metadata", {}), "voice_ref": path}
        return await self._repo.update(subject_id, {"metadata": metadata})

    async def add_wardrobe_upload(
        self, subject_id: str, *, filename: str, data: bytes
    ) -> dict[str, Any] | None:
        """上传造型/服装参考图 —— 与身份参考图(reference_images,驱动 i2v 锁脸 + 身份
        向量)分开管理,存进 metadata.wardrobe_images,不影响脸部锁定。"""
        existing = await self._repo.get(subject_id)
        if existing is None:
            return None
        if not data:
            raise ValueError("empty upload")
        path = self._ref_store.save_upload(subject_id, filename, data)
        metadata = dict(existing.get("metadata", {}))
        wardrobe = list(metadata.get("wardrobe_images") or [])
        if path not in wardrobe:
            wardrobe.append(path)
        metadata["wardrobe_images"] = wardrobe
        return await self._repo.update(subject_id, {"metadata": metadata})

    async def delete_subject(self, subject_id: str) -> bool:
        return await self._repo.soft_delete(subject_id)
