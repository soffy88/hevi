from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from obase.persistence import PgPool, insert_one, query, update_one


class PresenterRepository:
    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        data.setdefault("id", uuid.uuid4())
        now = datetime.now(UTC).replace(tzinfo=None)
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        data.setdefault("delivery_json", {})
        presenter_id = await insert_one(self.pool, table="presenters", data=data, returning="id")
        return await self.get(str(presenter_id), str(data["user_id"])) or {}

    async def ensure_default(self, user_id: str) -> dict[str, Any]:
        """Return the user's first presenter or create a real local fallback.

        The generated presenter is rendered by HEVI's Remotion template and
        therefore does not pretend that an external avatar provider exists.
        """
        existing = await self.list(user_id)
        if existing:
            return existing[0]
        return await self.create(
            {
                "user_id": user_id,
                "name": "HEVI 默认解说数字人",
                "subject_id": None,
                "voice_profile_id": None,
                "performance": "presenter",
                "motion": "picture_in_picture",
                "lipsync": "none",
                "delivery_json": {
                    "provider": "remotion",
                    "variant": "generated",
                    "auto_created": True,
                },
                "description": "系统自动创建；无外部数字人 Provider 时使用本地动态出镜。",
            }
        )

    async def get(self, presenter_id: str, user_id: str) -> dict[str, Any] | None:
        rows = await query(
            self.pool,
            sql="SELECT * FROM presenters WHERE id = $1 AND user_id = $2",
            params=[uuid.UUID(presenter_id), user_id],
        )
        return rows[0] if rows else None

    async def list(self, user_id: str) -> list[dict[str, Any]]:
        return await query(
            self.pool,
            sql="SELECT * FROM presenters WHERE user_id = $1 ORDER BY created_at DESC",
            params=[user_id],
        )

    async def update(
        self, presenter_id: str, user_id: str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        data["updated_at"] = datetime.now(UTC).replace(tzinfo=None)
        row = await self.get(presenter_id, user_id)
        if row is None:
            return None
        await update_one(self.pool, table="presenters", id=uuid.UUID(presenter_id), data=data)
        return await self.get(presenter_id, user_id)
