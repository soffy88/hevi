"""StoryGraph API - 原著导入与事件图谱管理。

端点:
- POST /api/storygraph/extract - 从长文提取 StoryGraph (自动切章)
- GET /api/storygraph - 列出所有 StoryGraph
- GET /api/storygraph/{id} - 获取 StoryGraph 详情
- DELETE /api/storygraph/{id} - 删除 StoryGraph
- POST /api/storygraph/{id}/chapters - 追加章节
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from hevi.api.dependencies import get_db_session
from hevi.storygraph.chapter_splitter import (
    merge_chapters_to_story_graph,
    split_text_to_chapters,
)
from hevi.storygraph.extract import extract_story_graph
from hevi.storygraph.repository import StoryGraphRepository
from hevi.storygraph.schemas import StoryGraph

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/storygraph", tags=["storygraph"])


# ── Request/Response schemas ─────────────────────────────────────────────────


class ExtractRequest(BaseModel):
    """长文提取请求。"""

    source_name: str = Field(..., description="来源名称 (小说标题/剧本名)")
    text: str = Field(..., description="原文文本", min_length=10)
    created_by: str | None = Field(default=None, description="创建者 ID")


class ExtractResponse(BaseModel):
    """提取响应。"""

    id: int
    source_name: str
    chapter_count: int
    total_char_count: int
    chapter_ids: list[str]
    character_count: int
    event_count: int


class StoryGraphSummary(BaseModel):
    """StoryGraph 摘要 (列表用)。"""

    id: int
    source_name: str
    chapter_count: int
    total_char_count: int
    chapter_ids: list[str]
    created_at: str
    updated_at: str
    created_by: str | None


class StoryGraphDetail(BaseModel):
    """StoryGraph 详情 (含完整 graph_json)。"""

    id: int
    source_name: str
    chapter_count: int
    total_char_count: int
    chapter_ids: list[str]
    created_at: str
    updated_at: str
    created_by: str | None
    graph: dict[str, Any]


class AppendChaptersRequest(BaseModel):
    """追加章节请求。"""

    text: str = Field(..., description="新增章节文本", min_length=10)


# ── 端点实现 ─────────────────────────────────────────────────────────────────


@router.post("/extract", response_model=ExtractResponse, status_code=201)
async def extract_storygraph(
    request: ExtractRequest,
    db: AsyncSession = Depends(get_db_session),
) -> ExtractResponse:
    """从长文提取 StoryGraph。

    流程:
    1. 切章 (split_text_to_chapters)
    2. 逐章提取 StoryGraph (extract_story_graph)
    3. 合并为单一 StoryGraph (merge_chapters_to_story_graph)
    4. 持久化到数据库
    """
    logger.info(f"Extracting StoryGraph from '{request.source_name}' ({len(request.text)} chars)")

    # 1. 切章
    chapters = split_text_to_chapters(request.text, source_name=request.source_name)
    logger.info(f"Split into {len(chapters)} chapters")

    # 2. 逐章提取
    chapter_graphs: list[StoryGraph] = []
    for i, chapter in enumerate(chapters):
        try:
            graph = await extract_story_graph(
                source_name=f"{request.source_name} - {chapter.title}",
                raw_text=chapter.content,
                llm=None,  # 使用默认 LLM
            )
            chapter_graphs.append(graph)
            logger.info(f"Extracted chapter {i+1}/{len(chapters)}: {chapter.title}")
        except Exception as e:
            logger.error(f"Failed to extract chapter {i+1}: {e}")
            # 继续提取其他章节,不中断

    if not chapter_graphs:
        raise HTTPException(status_code=500, detail="所有章节提取失败")

    # 3. 合并
    merged_graph = merge_chapters_to_story_graph(
        chapters=chapters,
        chapter_graphs=chapter_graphs,
        source_name=request.source_name,
    )

    # 4. 持久化
    repo = StoryGraphRepository(db)
    record = await repo.save(
        source_name=request.source_name,
        graph=merged_graph,
        chapter_ids=[ch.chapter_id for ch in chapters],
        created_by=request.created_by,
    )

    logger.info(
        f"StoryGraph saved: id={record.id}, "
        f"{len(merged_graph.characters)} characters, "
        f"{len(merged_graph.events)} events"
    )

    return ExtractResponse(
        id=record.id,
        source_name=record.source_name,
        chapter_count=record.chapter_count,
        total_char_count=record.total_char_count,
        chapter_ids=record.chapter_ids,
        character_count=len(merged_graph.characters),
        event_count=len(merged_graph.events),
    )


@router.get("", response_model=list[StoryGraphSummary])
async def list_storygraphs(
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db_session),
) -> list[StoryGraphSummary]:
    """列出所有 StoryGraph (摘要)。"""
    repo = StoryGraphRepository(db)
    records = await repo.list_all(limit=limit, offset=offset)

    return [
        StoryGraphSummary(
            id=r.id,
            source_name=r.source_name,
            chapter_count=r.chapter_count,
            total_char_count=r.total_char_count,
            chapter_ids=r.chapter_ids,
            created_at=r.created_at.isoformat() if r.created_at else "",
            updated_at=r.updated_at.isoformat() if r.updated_at else "",
            created_by=r.created_by,
        )
        for r in records
    ]


@router.get("/{record_id}", response_model=StoryGraphDetail)
async def get_storygraph(
    record_id: int,
    db: AsyncSession = Depends(get_db_session),
) -> StoryGraphDetail:
    """获取 StoryGraph 详情 (含完整 graph_json)。"""
    repo = StoryGraphRepository(db)
    record = await repo.load(record_id)

    if not record:
        raise HTTPException(status_code=404, detail=f"StoryGraph {record_id} not found")

    return StoryGraphDetail(
        id=record.id,
        source_name=record.source_name,
        chapter_count=record.chapter_count,
        total_char_count=record.total_char_count,
        chapter_ids=record.chapter_ids,
        created_at=record.created_at.isoformat() if record.created_at else "",
        updated_at=record.updated_at.isoformat() if record.updated_at else "",
        created_by=record.created_by,
        graph=record.graph_json,
    )


@router.delete("/{record_id}", status_code=204)
async def delete_storygraph(
    record_id: int,
    db: AsyncSession = Depends(get_db_session),
) -> None:
    """删除 StoryGraph。"""
    repo = StoryGraphRepository(db)
    deleted = await repo.delete(record_id)

    if not deleted:
        raise HTTPException(status_code=404, detail=f"StoryGraph {record_id} not found")

    logger.info(f"Deleted StoryGraph: id={record_id}")


@router.post("/{record_id}/chapters", response_model=ExtractResponse)
async def append_chapters(
    record_id: int,
    request: AppendChaptersRequest,
    db: AsyncSession = Depends(get_db_session),
) -> ExtractResponse:
    """向现有 StoryGraph 追加章节。

    流程:
    1. 加载现有 StoryGraph
    2. 切分新文本为章节
    3. 逐章提取 StoryGraph
    4. 合并新旧 StoryGraph
    5. 更新数据库
    """
    repo = StoryGraphRepository(db)
    existing = await repo.load(record_id)

    if not existing:
        raise HTTPException(status_code=404, detail=f"StoryGraph {record_id} not found")

    # 反序列化现有 graph
    existing_graph = StoryGraph.model_validate(existing.graph_json)

    # 切分新文本
    new_chapters = split_text_to_chapters(request.text, source_name=existing.source_name)
    logger.info(f"Appending {len(new_chapters)} chapters to StoryGraph {record_id}")

    # 逐章提取
    new_graphs: list[StoryGraph] = []
    for i, chapter in enumerate(new_chapters):
        try:
            graph = await extract_story_graph(
                source_name=f"{existing.source_name} - {chapter.title}",
                raw_text=chapter.content,
                llm=None,
            )
            new_graphs.append(graph)
        except Exception as e:
            logger.error(f"Failed to extract new chapter {i+1}: {e}")

    if not new_graphs:
        raise HTTPException(status_code=500, detail="新章节提取失败")

    # 合并
    all_chapters = [
        # 现有章节 (从 chapter_ids 重建,这里简化处理)
    ] + new_chapters

    all_graphs = [existing_graph] + new_graphs

    merged_graph = merge_chapters_to_story_graph(
        chapters=all_chapters,
        chapter_graphs=all_graphs,
        source_name=existing.source_name,
    )

    # 更新
    new_chapter_ids = [ch.chapter_id for ch in new_chapters]
    record = await repo.append_chapters(
        record_id=record_id,
        merged_graph=merged_graph,
        new_chapter_ids=new_chapter_ids,
    )

    return ExtractResponse(
        id=record.id,
        source_name=record.source_name,
        chapter_count=record.chapter_count,
        total_char_count=record.total_char_count,
        chapter_ids=record.chapter_ids,
        character_count=len(merged_graph.characters),
        event_count=len(merged_graph.events),
    )
