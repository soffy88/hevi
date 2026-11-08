"""First-class canvas node graph entities (canvas MVP).

``canvas_graphs.nodes_json`` / ``edges_json`` stay the frontend compatibility
mirror.  These tables are the execution-time source of truth: one row per node
and edge, an append-only artifact log, append-only node revisions, and a
per-node cost ledger.  Method provenance: stale marking, "a rerun only touches
the selected node and its downstream", locked nodes never being overwritten and
per-node review writeback follow the ArcReel canvas method described in
``HEVI_CANVAS_DESIGN.md`` §1/§2; this module is hevi's own implementation.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from hevi.db.base import Base


class CanvasNode(Base):
    __tablename__ = "canvas_nodes"
    __table_args__ = (UniqueConstraint("graph_id", "node_key", name="uq_canvas_nodes_graph_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    graph_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canvas_graphs.id", ondelete="CASCADE"), index=True
    )
    node_key: Mapped[str] = mapped_column(String(255), index=True)
    node_type: Mapped[str] = mapped_column(String(32))
    sub_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config: Mapped[Any] = mapped_column(JSONB, default=dict)
    input_refs: Mapped[Any] = mapped_column(JSONB, default=list)
    position: Mapped[Any] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    locked: Mapped[bool] = mapped_column(Boolean, default=False)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    review: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    estimated_cost: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    actual_cost: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CanvasEdge(Base):
    __tablename__ = "canvas_edges"
    __table_args__ = (UniqueConstraint("graph_id", "edge_key", name="uq_canvas_edges_graph_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    graph_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canvas_graphs.id", ondelete="CASCADE"), index=True
    )
    edge_key: Mapped[str] = mapped_column(String(255))
    from_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canvas_nodes.id", ondelete="CASCADE"), index=True
    )
    to_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canvas_nodes.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32), default="data")
    meta: Mapped[Any] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CanvasArtifact(Base):
    __tablename__ = "canvas_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    graph_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canvas_graphs.id", ondelete="CASCADE"), index=True
    )
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canvas_nodes.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    path: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    digest: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    mime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    meta: Mapped[Any] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CanvasNodeRevision(Base):
    __tablename__ = "canvas_node_revisions"
    __table_args__ = (
        UniqueConstraint("node_id", "revision", name="uq_canvas_revisions_node_rev"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canvas_nodes.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    config_snapshot: Mapped[Any] = mapped_column(JSONB, default=dict)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    review_result: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CanvasNodeCost(Base):
    __tablename__ = "canvas_node_costs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("canvas_nodes.id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimate: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    actual: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    pricing_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
