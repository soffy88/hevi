"""Durable VideoCase repository with ownership and idempotency enforcement."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from obase.persistence import PgPool, insert_one, query, read_one

from .case_models import VideoCase


class CaseRepository:
    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    @staticmethod
    def _row(case: VideoCase) -> dict[str, Any]:
        now = datetime.now(UTC).replace(tzinfo=None)
        return {
            "id": uuid.UUID(case.id),
            "user_id": uuid.UUID(case.user_id),
            "title": case.title,
            "description": case.description,
            "source_url": case.source_url,
            "source_platform": case.source_platform,
            "source_author": case.source_author,
            "provenance_status": case.provenance_status.value,
            "provenance_json": [item.model_dump(mode="json") for item in case.provenance],
            "original_video_asset_id": uuid.UUID(case.original_video_asset_id) if case.original_video_asset_id else None,
            "thumbnail_asset_id": uuid.UUID(case.thumbnail_asset_id) if case.thumbnail_asset_id else None,
            "original_prompt": case.original_prompt,
            "prompt_origin": case.prompt_origin.value,
            "reference_assets_json": [item.model_dump(mode="json") for item in case.reference_assets],
            "duration_ms": case.duration_ms,
            "aspect_ratio": case.aspect_ratio,
            "fps": case.fps,
            "width": case.width,
            "height": case.height,
            "declared_model": case.declared_model,
            "declared_model_version": case.declared_model_version,
            "rights_status": case.rights_status.value,
            "rights_metadata": case.rights_metadata,
            "tags": case.tags,
            "analysis_status": case.analysis_status.value,
            "duplicate_outcome": case.duplicate_outcome.value,
            "exact_asset_sha256": case.exact_asset_sha256,
            "source_fingerprint": case.source_fingerprint,
            "shots_json": [item.model_dump(mode="json") for item in case.shots],
            "idempotency_key": None,
            "created_at": case.created_at.replace(tzinfo=None),
            "updated_at": now,
        }

    @staticmethod
    def _model(row: dict[str, Any]) -> VideoCase:
        payload = dict(row)
        payload["id"] = str(payload["id"])
        payload["user_id"] = str(payload["user_id"])
        payload["original_video_asset_id"] = str(payload["original_video_asset_id"]) if payload.get("original_video_asset_id") else None
        payload["thumbnail_asset_id"] = str(payload["thumbnail_asset_id"]) if payload.get("thumbnail_asset_id") else None
        payload["provenance"] = payload.pop("provenance_json", []) or []
        payload["reference_assets"] = payload.pop("reference_assets_json", []) or []
        payload["rights_metadata"] = payload.get("rights_metadata") or {}
        payload["tags"] = payload.get("tags") or []
        payload["shots"] = payload.pop("shots_json", []) or []
        payload.pop("idempotency_key", None)
        return VideoCase.model_validate(payload)

    async def get_owned(self, case_id: str, *, user_id: str) -> VideoCase | None:
        row = await read_one(self.pool, table="video_cases", id=uuid.UUID(case_id))
        if not row or str(row.get("user_id")) != str(uuid.UUID(user_id)):
            return None
        return self._model(row)

    async def find_idempotent(self, *, user_id: str, key: str) -> VideoCase | None:
        rows = await query(
            self.pool,
            sql="SELECT * FROM video_cases WHERE user_id = $1 AND idempotency_key = $2 LIMIT 1",
            params=[uuid.UUID(user_id), key],
        )
        return self._model(rows[0]) if rows else None

    async def find_exact_hash(self, *, user_id: str, sha256: str) -> VideoCase | None:
        rows = await query(
            self.pool,
            sql="SELECT * FROM video_cases WHERE user_id = $1 AND exact_asset_sha256 = $2 ORDER BY created_at ASC LIMIT 1",
            params=[uuid.UUID(user_id), sha256],
        )
        return self._model(rows[0]) if rows else None

    async def create(self, case: VideoCase, *, idempotency_key: str | None = None) -> VideoCase:
        if idempotency_key:
            existing = await self.find_idempotent(user_id=case.user_id, key=idempotency_key)
            if existing:
                return existing
        row = self._row(case)
        row["idempotency_key"] = idempotency_key
        case_id = await insert_one(self.pool, table="video_cases", data=row, returning="id")
        stored = await self.get_owned(str(case_id), user_id=case.user_id)
        if stored is None:
            raise RuntimeError("CASE_PERSISTENCE_FAILED")
        return stored

    async def list_owned(self, *, user_id: str, limit: int = 100) -> list[VideoCase]:
        rows = await query(
            self.pool,
            sql="SELECT * FROM video_cases WHERE user_id = $1 ORDER BY created_at DESC",
            params=[uuid.UUID(user_id)],
            limit=max(1, min(limit, 500)),
        )
        return [self._model(row) for row in rows]

    async def update_owned(
        self, case_id: str, *, user_id: str, changes: dict[str, Any]
    ) -> VideoCase | None:
        """Update only a row owned by ``user_id``.

        The owner predicate is deliberately in the SQL write, not only in a
        preceding read.  This makes the mutation fail closed under races and
        gives the ownership adversarial tests a real database boundary.
        """
        allowed = {
            "title", "description", "provenance_status", "provenance_json",
            "original_prompt", "prompt_origin", "reference_assets_json",
            "rights_status", "rights_metadata", "tags", "analysis_status",
            "shots_json", "duration_ms", "aspect_ratio", "fps", "width", "height",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unsupported video_cases columns: {sorted(unknown)}")
        if not changes:
            return await self.get_owned(case_id, user_id=user_id)
        params: list[Any] = []
        assignments: list[str] = []
        for column, value in changes.items():
            params.append(value)
            assignments.append(f'"{column}" = ${len(params)}')
        assignments.append("updated_at = NOW()")
        params.extend([uuid.UUID(case_id), uuid.UUID(user_id)])
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "UPDATE video_cases SET " + ", ".join(assignments)
                + f" WHERE id = ${len(params) - 1} AND user_id = ${len(params)} RETURNING *",
                *params,
            )
        return self._model(dict(row)) if row else None

    async def delete_owned(self, case_id: str, *, user_id: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM video_cases WHERE id = $1 AND user_id = $2",
                uuid.UUID(case_id), uuid.UUID(user_id),
            )
        return bool(result.endswith("1"))

    async def attach_provenance(
        self, case_id: str, *, user_id: str, provenance: list[dict[str, Any]]
    ) -> VideoCase | None:
        return await self.update_owned(
            case_id,
            user_id=user_id,
            changes={"provenance_json": provenance},
        )


__all__ = ["CaseRepository"]
