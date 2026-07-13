from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path
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
        subject_metadata = dict(metadata or {})
        ip_flags = await self._screen_new_uploads(refs)
        if ip_flags:
            subject_metadata["ip_safety_flags"] = ip_flags

        data: dict[str, Any] = {
            "id": subject_id,
            "name": name.strip(),
            "description": description,
            "subject_type": kind,
            "reference_images": refs,
            "metadata": subject_metadata,
            "tags": tags or [],
            "user_id": user_id,
        }
        # 3O §C1 + 多区域(#34):从参考图离线算全图/脸部两份身份向量
        # (best-effort;失败为 None,不阻断建角色)。
        (
            data["identity_embedding"],
            data["identity_embedding_face"],
        ) = await self._compute_identity_embeddings(refs)
        return await self._repo.create(data)

    # 平均前 N 张参考图的向量(L2 重归一化)—— 多角度参考图本该让识别更稳,此前
    # 永远只用建号时那一张、之后加图从不重算。取前 5 张封顶,避免角色攒几十张图后
    # 每次改动都线性变慢。
    _MAX_EMBED_REFS = 5

    async def _compute_identity_embeddings(
        self, refs: list[str]
    ) -> tuple[list[float] | None, list[float] | None]:
        """参考图(可多张)→ (全图向量, 脸部区域向量),各自平均后 L2 归一化。

        多区域(HEVI 路线图 Phase2 #34):全图(kind="style")和脸部区域(kind="face",
        几何裁剪启发式)分开算分开存——不是拿一份向量硬扛所有比对场景。CPU + 重
        (模型加载),丢线程池避免阻塞事件循环。任何失败(无参考图/文件缺失/torch
        缺)都降级为 None —— 身份向量是增强,非必需。
        """
        if not refs:
            return None, None
        sample = refs[: self._MAX_EMBED_REFS]

        def _mean_unit(vecs: list[list[float]]) -> list[float] | None:
            import math

            if not vecs:
                return None
            dim = len(vecs[0])
            mean = [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]
            norm = math.sqrt(sum(x * x for x in mean))
            return [x / norm for x in mean] if norm != 0.0 else None

        def _embed_all() -> tuple[list[float] | None, list[float] | None]:
            from hevi.subjects.subject_embed import SubjectEmbedError, subject_embed

            whole_vecs: list[list[float]] = []
            face_vecs: list[list[float]] = []
            for p in sample:
                try:
                    whole_vecs.append(subject_embed(image_path=p, kind="style"))
                except SubjectEmbedError as e:
                    logger.warning("identity_embedding: skip %s: %s", p, e)
                try:
                    face_vecs.append(subject_embed(image_path=p, kind="face"))
                except SubjectEmbedError as e:
                    logger.warning("identity_embedding_face: skip %s: %s", p, e)
            return _mean_unit(whole_vecs), _mean_unit(face_vecs)

        try:
            # 20s 硬顶:CLIP 模型首次加载若命中 transformers 联网校验(HEAD 请求),
            # 在没有公网出口的容器里会无限重试挂起——2026-07-12 真实撞见:某次短剧
            # 派发卡在 DISPATCHING 半小时不动,root cause 是这里挂死,不是任何"进度
            # 显示"的问题。有超时兜底,才对得起上面这句"任何失败都降级为 None"的
            # 设计意图(之前这句话只是文档,没有真的做到)。
            return await asyncio.wait_for(asyncio.to_thread(_embed_all), timeout=20.0)
        except TimeoutError:
            logger.warning("identity_embedding timed out after 20s (CLIP 模型不可达?),降级为 None")
            return None, None
        except Exception as e:  # 线程池/导入等意外,仍不阻断建角色
            logger.warning("identity_embedding thread failed: %s", e)
            return None, None

    async def _screen_new_uploads(self, paths: list[str]) -> list[str]:
        """IP 安全 pass 的图像半边(HEVI 路线图 Phase2 #36):新上传的参考图逐张过一遍
        "像不像具体的公众人物/版权角色"的粗粒度 VLM 检查——只标记,不阻断上传/建号
        (见 hevi/subjects/ip_screening.py 的设计说明)。本地 VL 模型不可用时静默跳过。
        """
        if not paths:
            return []
        try:
            from hevi.providers.local_qwen_vl_adapter import (
                local_qwen_vl_adapter,
                vl_model_available,
            )

            vlm = local_qwen_vl_adapter if vl_model_available() else None
        except Exception as e:
            logger.warning("ip_screening: local VL adapter unavailable: %s", e)
            vlm = None
        if vlm is None:
            return []

        from hevi.subjects.ip_screening import flag_if_recognizable_person

        flags: list[str] = []
        for p in paths:
            flags.extend(await flag_if_recognizable_person(p, vlm=vlm))
        return flags

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
        new_paths = [] if path in refs else [path]
        if new_paths:
            refs.append(path)
        whole, face = await self._compute_identity_embeddings(refs)
        update: dict[str, Any] = {
            "reference_images": refs,
            "identity_embedding": whole,
            "identity_embedding_face": face,
        }
        ip_flags = await self._screen_new_uploads(new_paths)
        if ip_flags:
            update["metadata"] = {
                **existing.get("metadata", {}),
                "ip_safety_flags": [
                    *existing.get("metadata", {}).get("ip_safety_flags", []),
                    *ip_flags,
                ],
            }
        return await self._repo.update(subject_id, update)

    async def add_reference_uploads(
        self, subject_id: str, *, files: list[tuple[str, bytes]]
    ) -> dict[str, Any] | None:
        """一次上传多张参考图(批量,替代逐张调用 add_reference_upload)。全部落盘追加后
        只重算一次身份向量(而非每张图都重算一遍)。"""
        existing = await self._repo.get(subject_id)
        if existing is None:
            return None
        refs = list(existing.get("reference_images") or [])
        new_paths: list[str] = []
        for filename, data in files:
            if not data:
                continue
            path = self._ref_store.save_upload(subject_id, filename, data)
            if path not in refs:
                refs.append(path)
                new_paths.append(path)
        whole, face = await self._compute_identity_embeddings(refs)
        update: dict[str, Any] = {
            "reference_images": refs,
            "identity_embedding": whole,
            "identity_embedding_face": face,
        }
        ip_flags = await self._screen_new_uploads(new_paths)
        if ip_flags:
            update["metadata"] = {
                **existing.get("metadata", {}),
                "ip_safety_flags": [
                    *existing.get("metadata", {}).get("ip_safety_flags", []),
                    *ip_flags,
                ],
            }
        return await self._repo.update(subject_id, update)

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
        whole, face = await self._compute_identity_embeddings(refs)
        return await self._repo.update(
            subject_id,
            {
                "reference_images": refs,
                "identity_embedding": whole,
                "identity_embedding_face": face,
            },
        )

    async def set_reference_role(
        self, subject_id: str, *, path: str, role: str
    ) -> dict[str, Any] | None:
        """给某张参考图打正交角色标签(设计文档 §5.2)——跟 subject_type 无关的另一个维度:
        同一张图可能是"身份锚点"(identity_anchor,驱动 i2v 锁脸/身份向量的那张),也
        可能只是"构图/氛围参考"(composition_ref,不代表这个人长什么样,只是想要类似
        取景)。角色值不强制枚举,常见的是 identity_anchor / composition_ref。

        不改变 reference_images 本身的顺序或 [0]-是-封面 的既定行为——纯标注,不影响
        任何现有下游消费方。path 必须是该角色当前 reference_images 里的一项。
        """
        existing = await self._repo.get(subject_id)
        if existing is None:
            return None
        if path not in (existing.get("reference_images") or []):
            raise ValueError(f"{path!r} is not a reference image of this subject")
        if not role.strip():
            raise ValueError("role must not be empty")
        roles = dict(existing.get("reference_roles") or {})
        roles[path] = role.strip()
        return await self._repo.update(subject_id, {"reference_roles": roles})

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

    async def generate_subject3d(
        self, subject_id: str, *, output_root: str = "output/subject3d"
    ) -> dict[str, Any] | None:
        """本地 Subject3D 生成(HEVI-ARCHITECTURE.md v3.0 §5.7 主路A,2026-07-13 探路,
        见 subject3d_local.py 模块顶部的真实质量特征说明)。用 reference_images[0](跟
        身份向量、下游 i2v 锁脸同一张"封面"图,既定约定)当输入,存进
        metadata.subject3d = {glb_path, views: {front/left/right/back: path}}。

        不影响 reference_images/identity_embedding 这条既有 2D 通道——3D 是并行的
        补充档,不是替换(同一角色可以同时有 2D 参考图和 3D 渲染帧)。
        """
        existing = await self._repo.get(subject_id)
        if existing is None:
            return None
        refs = existing.get("reference_images") or []
        if not refs:
            raise ValueError("subject 没有 reference_images,无法生成 Subject3D")

        from hevi.subjects.subject3d_local import generate_subject3d as _generate

        result = await _generate(Path(refs[0]), output_dir=Path(output_root) / subject_id)
        metadata = dict(existing.get("metadata", {}))
        metadata["subject3d"] = result
        return await self._repo.update(subject_id, {"metadata": metadata})

    async def delete_subject(self, subject_id: str) -> bool:
        return await self._repo.soft_delete(subject_id)
