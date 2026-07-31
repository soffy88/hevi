"""资产管理服务。

提供道具和服装的 CRUD + 名称唯一性检查 + 跨镜头关联。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from hevi.assets.models import Costume, Prop

logger = logging.getLogger(__name__)


class AssetService:
    """道具/服装资产管理。

    内存存储,生产环境可换 DB。
    """

    def __init__(self) -> None:
        self._props: dict[str, Prop] = {}
        self._costumes: dict[str, Costume] = {}

    # ── 道具 CRUD ────────────────────────────────────────────────────────

    def create_prop(
        self,
        *,
        name: str,
        description: str = "",
        visual_features: str = "",
        image_path: str | None = None,
        category: str = "",
        era: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Prop:
        if self.get_prop_by_name(name) is not None:
            raise ValueError(f"道具名称已存在: {name}")
        prop = Prop(
            id=f"prop_{uuid.uuid4().hex[:8]}",
            name=name,
            description=description,
            visual_features=visual_features,
            image_path=image_path,
            category=category,
            era=era,
            metadata=metadata or {},
        )
        self._props[prop.id] = prop
        logger.info("Created prop: %s (%s)", name, prop.id)
        return prop

    def get_prop(self, prop_id: str) -> Prop | None:
        return self._props.get(prop_id)

    def get_prop_by_name(self, name: str) -> Prop | None:
        for p in self._props.values():
            if p.name == name:
                return p
        return None

    def list_props(self) -> list[Prop]:
        return list(self._props.values())

    def update_prop(self, prop_id: str, **kwargs: Any) -> Prop | None:
        prop = self._props.get(prop_id)
        if prop is None:
            return None
        # 名称唯一性检查
        new_name = kwargs.get("name")
        if new_name and new_name != prop.name:
            existing = self.get_prop_by_name(new_name)
            if existing is not None:
                raise ValueError(f"道具名称已存在: {new_name}")
        for k, v in kwargs.items():
            if hasattr(prop, k):
                setattr(prop, k, v)
        return prop

    def delete_prop(self, prop_id: str) -> bool:
        if prop_id in self._props:
            del self._props[prop_id]
            return True
        return False

    def link_prop_to_shot(self, prop_id: str, shot_id: str) -> bool:
        prop = self._props.get(prop_id)
        if prop is None:
            return False
        if shot_id not in prop.shot_ids:
            prop.shot_ids.append(shot_id)
        return True

    # ── 服装 CRUD ────────────────────────────────────────────────────────

    def create_costume(
        self,
        *,
        name: str,
        character_name: str,
        description: str = "",
        visual_features: str = "",
        image_path: str | None = None,
        style: str = "",
        era: str = "",
        color_palette: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Costume:
        if self.get_costume_by_name(name) is not None:
            raise ValueError(f"服装名称已存在: {name}")
        costume = Costume(
            id=f"costume_{uuid.uuid4().hex[:8]}",
            name=name,
            character_name=character_name,
            description=description,
            visual_features=visual_features,
            image_path=image_path,
            style=style,
            era=era,
            color_palette=color_palette or [],
            metadata=metadata or {},
        )
        self._costumes[costume.id] = costume
        logger.info("Created costume: %s for %s (%s)", name, character_name, costume.id)
        return costume

    def get_costume(self, costume_id: str) -> Costume | None:
        return self._costumes.get(costume_id)

    def get_costume_by_name(self, name: str) -> Costume | None:
        for c in self._costumes.values():
            if c.name == name:
                return c
        return None

    def list_costumes(self, character_name: str | None = None) -> list[Costume]:
        costumes = list(self._costumes.values())
        if character_name:
            costumes = [c for c in costumes if c.character_name == character_name]
        return costumes

    def update_costume(self, costume_id: str, **kwargs: Any) -> Costume | None:
        costume = self._costumes.get(costume_id)
        if costume is None:
            return None
        new_name = kwargs.get("name")
        if new_name and new_name != costume.name:
            existing = self.get_costume_by_name(new_name)
            if existing is not None:
                raise ValueError(f"服装名称已存在: {new_name}")
        for k, v in kwargs.items():
            if hasattr(costume, k):
                setattr(costume, k, v)
        return costume

    def delete_costume(self, costume_id: str) -> bool:
        if costume_id in self._costumes:
            del self._costumes[costume_id]
            return True
        return False

    def link_costume_to_shot(self, costume_id: str, shot_id: str) -> bool:
        costume = self._costumes.get(costume_id)
        if costume is None:
            return False
        if shot_id not in costume.shot_ids:
            costume.shot_ids.append(shot_id)
        return True

    # ── 统计 ─────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, int]:
        return {
            "total_props": len(self._props),
            "total_costumes": len(self._costumes),
        }
