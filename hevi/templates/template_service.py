from __future__ import annotations

from typing import Any

from hevi.templates.template_repository import TemplateRepository


class TemplateService:
    def __init__(self, repo: TemplateRepository) -> None:
        self._repo = repo

    async def create_template(
        self,
        *,
        name: str,
        category: str,
        canvas_json: dict[str, Any],
        thumbnail: str | None = None,
        is_official: bool = False,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = {
            "name": name,
            "category": category,
            "canvas_json": canvas_json,
            "thumbnail": thumbnail,
            "is_official": is_official,
            "user_id": user_id,
            "metadata": metadata or {},
        }
        return await self._repo.create(data)

    async def get_template(self, template_id: str) -> dict[str, Any] | None:
        return await self._repo.get(template_id)

    async def list_templates(
        self,
        *,
        category: str | None = None,
        official_only: bool = False,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return await self._repo.list_templates(
            category=category, official_only=official_only, user_id=user_id
        )

    async def apply_template(self, template_id: str) -> dict[str, Any]:
        template = await self.get_template(template_id)
        if not template:
            raise ValueError(f"Template not found: {template_id}")
        
        # Returns canvas_json for initializing a new canvas
        return template["canvas_json"]  # type: ignore[no-any-return]

    async def delete_template(self, template_id: str) -> bool:
        return await self._repo.delete(template_id)
