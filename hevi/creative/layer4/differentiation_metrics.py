"""D4-F: differentiation product metrics — read-only over canonical state.

Every metric below is computed from the canonical stores (IdentityStore,
IncidentStore); there is no second analytics truth. Definitions:

- IDENTITY_REUSE_RATE: bindings per identity (cross-project reuse intensity).
- CONTINUITY_BLOCKS_CAUGHT: persisted BLOCK gate decisions.
- CONTINUITY_WARNINGS_OVERRIDDEN: WARN decisions with an explicit overrider.
- AUTO_SAFE_REPAIRS: RESOLVED incidents whose executed action was AUTO_SAFE.
- PAID_REPAIRS_CONFIRMED: RESOLVED incidents whose action could bill.
- FAILED_REPAIRS: terminal REPAIR_FAILED incidents.
- REPAIR_MEAN_ATTEMPTS: mean attempts over closed (resolved+failed) incidents.
- DUPLICATE_BILLING_PREVENTED: incident opens collapsed by fingerprint
  dedupe (each hit is a duplicate incident that never became a repair).
- ARTIFACTS_PRESERVED_BY_REPAIR: preserved artifact ids recorded on RESOLVED.
"""

from __future__ import annotations

from typing import Any

from hevi.creative.layer4.identity_store import IdentityStore
from hevi.creative.layer4.incident_store import IncidentStore


def compute_metrics(
    identity_store: IdentityStore, incident_store: IncidentStore, *, owner_id: str = ""
) -> dict[str, float | int]:
    scan = _scan_identity_store(identity_store, owner_id=owner_id)
    identities = scan["identities"]
    bindings = scan["bindings"]
    blocks = warns = 0
    for decision in scan["decisions"]:
        if decision.get("verdict") == "block":
            blocks += 1
        elif decision.get("verdict") == "warn" and decision.get("overridden_by"):
            warns += 1

    auto_safe = paid = failed = 0
    attempts_total = 0
    closed = 0
    preserved = 0
    incidents = (
        incident_store.load_incidents(owner_id=owner_id)
        if owner_id
        else incident_store.load_incidents()
    )
    for row in incidents:
        status = str(row.get("status") or "")
        if status == "resolved":
            closed += 1
            attempts_total += int(row.get("attempts") or 0)
            selected = (row.get("selected_action") or {}) if isinstance(
                row.get("selected_action"), dict) else {}
            if str(selected.get("policy") or "") == "auto_safe":
                auto_safe += 1
            if float(selected.get("estimated_cost_usd") or 0.0) > 0.0:
                paid += 1
            evidence = row.get("evidence") or {}
            if isinstance(evidence, dict) and evidence.get("preserved_intact"):
                preserved += len(evidence.get("preserved_artifact_ids") or [])
        elif status == "repair_failed":
            closed += 1
            attempts_total += int(row.get("attempts") or 0)
            failed += 1

    dedupe_prevented = sum(incident_store.load_dedupe_hits().values())
    return {
        "IDENTITY_REUSE_RATE": round(bindings / identities, 3) if identities else 0.0,
        "CONTINUITY_BLOCKS_CAUGHT": blocks,
        "CONTINUITY_WARNINGS_OVERRIDDEN": warns,
        "AUTO_SAFE_REPAIRS": auto_safe,
        "PAID_REPAIRS_CONFIRMED": paid,
        "FAILED_REPAIRS": failed,
        "REPAIR_MEAN_ATTEMPTS": round(attempts_total / closed, 3) if closed else 0.0,
        "DUPLICATE_BILLING_PREVENTED": dedupe_prevented,
        "ARTIFACTS_PRESERVED_BY_REPAIR": preserved,
    }


def _scan_identity_store(store: IdentityStore, *, owner_id: str = "") -> dict[str, Any]:
    """Owner-scoped (or global) scan using the store's own SQL."""
    import sqlite3

    identities = 0
    bindings = 0
    decisions: list[dict[str, Any]] = []
    where = " WHERE owner_id=?" if owner_id else ""
    params: tuple[Any, ...] = (owner_id,) if owner_id else ()
    with sqlite3.connect(str(store.db_path), timeout=30.0) as conn:
        conn.row_factory = sqlite3.Row
        try:
            identities = int(
                conn.execute(
                    f"SELECT COUNT(*) AS n FROM identities{where}", params
                ).fetchone()["n"]
            )
            bindings = int(
                conn.execute(
                    f"SELECT COUNT(*) AS n FROM bindings{where}", params
                ).fetchone()["n"]
            )
            rows = conn.execute(
                f"SELECT decision_json FROM continuity_decisions{where}", params
            ).fetchall()
        except Exception:
            return {"identities": 0, "bindings": 0, "decisions": []}
    import json

    for row in rows:
        try:
            decisions.append(json.loads(row["decision_json"]))
        except Exception:
            continue
    return {"identities": identities, "bindings": bindings, "decisions": decisions}


__all__ = ["compute_metrics"]
