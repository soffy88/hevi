from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from obase.persistence import PgPool, insert_one, query, read_one, update_one

# E4 asset_refs taxonomy (oskill._asset_reference_inject._ASSET_KEYS).
ASSET_TYPES: frozenset[str] = frozenset({"character", "scene", "voice", "prop", "fx"})


class AssetRepository:
    def __init__(self, pool: PgPool) -> None:
        self._pool = pool

    async def create(
        self,
        *,
        asset_type: str,
        name: str,
        data: dict[str, Any] | None = None,
        user_id: str | None = None,
        is_official: bool = False,
    ) -> dict[str, Any]:
        if asset_type not in ASSET_TYPES:
            raise ValueError(f"Invalid asset_type: {asset_type!r}. Valid: {sorted(ASSET_TYPES)}")
        now = datetime.now(UTC).replace(tzinfo=None)
        row = {
            "id": uuid.uuid4(),
            "asset_type": asset_type,
            "name": name,
            "data": data or {},
            "user_id": user_id,
            "is_official": is_official,
            "created_at": now,
            "updated_at": now,
            "deleted_at": None,
        }
        new_id = await insert_one(self._pool, table="assets", data=row)
        return (await self.get(str(new_id))) or row

    async def get(self, asset_id: str) -> dict[str, Any] | None:
        result: dict[str, Any] | None = await read_one(
            self._pool, table="assets", id=uuid.UUID(asset_id)
        )
        if result is not None and result.get("deleted_at") is not None:
            return None
        return result

    async def list_for_user(
        self, *, user_id: str, asset_type: str | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        conditions = ["deleted_at IS NULL", "(is_official = TRUE OR user_id = $1)"]
        params: list[Any] = [user_id]
        if asset_type is not None:
            conditions.append(f"asset_type = ${len(params) + 1}")
            params.append(asset_type)
        where = " AND ".join(conditions)
        rows: list[dict[str, Any]] = await query(
            self._pool,
            sql=f"SELECT * FROM assets WHERE {where} ORDER BY created_at DESC",
            params=params,
            limit=limit,
        )
        return rows

    async def soft_delete(self, asset_id: str) -> bool:
        existing = await self.get(asset_id)
        if existing is None:
            return False
        ok: bool = await update_one(
            self._pool,
            table="assets",
            id=uuid.UUID(asset_id),
            data={"deleted_at": datetime.now(UTC).replace(tzinfo=None)},
        )
        return bool(ok)
