"""道具和服装数据模型。

Prop: 道具资产
  - 名称唯一性(鼓励复用)
  - 描述/视觉特征(供 prompt 生成)
  - 图像路径
  - 关联镜头列表

Costume: 服装资产
  - 角色关联(哪个角色的哪套服装)
  - 服装描述(朝代/风格/颜色)
  - 图像路径
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Prop:
    """道具资产。"""

    id: str
    name: str
    description: str = ""
    visual_features: str = ""  # 视觉特征描述(供 prompt 生成)
    image_path: str | None = None
    category: str = ""  # 道具分类: 武器/文书/器皿/家具/自然物...
    era: str = ""  # 年代约束(战国/汉/唐...)
    shot_ids: list[str] = field(default_factory=list)  # 关联镜头
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "visual_features": self.visual_features,
            "image_path": self.image_path,
            "category": self.category,
            "era": self.era,
            "shot_ids": self.shot_ids,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Prop:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Costume:
    """服装资产。"""

    id: str
    name: str
    character_name: str  # 关联角色名
    description: str = ""
    visual_features: str = ""  # 视觉特征描述
    image_path: str | None = None
    style: str = ""  # 风格: 正式/便装/战斗/礼服
    era: str = ""  # 年代约束
    color_palette: list[str] = field(default_factory=list)  # 主色调
    shot_ids: list[str] = field(default_factory=list)  # 关联镜头
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "character_name": self.character_name,
            "description": self.description,
            "visual_features": self.visual_features,
            "image_path": self.image_path,
            "style": self.style,
            "era": self.era,
            "color_palette": self.color_palette,
            "shot_ids": self.shot_ids,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Costume:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
