"""StylePack 资产模型(设计 §3 L2)—— 可实例化 + 版本化的风格。

20 个内置预设(`prompt.style_presets`)是静态 dict。StylePack 把它升级为**资产**:
  内置预设 fork + 用户覆盖(style/lighting/camera/color_grade/negative) + 版本号。
Series 每集引用同一 `StylePack@version` → 风格跨集不漂移(改风格 = 新版本,老集不受影响)。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from hevi.db.base import Base


class StylePack(Base):
    __tablename__ = "style_packs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    # fork 自哪个内置预设(prompt.style_presets 的键);空 = 从零建。
    base_preset: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    # 用户覆盖:style/lighting/camera/color_grade/negative 的任意子集。
    overrides_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
