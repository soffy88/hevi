"""Persistence adapters for W4/W5 authorities (Gap Closure W13).

Call records and endpoint definitions need a queryable home that is not
a task row: :class:`CallLedgerStore` (usage dashboard source) and
:class:`EndpointRegistry` (settings source). Both are small SQLite/WAL
stores with JSON rows, following the ``hevi.memory.store`` precedent.
Paths resolve from the environment at call time (``HEVI_USAGE_DB``,
``HEVI_ENDPOINTS_DB``) so tests point at tmp files without touching
production data. No secrets are ever stored: definitions are validated
secret-free before save.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  call_id TEXT PRIMARY KEY,
  project_ref TEXT NOT NULL DEFAULT '',
  provider TEXT NOT NULL DEFAULT '',
  model TEXT NOT NULL DEFAULT '',
  operation TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '',
  started_at TEXT NOT NULL DEFAULT '',
  record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_calls_filters ON calls(provider, model, operation, status);
CREATE TABLE IF NOT EXISTS endpoints (
  name TEXT PRIMARY KEY,
  updated_at TEXT NOT NULL DEFAULT '',
  definition_json TEXT NOT NULL
);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    return conn


def usage_db_path() -> Path:
    return Path(os.getenv("HEVI_USAGE_DB", "data/usage/ledger.db"))


def endpoints_db_path() -> Path:
    return Path(os.getenv("HEVI_ENDPOINTS_DB", "data/endpoints/registry.db"))


def memory_db_path() -> Path:
    return Path(os.getenv("HEVI_MEMORY_DB", "data/memory/hevi.db"))


class CallLedgerStore:
    """Append/read store for ProviderCallRecord rows (dashboard source)."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or usage_db_path()

    def append(self, record: dict[str, Any]) -> str:
        from hevi.creative.layer4.usage_ledger import ProviderCallRecord

        validated = ProviderCallRecord.model_validate(record)
        dump = validated.model_dump(mode="json")
        with _connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO calls "
                "(call_id, project_ref, provider, model, operation, status, started_at, record_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(validated.call_id),
                    validated.project_ref,
                    validated.provider,
                    validated.model,
                    validated.operation_type,
                    validated.status.value,
                    validated.started_at.isoformat(),
                    json.dumps(dump, ensure_ascii=False),
                ),
            )
        return str(validated.call_id)

    def get(self, call_id: str) -> dict[str, Any] | None:
        with _connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT record_json FROM calls WHERE call_id=?", (call_id,)
            ).fetchone()
        return json.loads(row["record_json"]) if row else None

    def list_records(
        self,
        *,
        provider: str = "",
        model: str = "",
        operation: str = "",
        status: str = "",
        project_ref: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("provider", provider),
            ("model", model),
            ("operation", operation),
            ("status", status),
            ("project_ref", project_ref),
        ):
            if value:
                clauses.append(f"{column}=?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with _connect(self.db_path) as conn:
            total = int(
                conn.execute(f"SELECT COUNT(*) AS n FROM calls {where}", params).fetchone()["n"]
            )
            rows = conn.execute(
                f"SELECT record_json FROM calls {where} ORDER BY started_at DESC, call_id DESC"
                " LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return [json.loads(row["record_json"]) for row in rows], total

    def all_records(self) -> list[dict[str, Any]]:
        rows, _ = self.list_records(limit=100000, offset=0)
        return rows


class EndpointRegistry:
    """Registry for declarative endpoint definitions (settings source)."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or endpoints_db_path()

    def save(self, definition: dict[str, Any]) -> str:
        from hevi.creative.layer4.endpoint_lifecycle import DeclarativeEndpointDefinition

        validated = DeclarativeEndpointDefinition.model_validate(definition)
        dump = validated.model_dump(mode="json")
        with _connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO endpoints (name, updated_at, definition_json)"
                " VALUES (?, ?, ?)",
                (validated.name, validated.updated_at.isoformat(), json.dumps(dump)),
            )
        return validated.name

    def get(self, name: str) -> dict[str, Any] | None:
        with _connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT definition_json FROM endpoints WHERE name=?", (name,)
            ).fetchone()
        return json.loads(row["definition_json"]) if row else None

    def list_definitions(self) -> list[dict[str, Any]]:
        with _connect(self.db_path) as conn:
            rows = conn.execute("SELECT definition_json FROM endpoints ORDER BY name").fetchall()
        return [json.loads(row["definition_json"]) for row in rows]

    def delete(self, name: str) -> bool:
        with _connect(self.db_path) as conn:
            cursor = conn.execute("DELETE FROM endpoints WHERE name=?", (name,))
            return cursor.rowcount > 0


__all__ = [
    "CallLedgerStore",
    "EndpointRegistry",
    "endpoints_db_path",
    "memory_db_path",
    "usage_db_path",
]
