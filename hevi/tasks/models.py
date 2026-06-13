import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hevi.db.base import Base


class VideoTask(Base):
    __tablename__ = "video_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    topic: Mapped[str] = mapped_column(String(255))
    duration_archetype: Mapped[str] = mapped_column(String(50))
    video_provider: Mapped[str] = mapped_column(String(50))
    audio_provider: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    progress_pct: Mapped[float] = mapped_column(Float, default=0.0)
    total_shots: Mapped[int] = mapped_column(Integer, default=0)
    completed_shots: Mapped[int] = mapped_column(Integer, default=0)
    result_video_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=datetime.utcnow, onupdate=datetime.utcnow)

    shots: Mapped[list[ShotState]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class ShotState(Base):
    __tablename__ = "shot_states"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("video_tasks.id"))
    shot_index: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    output_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reference_set_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)

    task: Mapped[VideoTask] = relationship(back_populates="shots")
