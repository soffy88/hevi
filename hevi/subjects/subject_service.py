from __future__ import annotations

import uuid
from typing import Any

from hevi.subjects.reference_store import ReferenceStore
from hevi.subjects.repository import SUBJECT_KINDS, SubjectRepository


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
        }
        return await self._repo.create(data)

    async def get_subject(self, subject_id: str) -> dict[str, Any] | None:
        return await self._repo.get(subject_id)

    async def search_subjects(
        self,
        *,
        kind: str | None = None,
        query: str | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self._repo.list_subjects(
            kind=kind, query_text=query, user_id=user_id
        )

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
