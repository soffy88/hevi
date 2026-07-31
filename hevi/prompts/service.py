"""提示词模板管理服务。"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any

from hevi.prompts.models import PromptCategory, PromptTemplate

logger = logging.getLogger(__name__)

# 变量提取正则: {variable_name}
_VAR_PATTERN = re.compile(r"\{(\w+)\}")


def _extract_variables(template: str) -> list[str]:
    """从模板中提取 {variable} 变量名。"""
    return list(dict.fromkeys(_VAR_PATTERN.findall(template)))


class PromptTemplateService:
    """提示词模板管理。

    内存存储,生产环境可换 DB。
    内置一套默认模板,可通过 API 增删改。
    """

    def __init__(self) -> None:
        self._templates: dict[str, PromptTemplate] = {}
        self._defaults: dict[PromptCategory, str] = {}  # category → template_id
        self._load_builtins()

    def _load_builtins(self) -> None:
        """加载内置模板。"""
        builtins = [
            PromptTemplate(
                id="builtin_shot_frame",
                name="镜头帧提示词",
                category=PromptCategory.SHOT,
                template=(
                    "{shot_description}, "
                    "camera: {camera_movement}, "
                    "characters: {character_names}, "
                    "scene: {scene_description}, "
                    "style: {style_directive}, "
                    "cinematic lighting, high quality"
                ),
                description="标准镜头帧生成提示词",
                variables=[
                    "shot_description",
                    "camera_movement",
                    "character_names",
                    "scene_description",
                    "style_directive",
                ],
                default_values={"style_directive": "cinematic, realistic"},
                is_default=True,
            ),
            PromptTemplate(
                id="builtin_character_portrait",
                name="角色肖像提示词",
                category=PromptCategory.CHARACTER,
                template=(
                    "portrait of {character_name}, "
                    "{character_description}, "
                    "wearing {costume_description}, "
                    "era: {era}, "
                    "cinematic portrait, detailed face, high quality"
                ),
                description="角色肖像/定妆照生成提示词",
                variables=[
                    "character_name",
                    "character_description",
                    "costume_description",
                    "era",
                ],
                default_values={"era": "ancient china"},
                is_default=True,
            ),
            PromptTemplate(
                id="builtin_scene_plate",
                name="场景底图提示词",
                category=PromptCategory.SCENE,
                template=(
                    "{scene_name}, {scene_description}, "
                    "time: {time_of_day}, "
                    "weather: {weather}, "
                    "wide shot, establishing shot, cinematic"
                ),
                description="场景底图/环境生成提示词",
                variables=[
                    "scene_name",
                    "scene_description",
                    "time_of_day",
                    "weather",
                ],
                default_values={"time_of_day": "daytime", "weather": "clear"},
                is_default=True,
            ),
            PromptTemplate(
                id="builtin_video_prompt",
                name="视频生成提示词",
                category=PromptCategory.VIDEO,
                template=(
                    "{action_description}, "
                    "camera: {camera_movement}, "
                    "duration: {duration_s}s, "
                    "style: {style_directive}"
                ),
                description="视频生成提示词",
                variables=[
                    "action_description",
                    "camera_movement",
                    "duration_s",
                    "style_directive",
                ],
                is_default=True,
            ),
        ]
        for t in builtins:
            self._templates[t.id] = t
            if t.is_default:
                self._defaults[t.category] = t.id

    # ── CRUD ─────────────────────────────────────────────────────────────

    def create_template(
        self,
        *,
        name: str,
        category: PromptCategory,
        template: str,
        description: str = "",
        default_values: dict[str, str] | None = None,
        is_default: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> PromptTemplate:
        """创建模板。自动提取变量。"""
        variables = _extract_variables(template)
        tid = f"tmpl_{uuid.uuid4().hex[:8]}"
        now = datetime.now().isoformat()
        t = PromptTemplate(
            id=tid,
            name=name,
            category=category,
            template=template,
            description=description,
            variables=variables,
            default_values=default_values or {},
            is_default=is_default,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        self._templates[tid] = t
        if is_default:
            self._defaults[category] = tid
        logger.info("Created prompt template: %s (%s)", name, tid)
        return t

    def get_template(self, template_id: str) -> PromptTemplate | None:
        return self._templates.get(template_id)

    def get_default_template(self, category: PromptCategory) -> PromptTemplate | None:
        tid = self._defaults.get(category)
        if tid is None:
            return None
        return self._templates.get(tid)

    def list_templates(
        self, category: PromptCategory | None = None
    ) -> list[PromptTemplate]:
        templates = list(self._templates.values())
        if category:
            templates = [t for t in templates if t.category == category]
        return templates

    def update_template(self, template_id: str, **kwargs: Any) -> PromptTemplate | None:
        t = self._templates.get(template_id)
        if t is None:
            return None
        if "template" in kwargs:
            kwargs["variables"] = _extract_variables(kwargs["template"])
            t.template = kwargs["template"]
        for k, v in kwargs.items():
            if k == "template":
                continue
            if hasattr(t, k):
                setattr(t, k, v)
        t.updated_at = datetime.now().isoformat()
        if kwargs.get("is_default"):
            self._defaults[t.category] = template_id
        return t

    def delete_template(self, template_id: str) -> bool:
        t = self._templates.get(template_id)
        if t is None:
            return False
        # 不能删除内置模板
        if template_id.startswith("builtin_"):
            raise ValueError("Cannot delete built-in templates")
        if self._defaults.get(t.category) == template_id:
            del self._defaults[t.category]
        del self._templates[template_id]
        return True

    def render(self, template_id: str, **kwargs: str) -> str:
        """渲染指定模板。"""
        t = self._templates.get(template_id)
        if t is None:
            raise ValueError(f"Template not found: {template_id}")
        return t.render(**kwargs)

    def render_default(self, category: PromptCategory, **kwargs: str) -> str:
        """渲染指定类别的默认模板。"""
        t = self.get_default_template(category)
        if t is None:
            raise ValueError(f"No default template for category: {category.value}")
        return t.render(**kwargs)

    def stats(self) -> dict[str, Any]:
        by_category: dict[str, int] = {}
        for t in self._templates.values():
            by_category[t.category.value] = by_category.get(t.category.value, 0) + 1
        return {
            "total": len(self._templates),
            "by_category": by_category,
        }
