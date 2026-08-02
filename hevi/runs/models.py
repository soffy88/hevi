from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from hevi.db.base import Base


class AutomationRun(Base):
    """A durable pre-production session owned by a content adapter.

    A run stores adapter-specific planning state only.  Generated media,
    accounting and delivery remain the responsibility of linked video tasks.
    """

    __tablename__ = "automation_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # tongjian / shortdrama / explainer
    user_id: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(40), index=True, default="PENDING")
    input_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    state_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    task_ids: Mapped[list[str]] = mapped_column(JSONB, default=list)
    series_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
