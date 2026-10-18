"""Append-only changefeed writer backed by MetaDB (DuckDB/Postgres).

Invariants:
- Only INSERTs — never UPDATE or DELETE changefeed_events
- seq is strictly increasing per (user_id)
- asyncio.Lock per user_id serializes concurrent writers within a process

Restored from Phase 2 Wave 2 (commit 11a6f0b) and adapted to the current
consumer contract (event_type/seq/device_id) + lazy schema bootstrap.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from oprim._logging import log
from oprim.changefeed._bootstrap import ensure_schema
from oprim.changefeed.errors import ChangefeedConflictError
from oprim.changefeed.schema import ChangefeedEvent, EventType
from oprim.meta_db.duckdb import MetaDB

# Per-user async locks — serializes concurrent append() calls within one process
_USER_LOCKS: dict[str, asyncio.Lock] = {}
_LOCKS_MUTEX = asyncio.Lock()


async def _get_user_lock(user_id: str) -> asyncio.Lock:
    async with _LOCKS_MUTEX:
        if user_id not in _USER_LOCKS:
            _USER_LOCKS[user_id] = asyncio.Lock()
        return _USER_LOCKS[user_id]


class ChangefeedWriter:
    """Appends events to the changefeed_events table in an append-only manner."""

    def __init__(self, db: MetaDB, user_id: str, device_id: str) -> None:
        self.db = db
        self.user_id = user_id
        self.device_id = device_id

    async def append(
        self,
        event_type: EventType,
        aggregate_id: str | None,
        payload: dict,
    ) -> ChangefeedEvent:
        """Append an event; seq is assigned atomically per user."""
        ensure_schema(self.db)
        lock = await _get_user_lock(self.user_id)
        async with lock:
            rows = self.db.fetchall(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM changefeed_events WHERE user_id = ?",
                [self.user_id],
            )
            next_seq: int = rows[0][0]

            payload_json = json.dumps(payload, ensure_ascii=False)
            try:
                self.db.execute(
                    """INSERT INTO changefeed_events
                       (device_id, user_id, event_type, aggregate_id, payload, seq)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        self.device_id,
                        self.user_id,
                        event_type.value,
                        aggregate_id,
                        payload_json,
                        next_seq,
                    ],
                )
            except Exception as exc:
                if "UNIQUE constraint" in str(exc) or "Constraint" in type(exc).__name__:
                    raise ChangefeedConflictError(
                        f"seq conflict for user_id={self.user_id} seq={next_seq}"
                    ) from exc
                raise

            back = self.db.fetchall(
                "SELECT id, created_at FROM changefeed_events WHERE user_id = ? AND seq = ?",
                [self.user_id, next_seq],
            )
            row_id, created_at_raw = back[0]
            if isinstance(created_at_raw, str):
                created_at = datetime.fromisoformat(created_at_raw)
            elif isinstance(created_at_raw, datetime):
                created_at = created_at_raw
            else:
                created_at = datetime.now(tz=UTC)

            event = ChangefeedEvent(
                id=row_id,
                device_id=self.device_id,
                user_id=self.user_id,
                event_type=event_type,
                aggregate_id=aggregate_id,
                payload=payload,
                created_at=created_at,
                seq=next_seq,
            )
            log.info(
                "changefeed_event_written",
                event_type=event_type.value,
                seq=next_seq,
                user_id=self.user_id,
            )
            return event
