"""提示词模板数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class PromptCategory(str, Enum):
    """提示词模板类别。"""

    IMAGE = "image"  # 图像生成提示词
    VIDEO = "video"  # 视频生成提示词
    SHOT = "shot"  # 镜头帧提示词
    SCRIPT = "script"  # 剧本/分镜提示词
    CHARACTER = "character"  # 角色描述提示词
    SCENE = "scene"  # 场景描述提示词


@dataclass
class PromptTemplate:
    """提示词模板。"""

    id: str
    name: str
    category: PromptCategory
    template: str  # 模板内容,支持 {variable} 插值
    description: str = ""
    variables: list[str] = field(default_factory=list)  # 模板变量列表
    default_values: dict[str, str] = field(default_factory=dict)  # 变量默认值
    is_default: bool = False  # 是否为该类别的默认模板
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def render(self, **kwargs: str) -> str:
        """渲染模板:用 kwargs 填充变量。"""
        # 合并默认值和传入值
        values = {**self.default_values, **kwargs}
        result = self.template
        for var in self.variables:
            placeholder = f"{{{var}}}"
            value = values.get(var, "")
            result = result.replace(placeholder, str(value))
        return result

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category.value,
            "template": self.template,
            "description": self.description,
            "variables": self.variables,
            "default_values": self.default_values,
            "is_default": self.is_default,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromptTemplate:
        return cls(
            id=data["id"],
            name=data["name"],
            category=PromptCategory(data["category"]),
            template=data["template"],
            description=data.get("description", ""),
            variables=data.get("variables", []),
            default_values=data.get("default_values", {}),
            is_default=data.get("is_default", False),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )
