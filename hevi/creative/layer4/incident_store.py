"""D3-C: durable store + service for self-healing incidents (HEVI Layer 4).

:class:`IncidentStore` persists every :class:`RepairIncident` transition and
the loop-guard attempt history in SQLite/WAL (``HEVI_INCIDENT_DB``), so a
process restart resumes the same incident/action/attempt-count/cooldown
instead of forgetting and rebilling.

:class:`IncidentService` composes :class:`SelfHealingCoordinator` with the
store: every mutating call persists, construction reloads open state. The
service never executes provider work — execution stays with the existing
runtime authority; the service only tracks, gates, and verifies.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hevi.creative.layer4.repair_incident import (
    IncidentError,
    IncidentStatus,
    ProjectRepairPolicy,
    RepairActionProposal,
    RepairIncident,
    RepairLoopGuard,
    SelfHealingCoordinator,
)

_SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
  incident_id TEXT PRIMARY KEY,
  production_run_id TEXT NOT NULL DEFAULT '',
  node_key TEXT NOT NULL DEFAULT '',
  owner_id TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT '',
  incident_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incidents_run_node ON incidents(production_run_id, node_key);
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_incidents_owner ON incidents(owner_id);
CREATE TABLE IF NOT EXISTS repair_attempts (
  fingerprint TEXT PRIMARY KEY,
  timestamps_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dedupe_events (
  fingerprint TEXT PRIMARY KEY,
  hits INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS schema_version (
  store TEXT PRIMARY KEY,
  version INTEGER NOT NULL
);
"""


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Fail-safe forward migration: old DBs gain new columns, never rebuilds."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(incidents)")}
    if "owner_id" not in existing:
        conn.execute("ALTER TABLE incidents ADD COLUMN owner_id TEXT NOT NULL DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_incidents_owner ON incidents(owner_id)")
    row = conn.execute(
        "SELECT version FROM schema_version WHERE store='incidents'"
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_version (store, version) VALUES ('incidents', ?)",
            (_SCHEMA_VERSION,),
        )
    elif int(row["version"]) > _SCHEMA_VERSION:
        raise ValueError(
            f"INCIDENT_STORE_SCHEMA_TOO_NEW:{row['version']}>{_SCHEMA_VERSION}"
        )


def incident_db_path() -> Path:
    return Path(os.getenv("HEVI_INCIDENT_DB", "data/incidents/repair.db"))


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    _ensure_columns(conn)
    return conn


_TERMINAL = (
    IncidentStatus.RESOLVED.value,
    IncidentStatus.REPAIR_FAILED.value,
    IncidentStatus.ESCALATED_MANUAL.value,
)


class IncidentStore:
    """Durable persistence for incidents + loop-guard history."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or incident_db_path()
        with _connect(self.db_path):
            pass

    def save_incident(
        self, incident: dict[str, Any], *, expect_status: str | None = None
    ) -> bool:
        """Persist one incident. With ``expect_status``, the write is a
        compare-and-swap: it applies only if the stored status still matches,
        returning False on a concurrent modification (lost-update guard)."""
        incident_id = str(incident.get("incident_id") or "")
        if not incident_id:
            raise ValueError("INCIDENT_STORE_INCIDENT_ID_REQUIRED")
        row = (
            incident_id,
            str(incident.get("production_run_id") or ""),
            str(incident.get("node_key") or ""),
            str(incident.get("owner_id") or ""),
            str(incident.get("status") or ""),
            str(incident.get("created_at") or ""),
            json.dumps(incident, ensure_ascii=False),
        )
        with _connect(self.db_path) as conn:
            if expect_status is None:
                conn.execute(
                    "INSERT OR REPLACE INTO incidents "
                    "(incident_id, production_run_id, node_key, owner_id, status,"
                    " updated_at, incident_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    row,
                )
                return True
            cursor = conn.execute(
                "UPDATE incidents SET production_run_id=?, node_key=?, owner_id=?,"
                " status=?, updated_at=?, incident_json=? "
                "WHERE incident_id=? AND status=?",
                (row[1], row[2], row[3], row[4], row[5], row[6], incident_id, expect_status),
            )
            if cursor.rowcount:
                return True
            exists = conn.execute(
                "SELECT 1 FROM incidents WHERE incident_id=?", (incident_id,)
            ).fetchone()
            if exists is not None:
                return False
            conn.execute(
                "INSERT INTO incidents "
                "(incident_id, production_run_id, node_key, owner_id, status,"
                " updated_at, incident_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                row,
            )
            return True

    def load_incident(self, incident_id: str) -> dict[str, Any] | None:
        with _connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT incident_json FROM incidents WHERE incident_id=?",
                (incident_id,),
            ).fetchone()
        return json.loads(row["incident_json"]) if row else None

    def load_incidents(
        self,
        *,
        production_run_id: str = "",
        include_terminal: bool = True,
        owner_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if production_run_id:
            clauses.append("production_run_id=?")
            params.append(production_run_id)
        if owner_id is not None:
            clauses.append("owner_id=?")
            params.append(owner_id)
        if not include_terminal:
            clauses.append(f"status NOT IN ({','.join('?' * len(_TERMINAL))})")
            params.extend(_TERMINAL)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT incident_json FROM incidents {where} ORDER BY incident_id",
                params,
            ).fetchall()
        return [json.loads(row["incident_json"]) for row in rows]

    def save_attempts(self, history: dict[str, list[float]]) -> None:
        with _connect(self.db_path) as conn:
            for fingerprint, timestamps in (history or {}).items():
                conn.execute(
                    "INSERT OR REPLACE INTO repair_attempts (fingerprint, timestamps_json)"
                    " VALUES (?, ?)",
                    (str(fingerprint), json.dumps([float(t) for t in timestamps])),
                )

    def load_attempts(self) -> dict[str, list[float]]:
        with _connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT fingerprint, timestamps_json FROM repair_attempts"
            ).fetchall()
        return {
            str(row["fingerprint"]): [float(t) for t in json.loads(row["timestamps_json"])]
            for row in rows
        }

    def save_dedupe_hits(self, hits: dict[str, int]) -> None:
        with _connect(self.db_path) as conn:
            for fingerprint, count in (hits or {}).items():
                conn.execute(
                    "INSERT INTO dedupe_events (fingerprint, hits) VALUES (?, ?)"
                    " ON CONFLICT(fingerprint) DO UPDATE SET hits=excluded.hits",
                    (str(fingerprint), int(count)),
                )

    def load_dedupe_hits(self) -> dict[str, int]:
        with _connect(self.db_path) as conn:
            rows = conn.execute("SELECT fingerprint, hits FROM dedupe_events").fetchall()
        return {str(row["fingerprint"]): int(row["hits"]) for row in rows}


class IncidentService:
    """Coordinator + durable store. Tracks, gates, verifies — never executes."""

    def __init__(
        self,
        store: IncidentStore | None = None,
        *,
        project_policy: ProjectRepairPolicy | None = None,
        loop_guard: RepairLoopGuard | None = None,
    ) -> None:
        self.store = store or IncidentStore()
        self.coordinator = SelfHealingCoordinator(
            project_policy=project_policy, loop_guard=loop_guard
        )
        self._lock = threading.Lock()
        self.reload()

    def reload(self) -> int:
        """Restore incidents + attempt history after (re)start. Returns count."""
        incidents = self.store.load_incidents()
        history = self.store.load_attempts()
        dedupe = self.store.load_dedupe_hits()
        self.coordinator.restore_state(incidents, history, dedupe)
        return len(incidents)

    def _persist(self, incident: RepairIncident) -> RepairIncident:
        self.store.save_incident(incident.model_dump(mode="json"))
        self.store.save_attempts(self.coordinator.loop_guard.export_history())
        self.store.save_dedupe_hits(self.coordinator.dedupe_hits)
        return incident

    def _apply(
        self,
        incident_id: str,
        owner_id: str,
        fn: Callable[[str], RepairIncident],
    ) -> RepairIncident:
        """Atomic transition (D4-D): reload fresh row under a process lock,
        check ownership, apply the coordinator transition, and persist with a
        compare-and-swap on the previous status. A concurrent modification
        raises instead of silently winning (no lost updates)."""
        with self._lock:
            row = self.store.load_incident(incident_id)
            if row is None:
                raise IncidentError(f"REPAIR_INCIDENT_UNKNOWN:{incident_id}")
            fresh = RepairIncident.model_validate(row)
            self.coordinator.restore_single(fresh)
            self.coordinator.check_owner(fresh, owner_id)
            updated = fn(incident_id)
            ok = self.store.save_incident(
                updated.model_dump(mode="json"), expect_status=fresh.status.value
            )
            if not ok:
                raise IncidentError("REPAIR_CONCURRENT_MODIFICATION")
            self.store.save_attempts(self.coordinator.loop_guard.export_history())
            return updated

    def open_or_get(
        self,
        *,
        production_run_id: str,
        node_key: str,
        failure: str,
        artifact_id: str = "",
        evidence: dict[str, Any] | None = None,
        owner_id: str = "",
    ) -> RepairIncident:
        with self._lock:
            self.reload()
            incident = self.coordinator.open_or_get(
                production_run_id=production_run_id,
                node_key=node_key,
                failure=failure,
                artifact_id=artifact_id,
                evidence=evidence,
                owner_id=owner_id,
            )
            return self._persist(incident)

    def get(self, incident_id: str, *, owner_id: str = "") -> RepairIncident:
        incident = self.coordinator.get(incident_id, owner_id=owner_id)
        self.coordinator.check_owner(incident, owner_id)
        return incident

    def decline(
        self, incident_id: str, *, reason: str = "user_declined", owner_id: str = ""
    ) -> RepairIncident:
        return self._apply(
            incident_id,
            owner_id,
            lambda iid: self.coordinator.decline_incident(
                iid, reason=reason, owner_id=owner_id
            ),
        )

    def list_incidents(
        self, *, production_run_id: str = "", owner_id: str | None = None
    ) -> list[RepairIncident]:
        incidents = self.store.load_incidents(
            production_run_id=production_run_id, owner_id=owner_id
        )
        return [RepairIncident.model_validate(row) for row in incidents]

    def propose_agent_action(
        self, incident_id: str, action: RepairActionProposal, *, owner_id: str = ""
    ) -> RepairIncident:
        return self._apply(
            incident_id,
            owner_id,
            lambda iid: self.coordinator.propose_agent_action(
                iid, action, owner_id=owner_id
            ),
        )

    def authorize(
        self,
        incident_id: str,
        action: RepairActionProposal,
        *,
        confirmed: bool = False,
        owner_id: str = "",
    ) -> tuple[bool, str]:
        with self._lock:
            self.reload()
            row = self.store.load_incident(incident_id)
            if row is None:
                raise IncidentError(f"REPAIR_INCIDENT_UNKNOWN:{incident_id}")
            fresh = RepairIncident.model_validate(row)
            self.coordinator.restore_single(fresh)
            approved, reason = self.coordinator.authorize(
                incident_id, action, confirmed=confirmed, owner_id=owner_id
            )
            current = self.coordinator.get(incident_id, owner_id=owner_id)
            ok = self.store.save_incident(
                current.model_dump(mode="json"), expect_status=fresh.status.value
            )
            if not ok:
                raise IncidentError("REPAIR_CONCURRENT_MODIFICATION")
            self.store.save_attempts(self.coordinator.loop_guard.export_history())
            return approved, reason

    def record_execution(self, incident_id: str, *, owner_id: str = "") -> RepairIncident:
        return self._apply(
            incident_id,
            owner_id,
            lambda iid: self.coordinator.record_execution(iid, owner_id=owner_id),
        )

    def verify(
        self,
        incident_id: str,
        verification: dict[str, bool],
        *,
        preserved_artifact_ids: tuple[str, ...] = (),
        preserved_intact: bool = True,
        owner_id: str = "",
    ) -> RepairIncident:
        return self._apply(
            incident_id,
            owner_id,
            lambda iid: self.coordinator.verify(
                iid,
                verification,
                preserved_artifact_ids=preserved_artifact_ids,
                preserved_intact=preserved_intact,
                owner_id=owner_id,
            ),
        )


__all__ = ["IncidentService", "IncidentStore", "incident_db_path", "track_task_failure"]


def track_task_failure(
    *,
    production_run_id: str,
    node_key: str,
    failure: str,
    artifact_id: str = "",
    evidence: dict[str, Any] | None = None,
) -> str | None:
    """Best-effort detection seam for task/durable failure paths (D3-C/C1).

    Classifies deterministically and dedupes by fingerprint — repeated
    failures of the same root cause reuse the open incident instead of
    creating a storm. Never raises: incident tracking must not break the
    production flow it observes. Returns the incident id or None.
    """
    try:
        service = IncidentService()
        incident = service.open_or_get(
            production_run_id=production_run_id,
            node_key=node_key,
            failure=failure,
            artifact_id=artifact_id,
            evidence=evidence,
        )
    except Exception:
        return None
    return incident.incident_id
