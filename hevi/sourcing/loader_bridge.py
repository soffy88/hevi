from __future__ import annotations

import uuid
from collections.abc import Callable
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
"""Bridge hevi's async asset store to oskill's synchronous asset_loader contract.

oskill.asset_reference_inject(*, shot_spec, asset_refs, asset_loader) calls
asset_loader(asset_type, asset_id) -> dict | None **synchronously**, but hevi's
assets live in async Postgres. So we pre-fetch all referenced assets (async),
then hand asset_reference_inject a sync dict-backed loader.

Typical usage at the injection boundary:

    asset_map = await load_asset_map(repo, asset_refs)
    loader = make_asset_loader(asset_map)
    enriched = asset_reference_inject(
        shot_spec=spec, asset_refs=asset_refs, asset_loader=loader
    )
"""


async def load_asset_map(
    repo: AssetRepository, asset_refs: dict[str, str]
) -> dict[tuple[str, str], dict[str, Any]]:
    """Pre-fetch every referenced asset, keyed by (ref_key, asset_id).

    asset_refs maps {character_id, scene_id, ...} -> asset-id. We key the map by
    the *ref key* (e.g. "character_id") because oskill.asset_reference_inject
    invokes asset_loader(key, asset_id) with that exact key. The asset's stored
    asset_type is verified against the key (trailing '_id' stripped) so a wrong
    type id won't resolve. Missing / deleted / type-mismatched refs are omitted.
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for key, asset_id in asset_refs.items():
        if not asset_id:
            continue
        asset_type = key[:-3] if key.endswith("_id") else key
        asset = await repo.get(asset_id)
        if asset is not None and asset.get("asset_type") == asset_type:
            out[(key, asset_id)] = asset
    return out


def make_asset_loader(
    asset_map: dict[tuple[str, str], dict[str, Any]],
) -> Callable[[str, str], dict[str, Any] | None]:
    """Return a sync loader over a pre-fetched asset map (E4 contract).

    The first arg is the ref key that asset_reference_inject passes through
    (e.g. "character_id"), matching how load_asset_map keys the map.
    """

    def _loader(ref_key: str, asset_id: str) -> dict[str, Any] | None:
        return asset_map.get((ref_key, asset_id))

    return _loader
