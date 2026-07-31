"""StoryGraph 仓储层 - CRUD 操作封装。

提供:
- save: 保存 StoryGraph
- load: 加载 StoryGraph
- list: 列表查询
- delete: 删除记录
- append_chapters: 增量追加章节
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from hevi.storygraph.models import StoryGraphRecord
from hevi.storygraph.schemas import StoryGraph

logger = logging.getLogger(__name__)


class StoryGraphRepository:
    """StoryGraph 仓储。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(
        self,
        source_name: str,
        graph: StoryGraph,
        chapter_ids: list[str] | None = None,
        created_by: str | None = None,
    ) -> StoryGraphRecord:
        """保存 StoryGraph。

        如果 source_name 已存在,则更新;否则新建。
        """
        graph_dict = graph.model_dump(mode="json")

        # 检查是否已存在
        stmt = select(StoryGraphRecord).where(StoryGraphRecord.source_name == source_name)
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # 更新
            existing.graph_json = graph_dict
            existing.chapter_count = len(chapter_ids) if chapter_ids else 0
            existing.chapter_ids = chapter_ids or []
            existing.total_char_count = graph.meta.char_count
            existing.updated_at = datetime.utcnow()
            await self._session.commit()
            await self._session.refresh(existing)
            logger.info(f"Updated StoryGraph: {source_name}")
            return existing
        else:
            # 新建
            record = StoryGraphRecord(
                source_name=source_name,
                graph_json=graph_dict,
                chapter_count=len(chapter_ids) if chapter_ids else 0,
                chapter_ids=chapter_ids or [],
                total_char_count=graph.meta.char_count,
                created_by=created_by,
            )
            self._session.add(record)
            await self._session.commit()
            await self._session.refresh(record)
            logger.info(f"Created StoryGraph: {source_name} (id={record.id})")
            return record

    async def load(self, record_id: int) -> StoryGraphRecord | None:
        """按 ID 加载 StoryGraphRecord。"""
        stmt = select(StoryGraphRecord).where(StoryGraphRecord.id == record_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def load_by_source(self, source_name: str) -> StoryGraphRecord | None:
        """按 source_name 加载 StoryGraphRecord。"""
        stmt = select(StoryGraphRecord).where(StoryGraphRecord.source_name == source_name)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def load_graph(self, record_id: int) -> StoryGraph | None:
        """加载并反序列化为 StoryGraph Pydantic 模型。"""
        record = await self.load(record_id)
        if not record:
            return None
        return StoryGraph.model_validate(record.graph_json)

    async def list_all(
        self, limit: int = 100, offset: int = 0
    ) -> list[StoryGraphRecord]:
        """列表查询(返回摘要,不含完整 graph_json)。"""
        stmt = (
            select(StoryGraphRecord)
            .order_by(StoryGraphRecord.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, record_id: int) -> bool:
        """删除 StoryGraphRecord。"""
        stmt = delete(StoryGraphRecord).where(StoryGraphRecord.id == record_id)
        result = await self._session.execute(stmt)
        await self._session.commit()
        deleted = result.rowcount > 0  # type: ignore[attr-defined]
        if deleted:
            logger.info(f"Deleted StoryGraph: id={record_id}")
        return deleted

    async def count(self) -> int:
        """统计总数。"""
        from sqlalchemy import func

        stmt = select(func.count(StoryGraphRecord.id))
        result = await self._session.execute(stmt)
        return result.scalar_one()

    async def append_chapters(
        self,
        record_id: int,
        merged_graph: StoryGraph,
        new_chapter_ids: list[str],
    ) -> StoryGraphRecord | None:
        """增量追加章节到现有 StoryGraph。

        Args:
            record_id: 现有记录 ID
            merged_graph: 合并后的完整 StoryGraph
            new_chapter_ids: 新增的章节 ID 列表
        """
        record = await self.load(record_id)
        if not record:
            return None

        # 更新
        record.graph_json = merged_graph.model_dump(mode="json")
        record.chapter_ids = list(set(record.chapter_ids + new_chapter_ids))
        record.chapter_count = len(record.chapter_ids)
        record.total_char_count = merged_graph.meta.char_count
        record.updated_at = datetime.utcnow()

        await self._session.commit()
        await self._session.refresh(record)
        logger.info(f"Appended {len(new_chapter_ids)} chapters to StoryGraph: id={record_id}")
        return record
