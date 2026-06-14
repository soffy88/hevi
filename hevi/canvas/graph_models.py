from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from hevi.db.base import Base


class CanvasGraph(Base):
    __tablename__ = "canvas_graphs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), default="Untitled")
    description: Mapped[str] = mapped_column(Text, default="")
    nodes_json: Mapped[Any] = mapped_column(JSONB, default=list)
    edges_json: Mapped[Any] = mapped_column(JSONB, default=list)
    user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
