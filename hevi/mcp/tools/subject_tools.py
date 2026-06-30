"""MCP tools: subject_create, subject_search — wraps P11.A SubjectService."""

from __future__ import annotations

from typing import Any

from obase.mcp_server import SkillDef
from obase.persistence import PgPool

from hevi.core.config import settings
from hevi.mcp.schemas import (
    SUBJECT_CREATE_INPUT,
    SUBJECT_CREATE_OUTPUT,
    SUBJECT_SEARCH_INPUT,
    SUBJECT_SEARCH_OUTPUT,
)
from hevi.subjects.repository import SubjectRepository
from hevi.subjects.subject_service import SubjectService


def build_subject_skills(subject_svc: SubjectService | None = None) -> list[SkillDef]:
    async def _get_svc() -> SubjectService:
        if subject_svc is not None:
            return subject_svc
        pool = await PgPool.get_or_create(dsn=settings.database_url)
        return SubjectService(SubjectRepository(pool))

    async def _create(args: dict[str, Any]) -> dict[str, Any]:
        svc = await _get_svc()
        return await svc.create_subject(
            name=args["name"],
            kind=args["kind"],
            description=args.get("description", ""),
            reference_images=args.get("reference_images"),
            user_id=args.get("user_id"),
        )

    async def _search(args: dict[str, Any]) -> dict[str, Any]:
        svc = await _get_svc()
        results = await svc.search_subjects(
            kind=args.get("kind"),
            query=args.get("query"),
            user_id=args.get("user_id"),
        )
        return {"subjects": results, "count": len(results)}

    return [
        SkillDef(
            name="hevi.subject_create",
            description="AI管理主体库：创建角色/人物/产品/场景主体",
            input_schema=SUBJECT_CREATE_INPUT,
            output_schema=SUBJECT_CREATE_OUTPUT,
            handler=_create,
        ),
        SkillDef(
            name="hevi.subject_search",
            description="AI管理主体库：按类型/关键词搜索主体",
            input_schema=SUBJECT_SEARCH_INPUT,
            output_schema=SUBJECT_SEARCH_OUTPUT,
            handler=_search,
        ),
    ]
