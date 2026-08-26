"""P0-D: Transactional Billing Reservation System

Replaces check_and_reserve (which only checked balance) with full reservation lifecycle:
- reserve(): atomic SELECT FOR UPDATE + INSERT reservation + ledger entry
- consume(): mark reservation consumed, update account balance
- release(): release unused reservation, rollback reserved_balance
- refund(): create REFUND transaction for already consumed amounts
- All operations idempotent via external_ref unique constraint
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from hevi.core.config import settings
from hevi.cost.estimator import estimate_cost
from hevi.credits.account_service import AccountService
from obase.persistence import PgPool


class InsufficientCredits(Exception):
    """Raised when user available balance is below requested amount."""

    def __init__(self, amount_cents: int, available_cents: int) -> None:
        self.amount_cents = amount_cents
        self.available_cents = available_cents
        super().__init__(
            f"Insufficient credits: needed {amount_cents} cents, have {available_cents} cents"
        )


class ReservationNotFound(Exception):
    pass


class BillingService:
    def __init__(self, account_svc: AccountService, pool: PgPool | None = None) -> None:
        self._account_svc = account_svc
        self._pool = pool or getattr(account_svc._repo, '_pool', None) if hasattr(account_svc, '_repo') else None

    async def estimate_credits(
        self,
        duration_archetype: str,
        video_provider: str = "ltx2_cloud",
        ltx2_tier: str = "fast",
        quality_profile: str = "standard",
        num_characters: int = 1,
        **kwargs: Any,
    ) -> int:
        """Estimate credit cost for a video task."""
        estimate = await estimate_cost(
            duration_archetype=duration_archetype,
            video_provider=video_provider,
            audio_provider=kwargs.get("audio_provider", "vibevoice"),
            ltx2_tier=ltx2_tier,
            quality=quality_profile,
            num_characters=num_characters,
        )
        return int(estimate.total_usd * settings.credits_per_usd)

    # ========== NEW: Transactional Reservation API ==========

    async def reserve(
        self,
        user_id: str,
        amount_cents: int,
        *,
        production_id: str | None = None,
        task_id: str | None = None,
        attempt_id: str | None = None,
        external_ref: str | None = None,
        ttl_seconds: int = 3600,  # 1 hour default TTL
    ) -> dict[str, Any]:
        """Atomically reserve credits for a production/attempt.

        Uses SELECT FOR UPDATE on credit_accounts + INSERT ON CONFLICT on billing_reservations.
        external_ref is the idempotency key (production_id:attempt_id:phase).
        """
        if external_ref is None:
            parts = []
            if production_id:
                parts.append(f"prod:{production_id}")
            if task_id:
                parts.append(f"task:{task_id}")
            if attempt_id:
                parts.append(f"att:{attempt_id}")
            parts.append("reserve")
            external_ref = ":".join(parts)

        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)

        async with self._pool.acquire() as conn, conn.transaction():
            # Lock the account row
            account = await conn.fetchrow(
                "SELECT balance, reserved_balance FROM credit_accounts WHERE user_id = $1 FOR UPDATE",
                user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(user_id),
            )
            if not account:
                raise InsufficientCredits(amount_cents, 0)

            balance = account["balance"]
            reserved = account["reserved_balance"]
            available = max(0, balance - reserved)

            if available < amount_cents:
                raise InsufficientCredits(amount_cents, available)

            # Check/insert reservation (idempotent)
            existing = await conn.fetchrow(
                """SELECT * FROM billing_reservations WHERE external_ref = $1""",
                external_ref,
            )
            if existing:
                # Already exists - return existing (idempotent)
                return dict(existing)

            # Insert reservation
            reservation_id = uuid.uuid4()
            await conn.execute(
                """INSERT INTO billing_reservations
                   (id, user_id, production_id, task_id, attempt_id, external_ref,
                    amount_cents, status, expires_at, consumed_amount_cents, created_at, updated_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, 'active', $8, 0, NOW(), NOW())""",
                reservation_id,
                user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(user_id),
                uuid.UUID(production_id) if production_id else None,
                uuid.UUID(task_id) if task_id else None,
                uuid.UUID(attempt_id) if attempt_id else None,
                external_ref,
                amount_cents,
                expires_at,
            )

            # Update reserved_balance
            await conn.execute(
                """UPDATE credit_accounts SET reserved_balance = reserved_balance + $1 WHERE user_id = $2""",
                amount_cents,
                user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(user_id),
            )

            # Ledger entry for RESERVE
            await conn.execute(
                """INSERT INTO credit_transactions
                   (id, user_id, amount, tx_type, reference, balance_after, created_at)
                   VALUES ($1, $2, $3, 'reserve', $4, $5, NOW())""",
                user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(user_id),
                0,  # reserve doesn't change balance
                external_ref,
                balance,  # balance unchanged
            )

            return {
                "id": str(reservation_id),
                "user_id": user_id,
                "amount_cents": amount_cents,
                "status": "active",
                "external_ref": external_ref,
                "expires_at": expires_at.isoformat(),
            }

    async def consume(
        self,
        reservation_id: str,
        actual_amount_cents: int,
        *,
        external_ref: str | None = None,
    ) -> dict[str, Any]:
        """Mark reservation as consumed and deduct from posted balance.

        Idempotent: if already consumed with same external_ref, returns existing.
        """
        if external_ref is None:
            external_ref = f"consume:{reservation_id}:{actual_amount_cents}"

        async with self._pool.acquire() as conn, conn.transaction():
            # Get reservation with lock
            res = await conn.fetchrow(
                """SELECT * FROM billing_reservations WHERE id = $1 FOR UPDATE""",
                uuid.UUID(reservation_id),
            )
            if not res:
                raise ReservationNotFound(f"Reservation {reservation_id} not found")

            if res["status"] != "active":
                if res["status"] == "consumed" and res["consumed_amount_cents"] == actual_amount_cents:
                    # Idempotent re-consume
                    return dict(res)
                raise ValueError(f"Reservation {reservation_id} not active: {res['status']}")

            if actual_amount_cents > res["amount_cents"]:
                raise ValueError(f"Consume amount {actual_amount_cents} exceeds reservation {res['amount_cents']}")

            user_id = res["user_id"]

            # Lock account
            account = await conn.fetchrow(
                "SELECT balance, reserved_balance FROM credit_accounts WHERE user_id = $1 FOR UPDATE",
                user_id,
            )
            if not account:
                raise ValueError(f"Account {user_id} not found")

            # Update reservation
            await conn.execute(
                """UPDATE billing_reservations
                   SET status = 'consumed', consumed_amount_cents = $1, updated_at = NOW()
                   WHERE id = $2""",
                actual_amount_cents,
                uuid.UUID(reservation_id),
            )

            # Update account: deduct actual from balance, release FULL reservation from reserved_balance
            # Note: reserved_balance was increased by amount_cents at reserve time.
            # We must subtract the FULL reservation amount from reserved_balance to close it.
            # The difference (amount_cents - actual_amount_cents) is the unused excess.
            await conn.execute(
                """UPDATE credit_accounts
                   SET balance = balance - $1,
                       reserved_balance = reserved_balance - $2,
                       updated_at = NOW()
                   WHERE user_id = $3""",
                actual_amount_cents,
                res["amount_cents"],
                user_id,
            )

            # Ledger entry for CONSUME
            await conn.execute(
                """INSERT INTO credit_transactions
                   (id, user_id, amount, tx_type, reference, balance_after, created_at)
                   VALUES (uuid_generate_v4(), $1, -$2, 'consume', $3, $4, NOW())""",
                user_id,
                actual_amount_cents,
                external_ref,
                account["balance"] - actual_amount_cents,
            )

            return await conn.fetchrow(
                "SELECT * FROM billing_reservations WHERE id = $1",
                uuid.UUID(reservation_id),
            )

    async def release(
        self,
        reservation_id: str,
        *,
        external_ref: str | None = None,
    ) -> dict[str, Any]:
        """Release an unused/active reservation back to available balance.

        Idempotent: if already released, returns existing.
        """
        if external_ref is None:
            external_ref = f"release:{reservation_id}"

        async with self._pool.acquire() as conn, conn.transaction():
            res = await conn.fetchrow(
                """SELECT * FROM billing_reservations WHERE id = $1 FOR UPDATE""",
                uuid.UUID(reservation_id),
            )
            if not res:
                raise ReservationNotFound(f"Reservation {reservation_id} not found")

            if res["status"] in ("released", "expired"):
                return dict(res)

            user_id = res["user_id"]

            # Update account: release full reserved amount
            await conn.execute(
                """UPDATE credit_accounts
                   SET reserved_balance = reserved_balance - $1,
                       updated_at = NOW()
                   WHERE user_id = $2""",
                res["amount_cents"],
                user_id,
            )

            await conn.execute(
                """UPDATE billing_reservations
                   SET status = 'released', updated_at = NOW()
                   WHERE id = $1""",
                uuid.UUID(reservation_id),
            )

            # Ledger entry for RELEASE
            account = await conn.fetchrow(
                "SELECT balance, reserved_balance FROM credit_accounts WHERE user_id = $1",
                user_id,
            )
            await conn.execute(
                """INSERT INTO credit_transactions
                   (id, user_id, amount, tx_type, reference, balance_after, created_at)
                   VALUES (uuid_generate_v4(), $1, 0, 'release', $2, $3, NOW())""",
                user_id,
                external_ref,
                account["balance"] if account else 0,
            )

            return await conn.fetchrow(
                "SELECT * FROM billing_reservations WHERE id = $1",
                uuid.UUID(reservation_id),
            )

    async def refund_consumed(
        self,
        attempt_id: str,
        amount_cents: int | None = None,
        *,
        external_ref: str | None = None,
    ) -> dict[str, Any]:
        """Refund credits for an already-consumed attempt.

        This creates a REFUND ledger entry and increases account balance.
        Unlike release(), this is for post-consumption refunds.
        """
        if external_ref is None:
            external_ref = f"refund:{attempt_id}"

        async with self._pool.acquire() as conn, conn.transaction():
            # Find consumed reservation for this attempt
            res = await conn.fetchrow(
                """SELECT * FROM billing_reservations
                   WHERE attempt_id = $1 AND status = 'consumed'
                   ORDER BY created_at DESC LIMIT 1""",
                uuid.UUID(attempt_id),
            )
            if not res:
                raise ReservationNotFound(f"No consumed reservation for attempt {attempt_id}")

            refund_amount = amount_cents or res["consumed_amount_cents"]
            if refund_amount > res["consumed_amount_cents"]:
                raise ValueError(f"Refund {refund_amount} exceeds consumed {res['consumed_amount_cents']}")

            user_id = res["user_id"]

            # Lock account
            account = await conn.fetchrow(
                "SELECT balance, reserved_balance FROM credit_accounts WHERE user_id = $1 FOR UPDATE",
                user_id,
            )
            if not account:
                raise ValueError(f"Account {user_id} not found")

            # Update balance
            await conn.execute(
                """UPDATE credit_accounts SET balance = balance + $1, updated_at = NOW() WHERE user_id = $2""",
                refund_amount,
                user_id,
            )

            # Ledger entry for REFUND
            await conn.execute(
                """INSERT INTO credit_transactions
                   (id, user_id, amount, tx_type, reference, balance_after, created_at)
                   VALUES (uuid_generate_v4(), $1, $2, 'refund', $3, $4, NOW())""",
                user_id,
                refund_amount,
                external_ref,
                account["balance"] + refund_amount,
            )

            return {
                "status": "refunded",
                "amount_cents": refund_amount,
                "user_id": str(user_id),
            }

    # ========== DEPRECATED: Old API (calls new internally for one release) ==========

    async def check_and_reserve(self, user_id: str, credits_needed: int) -> bool:
        """DEPRECATED: Only checks balance, no reservation.

        In one release, this will internally call reserve() and track it.
        For now, kept for backward compatibility but emits warning.
        """
        import warnings
        warnings.warn(
            "check_and_reserve is deprecated. Use reserve() for transactional reservations.",
            DeprecationWarning,
            stacklevel=2,
        )
        balance = await self._account_svc.get_balance(user_id)
        if balance < credits_needed:
            raise InsufficientCredits(
                amount_cents=credits_needed, available_cents=balance
            )
        return True

    async def consume_legacy(
        self, user_id: str, credits: int, task_id: str
    ) -> dict[str, Any]:
        """DEPRECATED: Use consume(reservation_id, amount_cents) instead."""
        return await self._account_svc.consume(user_id, credits, task_ref=task_id)

    async def refund_legacy(
        self, user_id: str, credits: int, task_id: str
    ) -> dict[str, Any]:
        """DEPRECATED: Use refund_consumed(attempt_id, amount_cents) instead."""
        return await self._account_svc.refund(user_id, credits, task_ref=task_id)

    async def refund_for_task(self, user_id: str, task_id: str) -> dict[str, Any]:
        """DEPRECATED: Use refund_consumed(attempt_id) instead."""
        return await self._account_svc.refund_for_task(user_id, task_id)


__all__ = ["InsufficientCredits", "ReservationNotFound", "BillingService"]