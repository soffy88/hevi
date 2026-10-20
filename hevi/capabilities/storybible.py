"""Story bible capabilities — foreshadowing ledger + canon consistency.

Registers two ``hevi.capabilities`` entries (CAPABILITY_CONTRACT.md) that put
the file-based story bible (``hevi.storybible``) behind the unified registry,
so long-form writing lines can track setups/payoffs and guard canon without
touching the DB-backed ``hevi.storygraph`` store:

* ``story.foreshadow`` — one capability, ``action``-dispatched:
  ``plant`` / ``payoff`` / ``abandon`` / ``list`` / ``check_overdue`` over the
  per-work foreshadowing ledger. ``check_overdue`` returns the alarm list of
  setups whose expected payoff window has passed at the current chapter.
* ``story.canon_check`` — canon maintenance + pre-writing consistency:
  ``action=add_fact`` records a confirmed fact, ``action=list`` dumps the
  canon ledger, ``action=check`` compares a draft chapter's fact claims
  against canon and reports contradictions (deterministic
  subject/attribute/value rule).

Ledgers are JSON files (atomic temp-file + rename writes) under
``data/storybible/`` or ``$HEVI_STORYBIBLE_DIR``; ``base_dir`` overrides per
call. Every render also writes a report JSON into ``out_dir``; the report
path travels in ``qa["report_json"]`` and its sha256 fingerprints the result,
so a caller can verify the outcome on disk. Ledger validation failures
surface as ``CapabilityError`` — never a fake success.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

_FORESHADOW_ACTIONS = ("plant", "payoff", "abandon", "list", "check_overdue")
_CANON_ACTIONS = ("add_fact", "list", "check")

_FORESHADOW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "work": {"type": "string", "minLength": 1, "description": "Work title (ledger key)"},
        "action": {"type": "string", "enum": list(_FORESHADOW_ACTIONS)},
        "base_dir": {
            "type": "string",
            "description": "Ledger directory override (default: $HEVI_STORYBIBLE_DIR or data/storybible)",
        },
        "entry_id": {"type": "string", "minLength": 1},
        "description": {"type": "string", "minLength": 1},
        "planted_chapter": {"type": "integer", "minimum": 1},
        "expected_start": {
            "type": "integer",
            "minimum": 1,
            "description": "First chapter of the expected payoff window",
        },
        "expected_end": {
            "type": "integer",
            "minimum": 1,
            "description": "Last chapter of the expected payoff window",
        },
        "chapter": {"type": "integer", "minimum": 1, "description": "Payoff chapter (payoff)"},
        "current_chapter": {
            "type": "integer",
            "minimum": 1,
            "description": "Chapter reached by the draft (check_overdue)",
        },
        "status": {"type": "string", "enum": ["planted", "paid_off", "overdue", "abandoned"]},
        "note": {"type": "string"},
    },
    "required": ["work", "action"],
    "additionalProperties": False,
    "anyOf": [
        {
            "properties": {"action": {"const": "plant"}},
            "required": ["description", "planted_chapter", "expected_start", "expected_end"],
        },
        {"properties": {"action": {"const": "payoff"}}, "required": ["entry_id", "chapter"]},
        {"properties": {"action": {"const": "abandon"}}, "required": ["entry_id"]},
        {"properties": {"action": {"const": "check_overdue"}}, "required": ["current_chapter"]},
        {"properties": {"action": {"const": "list"}}},
    ],
}

_CLAIM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "minLength": 1},
        "attribute": {"type": "string", "minLength": 1},
        "value": {"type": "string", "minLength": 1},
        "fact": {"type": "string", "description": "Optional free-text statement of the claim"},
    },
    "required": ["subject", "attribute", "value"],
}

_CANON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "work": {"type": "string", "minLength": 1, "description": "Work title (ledger key)"},
        "action": {"type": "string", "enum": list(_CANON_ACTIONS)},
        "base_dir": {
            "type": "string",
            "description": "Ledger directory override (default: $HEVI_STORYBIBLE_DIR or data/storybible)",
        },
        "fact_id": {"type": "string", "minLength": 1},
        "fact": {"type": "string", "minLength": 1},
        "subject": {"type": "string", "minLength": 1},
        "attribute": {"type": "string", "minLength": 1},
        "value": {"type": "string", "minLength": 1},
        "source_chapter": {"type": "integer", "minimum": 1},
        "tags": {"type": "array", "items": {"type": "string"}},
        "tag": {"type": "string", "description": "Filter for action=list"},
        "claims": {
            "type": "array",
            "minItems": 1,
            "items": _CLAIM_SCHEMA,
            "description": "Draft chapter fact claims (action=check)",
        },
    },
    "required": ["work", "action"],
    "additionalProperties": False,
    "anyOf": [
        {
            "properties": {"action": {"const": "add_fact"}},
            "required": ["fact", "subject", "attribute", "value", "source_chapter"],
        },
        {"properties": {"action": {"const": "check"}}, "required": ["claims"]},
        {"properties": {"action": {"const": "list"}}},
    ],
}


def _base_dir_kwarg(params: dict[str, Any]) -> dict[str, Any]:
    base_dir = params.get("base_dir")
    return {"base_dir": Path(base_dir)} if base_dir else {}


def _write_report(out_dir: Path, filename: str, payload: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    report = out_dir / filename
    report.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _report_result(report: Path, payload: dict[str, Any]) -> CapabilityResult:
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report),
        qa={"report_json": str(report), **payload},
    )


def _render_foreshadow(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.storybible import ForeshadowLedger

    action = params["action"]
    try:
        ledger = ForeshadowLedger(params["work"], **_base_dir_kwarg(params))
        if action == "plant":
            entry = ledger.plant(
                description=params["description"],
                planted_chapter=params["planted_chapter"],
                expected_start=params["expected_start"],
                expected_end=params["expected_end"],
                entry_id=params.get("entry_id"),
                note=params.get("note", ""),
            )
            payload: dict[str, Any] = {"entry": entry.to_dict()}
        elif action == "payoff":
            entry = ledger.payoff(
                params["entry_id"], params["chapter"], note=params.get("note", "")
            )
            payload = {"entry": entry.to_dict()}
        elif action == "abandon":
            entry = ledger.abandon(params["entry_id"], note=params.get("note", ""))
            payload = {"entry": entry.to_dict()}
        elif action == "list":
            entries = ledger.list_entries(status=params.get("status"))
            payload = {"entries": [e.to_dict() for e in entries], "count": len(entries)}
        elif action == "check_overdue":
            overdue = ledger.check_overdue(params["current_chapter"])
            payload = {
                "current_chapter": params["current_chapter"],
                "overdue": [e.to_dict() for e in overdue],
                "count": len(overdue),
            }
        else:  # schema enum guards this; stay loud if it is ever bypassed
            raise CapabilityError(f"story.foreshadow: unknown action {action!r}")
    except ValueError as exc:
        raise CapabilityError(f"story.foreshadow: {exc}") from exc

    payload = {"action": action, "work": params["work"], "ledger_path": str(ledger.path), **payload}
    report = _write_report(Path(out_dir), "foreshadow_report.json", payload)
    return _report_result(report, payload)


def _render_canon_check(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.storybible import CanonLedger, check_claims_against_canon

    action = params["action"]
    try:
        ledger = CanonLedger(params["work"], **_base_dir_kwarg(params))
        if action == "add_fact":
            fact = ledger.add_fact(
                fact=params["fact"],
                subject=params["subject"],
                attribute=params["attribute"],
                value=params["value"],
                source_chapter=params["source_chapter"],
                tags=params.get("tags"),
                fact_id=params.get("fact_id"),
            )
            payload: dict[str, Any] = {"fact": fact.to_dict()}
        elif action == "list":
            facts = ledger.list_facts(tag=params.get("tag"))
            payload = {"facts": [f.to_dict() for f in facts], "count": len(facts)}
        elif action == "check":
            payload = dict(check_claims_against_canon(params["claims"], ledger))
        else:  # schema enum guards this; stay loud if it is ever bypassed
            raise CapabilityError(f"story.canon_check: unknown action {action!r}")
    except ValueError as exc:
        raise CapabilityError(f"story.canon_check: {exc}") from exc

    payload = {"action": action, "work": params["work"], "ledger_path": str(ledger.path), **payload}
    report = _write_report(Path(out_dir), "canon_report.json", payload)
    return _report_result(report, payload)


def register_storybible_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    registered: list[str] = []

    register(
        Capability(
            name="story.foreshadow",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_FORESHADOW_SCHEMA,
            cpu_cost_hint=0.0,  # pure local JSON ledger work
            render=_render_foreshadow,
            description=(
                "Foreshadowing ledger for one work (file-based story bible). "
                "action=plant records a setup with its expected payoff window "
                "(expected_start..expected_end chapters); payoff/abandon move it "
                "through its lifecycle; list queries entries; check_overdue "
                "returns the alarm list of setups still open past their window "
                "at current_chapter. Use to keep long serials from dropping "
                "planted setups."
            ),
            line="storybible",
        )
    )
    registered.append("story.foreshadow")

    register(
        Capability(
            name="story.canon_check",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema=_CANON_SCHEMA,
            cpu_cost_hint=0.0,  # pure local JSON ledger work
            render=_render_canon_check,
            description=(
                "Canon ledger + pre-writing consistency check for one work. "
                "action=add_fact confirms a fact (fact/subject/attribute/value/"
                "source_chapter/tags) into canon — a conflicting value for the "
                "same subject+attribute is rejected; action=list dumps canon; "
                "action=check compares a draft chapter's claims "
                "(subject/attribute/value list) against canon and reports "
                "contradictions (ok=false) before the chapter is written."
            ),
            line="storybible",
        )
    )
    registered.append("story.canon_check")

    return registered
