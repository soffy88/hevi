"""D3-A: durable owner-scoped store for persistent identities (HEVI Layer 4).

Backs :class:`PersistentIdentityRegistry` + :class:`ContinuityLedger` with a
small SQLite/WAL store (same pattern as ``authority_stores``). Paths resolve
from the environment at call time (``HEVI_IDENTITY_DB``) so tests point at
tmp files. Every row carries ``owner_id``; all reads filter by owner — the
store layer enforces tenant isolation even if a caller forgets.

Tables: ``identities``, ``bindings``, ``continuity_facts``, ``subject_links``
(subject_id -> identity_id, so project-local Subjects can bind explicitly).
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from hevi.creative.layer4.persistent_identity import (
    ContinuityFactRecord,
    PersistentIdentityRegistry,
)
from hevi.creative.layer4.store_topology import claim_authority

_SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS identities (
  identity_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT '',
  identity_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_identities_owner ON identities(owner_id);
CREATE TABLE IF NOT EXISTS bindings (
  binding_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL DEFAULT '',
  project_id TEXT NOT NULL DEFAULT '',
  identity_id TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT '',
  binding_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bindings_owner ON bindings(owner_id);
CREATE INDEX IF NOT EXISTS idx_bindings_project ON bindings(project_id);
CREATE TABLE IF NOT EXISTS continuity_facts (
  fact_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL DEFAULT '',
  identity_id TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT '',
  fact_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facts_owner_identity ON continuity_facts(owner_id, identity_id);
CREATE TABLE IF NOT EXISTS subject_links (
  subject_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL DEFAULT '',
  identity_id TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_links_owner ON subject_links(owner_id);
CREATE TABLE IF NOT EXISTS continuity_decisions (
  decision_id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL DEFAULT '',
  binding_id TEXT NOT NULL DEFAULT '',
  stage TEXT NOT NULL DEFAULT '',
  verdict TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT '',
  decision_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_owner_binding ON continuity_decisions(owner_id, binding_id);
CREATE TABLE IF NOT EXISTS schema_version (
  store TEXT PRIMARY KEY,
  version INTEGER NOT NULL
);
"""


def _ensure_schema_version(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT version FROM schema_version WHERE store='identities'"
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_version (store, version) VALUES ('identities', ?)",
            (_SCHEMA_VERSION,),
        )
    elif int(row["version"]) > _SCHEMA_VERSION:
        raise ValueError(
            f"IDENTITY_STORE_SCHEMA_TOO_NEW:{row['version']}>{_SCHEMA_VERSION}"
        )


def identity_db_path() -> Path:
    return Path(os.getenv("HEVI_IDENTITY_DB", "data/identity/identities.db"))


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    _ensure_schema_version(conn)
    return conn


class IdentityStore:
    """Durable, owner-scoped persistence for identities/bindings/facts/links."""

    def __init__(
        self, db_path: Path | None = None, *, authority_host_id: str | None = None
    ) -> None:
        self.db_path = db_path or identity_db_path()
        with _connect(self.db_path) as conn:
            # D5-B: single-host durable authority — refuse split-brain.
            claim_authority(conn, store="identities", host_id=authority_host_id)

    # -- identities ----------------------------------------------------

    def save_identity(self, owner_id: str, identity: dict[str, Any]) -> str:
        identity_id = str(identity.get("identity_id") or "")
        if not identity_id:
            raise ValueError("IDENTITY_STORE_IDENTITY_ID_REQUIRED")
        with _connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO identities "
                "(identity_id, owner_id, updated_at, identity_json) VALUES (?, ?, ?, ?)",
                (
                    identity_id,
                    owner_id,
                    str(identity.get("created_at") or ""),
                    json.dumps(identity, ensure_ascii=False),
                ),
            )
        return identity_id

    def load_identities(self, owner_id: str) -> list[dict[str, Any]]:
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT identity_json FROM identities WHERE owner_id=? ORDER BY identity_id",
                (owner_id,),
            ).fetchall()
        return [json.loads(row["identity_json"]) for row in rows]

    # -- bindings ------------------------------------------------------

    def save_binding(self, owner_id: str, binding: dict[str, Any]) -> str:
        binding_id = str(binding.get("binding_id") or "")
        if not binding_id:
            raise ValueError("IDENTITY_STORE_BINDING_ID_REQUIRED")
        with _connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO bindings "
                "(binding_id, owner_id, project_id, identity_id, updated_at, binding_json)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    binding_id,
                    owner_id,
                    str(binding.get("project_id") or ""),
                    str(binding.get("identity_id") or ""),
                    str(binding.get("created_at") or ""),
                    json.dumps(binding, ensure_ascii=False),
                ),
            )
        return binding_id

    def load_bindings(
        self, owner_id: str, *, project_id: str = ""
    ) -> list[dict[str, Any]]:
        clauses = ["owner_id=?"]
        params: list[Any] = [owner_id]
        if project_id:
            clauses.append("project_id=?")
            params.append(project_id)
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT binding_json FROM bindings WHERE {' AND '.join(clauses)}"
                " ORDER BY binding_id",
                params,
            ).fetchall()
        return [json.loads(row["binding_json"]) for row in rows]

    # -- continuity facts ----------------------------------------------

    def save_fact(self, owner_id: str, fact: dict[str, Any]) -> str:
        fact_id = str(fact.get("fact_id") or "")
        if not fact_id:
            raise ValueError("IDENTITY_STORE_FACT_ID_REQUIRED")
        # Append-only history: the first write wins; current facts never
        # rewrite a historical revision (D3-B/B5).
        with _connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO continuity_facts "
                "(fact_id, owner_id, identity_id, updated_at, fact_json)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    fact_id,
                    owner_id,
                    str(fact.get("identity_id") or ""),
                    str(fact.get("created_at") or ""),
                    json.dumps(fact, ensure_ascii=False),
                ),
            )
        return fact_id

    def load_facts(self, owner_id: str, identity_id: str) -> list[dict[str, Any]]:
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT fact_json FROM continuity_facts WHERE owner_id=? AND identity_id=?"
                " ORDER BY fact_id",
                (owner_id, identity_id),
            ).fetchall()
        return [json.loads(row["fact_json"]) for row in rows]

    # -- subject links ---------------------------------------------------

    def link_subject(self, owner_id: str, subject_id: str, identity_id: str) -> None:
        if not subject_id.strip() or not identity_id.strip():
            raise ValueError("IDENTITY_STORE_LINK_IDENTITY_REQUIRED")
        with _connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO subject_links "
                "(subject_id, owner_id, identity_id, updated_at)"
                " VALUES (?, ?, ?, datetime('now'))",
                (subject_id, owner_id, identity_id),
            )

    def unlink_subject(self, owner_id: str, subject_id: str) -> bool:
        with _connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM subject_links WHERE subject_id=? AND owner_id=?",
                (subject_id, owner_id),
            )
            return cursor.rowcount > 0

    def subject_identity(self, owner_id: str, subject_id: str) -> str | None:
        with _connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT identity_id FROM subject_links WHERE subject_id=? AND owner_id=?",
                (subject_id, owner_id),
            ).fetchone()
        return str(row["identity_id"]) if row else None

    def linked_subjects(self, owner_id: str, identity_id: str) -> list[str]:
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT subject_id FROM subject_links WHERE owner_id=? AND identity_id=?"
                " ORDER BY subject_id",
                (owner_id, identity_id),
            ).fetchall()
        return [str(row["subject_id"]) for row in rows]

    # -- continuity gate decisions (WARN override audit) -------------------

    def save_decision(self, owner_id: str, decision: dict[str, Any]) -> str:
        decision_id = str(decision.get("decision_id") or "")
        if not decision_id:
            raise ValueError("IDENTITY_STORE_DECISION_ID_REQUIRED")
        with _connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO continuity_decisions "
                "(decision_id, owner_id, binding_id, stage, verdict, updated_at, decision_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    decision_id,
                    owner_id,
                    str(decision.get("binding_id") or ""),
                    str(decision.get("stage") or ""),
                    str(decision.get("verdict") or ""),
                    str(decision.get("decided_at") or ""),
                    json.dumps(decision, ensure_ascii=False),
                ),
            )
        return decision_id

    def load_decisions(
        self, owner_id: str, *, binding_id: str = ""
    ) -> list[dict[str, Any]]:
        clauses = ["owner_id=?"]
        params: list[Any] = [owner_id]
        if binding_id:
            clauses.append("binding_id=?")
            params.append(binding_id)
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT decision_json FROM continuity_decisions WHERE {' AND '.join(clauses)}"
                " ORDER BY decision_id",
                params,
            ).fetchall()
        return [json.loads(row["decision_json"]) for row in rows]

    # -- referential integrity (D5-C) -----------------------------------

    def integrity_report(self, owner_id: str) -> dict[str, list[str]]:
        """Return dangling canonical references for one owner (empty = clean).

        Dangling keys:
        - binding.identity_id not in identities
        - fact.identity_id not in identities
        - decision.binding_id not in bindings
        - subject_link.identity_id not in identities
        """
        with _connect(self.db_path) as conn:
            identity_ids = {
                str(row["identity_id"])
                for row in conn.execute(
                    "SELECT identity_id FROM identities WHERE owner_id=?", (owner_id,)
                )
            }
            bindings = conn.execute(
                "SELECT binding_id, identity_id FROM bindings WHERE owner_id=?",
                (owner_id,),
            ).fetchall()
            facts = conn.execute(
                "SELECT fact_id, identity_id FROM continuity_facts WHERE owner_id=?",
                (owner_id,),
            ).fetchall()
            decisions = conn.execute(
                "SELECT decision_id, binding_id FROM continuity_decisions WHERE owner_id=?",
                (owner_id,),
            ).fetchall()
            links = conn.execute(
                "SELECT subject_id, identity_id FROM subject_links WHERE owner_id=?",
                (owner_id,),
            ).fetchall()

        binding_ids = {str(row["binding_id"]) for row in bindings}
        dangling: dict[str, list[str]] = {
            "binding_identity": [
                str(row["binding_id"])
                for row in bindings
                if str(row["identity_id"]) not in identity_ids
            ],
            "fact_identity": [
                str(row["fact_id"])
                for row in facts
                if str(row["identity_id"]) not in identity_ids
            ],
            "decision_binding": [
                str(row["decision_id"])
                for row in decisions
                if str(row["binding_id"]) not in binding_ids
            ],
            "link_identity": [
                str(row["subject_id"])
                for row in links
                if str(row["identity_id"]) not in identity_ids
            ],
        }
        return {key: value for key, value in dangling.items() if value}


__all__ = ["IdentityStore", "identity_db_path", "load_owner_registry"]


def load_owner_registry(
    store: IdentityStore, owner_id: str
) -> PersistentIdentityRegistry:
    """Hydrate one owner's registry (identities + bindings + ledger facts)."""
    registry = PersistentIdentityRegistry()
    registry.restore(
        {
            "identities": store.load_identities(owner_id),
            "bindings": store.load_bindings(owner_id),
        }
    )
    for identity in registry.identities:
        for row in store.load_facts(owner_id, identity.identity_id):
            registry.ledger.record(ContinuityFactRecord.model_validate(row))
    return registry
