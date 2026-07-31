"""StoryGraph 数据库模型 - 持久化存储故事图谱。

支持:
- 长篇导入:多章合并存储
- 增量更新:按章节追加
- 查询:按 source_name / chapter_id 检索
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from hevi.db.base import Base


class StoryGraphRecord(Base):
    """StoryGraph 持久化记录。

    每个 StoryGraphRecord 对应一个来源(小说/剧本),
    graph_json 存储完整的 StoryGraph (可能包含多章合并结果)。
    """

    __tablename__ = "story_graphs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, comment="来源名称(小说标题/剧本名)"
    )
    graph_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, comment="完整 StoryGraph (Pydantic model_dump)"
    )
    chapter_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="章节数(0 = 单章或整文)"
    )
    chapter_ids: Mapped[list[str]] = mapped_column(
        JSON, default=list, comment="章节 ID 列表 (用于增量追加)"
    )
    total_char_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="总字符数"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间"
    )
    created_by: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="创建者 (user_id 或 system)"
    )

    def to_summary(self) -> dict[str, Any]:
        """返回摘要信息(不含完整 graph_json,用于列表查询)。"""
        return {
            "id": self.id,
            "source_name": self.source_name,
            "chapter_count": self.chapter_count,
            "total_char_count": self.total_char_count,
            "chapter_ids": self.chapter_ids,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "created_by": self.created_by,
        }
