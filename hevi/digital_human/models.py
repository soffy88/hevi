from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from hevi.db.base import Base


class Presenter(Base):
    """A reusable speaking/on-camera profile built on a Subject asset."""

    __tablename__ = "presenters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255))
    subject_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    voice_profile_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    performance: Mapped[str] = mapped_column(String(32), default="narrator")
    motion: Mapped[str] = mapped_column(String(32), default="picture_in_picture")
    lipsync: Mapped[str] = mapped_column(String(32), default="none")
    delivery_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)
