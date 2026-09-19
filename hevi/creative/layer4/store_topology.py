"""D5-B: durable-store topology contract (single-host durable).

HEVI's supported production topology at this revision is
``SINGLE_HOST_DURABLE``: one authoritative API process group on one host,
with the differentiation SQLite stores on that host's persistent volume
(mounted into ``hevi-api``; the queue worker runs inside the app lifespan).
This is **not** multi-node / HA durable.

Enforcement:

- every store claims authority for its ``store`` name at startup with a
  host identity + heartbeat;
- if another **host** holds a fresh claim on the same store file, startup
  fails closed (``SplitBrainAuthorityError``) instead of running two
  authority truths against one shared file;
- a stale claim from a dead host is taken over.

Claim parameters are injectable so the conflict can be tested without a
second physical host.
"""

from __future__ import annotations

import os
import socket
import sqlite3
import time

#: The only topology HEVI claims for these stores today.
TOPOLOGY = "single_host_durable"

#: A claim older than this is considered dead and may be taken over.
CLAIM_TTL_SECONDS = 120.0


class SplitBrainAuthorityError(RuntimeError):
    """Refusal: this store file is claimed by a different authority host."""


def authority_host_id() -> str:
    explicit = os.getenv("HEVI_AUTHORITY_HOST_ID", "").strip()
    if explicit:
        return explicit
    return socket.gethostname().strip() or "unknown-host"


_CLAIM_SCHEMA = """
CREATE TABLE IF NOT EXISTS authority_claim (
  store TEXT PRIMARY KEY,
  host_id TEXT NOT NULL DEFAULT '',
  pid INTEGER NOT NULL DEFAULT 0,
  heartbeat_at REAL NOT NULL DEFAULT 0
);
"""


def claim_authority(
    conn: sqlite3.Connection,
    *,
    store: str,
    host_id: str | None = None,
    pid: int | None = None,
    now: float | None = None,
    ttl_seconds: float = CLAIM_TTL_SECONDS,
) -> None:
    """Claim store authority or refuse on a live cross-host conflict.

    Raises :class:`SplitBrainAuthorityError` when a *different* host holds a
    claim whose heartbeat is still fresh.
    """
    conn.executescript(_CLAIM_SCHEMA)
    conn.row_factory = sqlite3.Row
    resolved_host = (host_id or authority_host_id()).strip() or "unknown-host"
    resolved_pid = os.getpid() if pid is None else pid
    moment = time.time() if now is None else now
    row = conn.execute(
        "SELECT host_id, heartbeat_at FROM authority_claim WHERE store=?", (store,)
    ).fetchone()
    if row is not None:
        other_host = str(row["host_id"] or "")
        last_beat = float(row["heartbeat_at"] or 0.0)
        if other_host and other_host != resolved_host and (moment - last_beat) < ttl_seconds:
            raise SplitBrainAuthorityError(
                f"AUTHORITY_HOST_CONFLICT:{store}:held_by={other_host}:"
                f"topology={TOPOLOGY}"
            )
    conn.execute(
        "INSERT OR REPLACE INTO authority_claim (store, host_id, pid, heartbeat_at)"
        " VALUES (?, ?, ?, ?)",
        (store, resolved_host, resolved_pid, moment),
    )


def current_claim(conn: sqlite3.Connection, store: str) -> dict[str, object] | None:
    conn.executescript(_CLAIM_SCHEMA)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT store, host_id, pid, heartbeat_at FROM authority_claim WHERE store=?",
        (store,),
    ).fetchone()
    if row is None:
        return None
    return {
        "store": str(row["store"]),
        "host_id": str(row["host_id"]),
        "pid": int(row["pid"]),
        "heartbeat_at": float(row["heartbeat_at"]),
    }


__all__ = [
    "CLAIM_TTL_SECONDS",
    "TOPOLOGY",
    "SplitBrainAuthorityError",
    "authority_host_id",
    "claim_authority",
    "current_claim",
]
