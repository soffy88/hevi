from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from hevi.db.base import Base


class CreditAccount(Base):
    __tablename__ = "credit_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # P0-D: reserved_balance tracks active reservations
    reserved_balance: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    @property
    def available_balance(self) -> int:
        """Available for new reservations: posted - active reservations"""
        return max(0, self.balance - self.reserved_balance)


class CreditTransaction(Base):
    __tablename__ = "credit_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # +topup / -consume
    tx_type: Mapped[Literal["topup", "consume", "refund", "reserve", "release"]] = mapped_column(
        String(20), nullable=False
    )
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    balance_after: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class BillingReservation(Base):
    """P0-D: Transactional billing reservation ledger.

    Reservation lifecycle:
    1. RESERVE: lock credits, status='active', expires_at set
    2. CONSUME: actual provider cost charged, status='consumed', consumed_amount set
    3. RELEASE: unused reservation returned, status='released'
    4. REFUND: for already-consumed credits (after provider acceptance failure), REFUND tx
    5. EXPIRED: TTL expiry, auto-released by cron
    """
    __tablename__ = "billing_reservations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    production_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("productions.id"), nullable=True, index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("video_tasks.id"), nullable=True, index=True
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_attempts.id"), nullable=True, index=True
    )
    # External idempotency key: production_id:attempt_id:phase (e.g., "prov1:att3:generate")
    external_ref: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)  # amount in cents
    status: Mapped[Literal["active", "consumed", "released", "expired"]] = mapped_column(
        String(20), nullable=False, default="active"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_amount_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


__all__ = ["BillingReservation", "CreditAccount", "CreditTransaction"]