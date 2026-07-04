"""StylePackService —— fork 内置预设 + 覆盖 + 版本化 + resolve 成最终风格 dict。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from obase.persistence import PgPool, insert_one, query, read_one, update_one

from hevi.prompt.style_presets import STYLE_PRESETS, get_style_preset

_STYLE_KEYS = ("style", "lighting", "camera", "color_grade", "negative")


class StylePackRepository:
    def __init__(self, pool: PgPool) -> None:
        self.pool = pool

    async def create(self, data: dict[str, Any]) -> dict[str, Any]:
        data.setdefault("id", uuid.uuid4())
        now = datetime.now(UTC).replace(tzinfo=None)
        data.setdefault("created_at", now)
        data.setdefault("updated_at", now)
        new_id = await insert_one(self.pool, table="style_packs", data=data)
        return (await self.get(str(new_id))) or data

    async def get(self, pack_id: str) -> dict[str, Any] | None:
        r: dict[str, Any] | None = await read_one(
            self.pool, table="style_packs", id=uuid.UUID(pack_id)
        )
        if r is not None and r.get("deleted_at") is not None:
            return None
        return r

    async def update(self, pack_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
        updates["updated_at"] = datetime.now(UTC).replace(tzinfo=None)
        await update_one(self.pool, table="style_packs", id=uuid.UUID(pack_id), data=updates)
        return await self.get(pack_id)

    async def list_packs(self, *, user_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM style_packs WHERE deleted_at IS NULL"
        params: list[Any] = []
        if user_id:
            sql += " AND user_id = $1"
            params.append(user_id)
        return await query(self.pool, sql=sql + " ORDER BY created_at DESC", params=params or None)


def resolve_style(pack: dict[str, Any]) -> dict[str, Any]:
    """StylePack → 最终风格 dict = 内置预设 base 合并 overrides(只取风格键)。

    纯函数,不查库 —— 生成时用它把 StylePack 展开成 style/lighting/camera/color_grade/negative。
    """
    base = (
        dict(get_style_preset(pack["base_preset"]))
        if pack.get("base_preset") in STYLE_PRESETS
        else {}
    )
    overrides = {k: v for k, v in (pack.get("overrides_json") or {}).items() if k in _STYLE_KEYS}
    return {**base, **overrides}


class StylePackService:
    def __init__(self, repo: StylePackRepository) -> None:
        self._repo = repo

    async def create_pack(
        self,
        *,
        name: str,
        base_preset: str = "",
        overrides: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if not name.strip():
            raise ValueError("name must not be empty")
        if base_preset and base_preset not in STYLE_PRESETS:
            raise ValueError(f"unknown base preset: {base_preset!r}")
        overrides = {k: v for k, v in (overrides or {}).items() if k in _STYLE_KEYS}
        return await self._repo.create(
            {
                "name": name.strip(),
                "user_id": user_id,
                "base_preset": base_preset,
                "overrides_json": overrides,
                "version": 1,
            }
        )

    async def get_pack(self, pack_id: str) -> dict[str, Any] | None:
        return await self._repo.get(pack_id)

    async def resolve(self, pack_id: str) -> dict[str, Any]:
        pack = await self._repo.get(pack_id)
        if pack is None:
            raise ValueError(f"StylePack {pack_id} not found")
        return resolve_style(pack)

    async def update_overrides(
        self, pack_id: str, *, overrides: dict[str, Any]
    ) -> dict[str, Any] | None:
        """改风格 = 覆盖合并 + **版本 +1**(老集引用旧版本,不漂移)。"""
        pack = await self._repo.get(pack_id)
        if pack is None:
            raise ValueError(f"StylePack {pack_id} not found")
        merged = {
            **(pack.get("overrides_json") or {}),
            **{k: v for k, v in overrides.items() if k in _STYLE_KEYS},
        }
        return await self._repo.update(
            pack_id, {"overrides_json": merged, "version": int(pack.get("version", 1)) + 1}
        )
