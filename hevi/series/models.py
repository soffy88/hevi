"""Series 资产模型(设计 §3 L2 核心)—— "第 N 集"的载体。

Series = {角色组引用, StylePack@版本, 规格锁(档位/画幅/provider), 片头尾模板, 集数}。
做第 N 集 = 继承全部 + 只写新剧情 → 风格/角色/规格跨集不漂移。迁移成本即护城河。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from hevi.db.base import Base


class Series(Base):
    __tablename__ = "series"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # 角色组:subject id 列表(每集以其做 i2v 锁定身份)。
    subject_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # 风格:引用内置/用户 StylePack 名 + 版本(每集同一 StylePack@version = 风格不漂移)。
    style_preset: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    style_pack_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 规格锁:{duration_archetype, video_provider, audio_provider, num_characters, quality_profile,
    #         prompt_* 等} —— 每集继承,保证画幅/时长档/provider 一致。
    spec_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    intro_template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outro_template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    episode_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
