"""Pre-spend brake (``pipeline.spend_brake``).

A paid generation call is the one place where a sloppy plan turns
directly into money burned, so this gate sits in front of it and
refuses to approve anything that skipped the cheap steps first:

1. A storyboard table must exist, with one row per shot, each row
   naming its shot id, what the shot shows, and how long it runs.
2. A human must have confirmed that table, in a machine-readable
   field: ``confirmed`` must be exactly ``True``. The string
   ``"true"``, ``1``, or a missing field is not confirmation.
3. One single frame (for an image job) or one single segment (for
   a video job) must have run clean first -- the smoke run -- before
   any batch is approved. The smoke run itself is a batch of one,
   so it needs the storyboard and the confirmation but not a prior
   smoke result.

This module approves or refuses; it never calls a generator itself
and never spends anything. A refusal names the exact missing step
(``confirmed``, ``storyboard``, or ``smoke``) so the caller knows
what to fix instead of guessing.
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

_REQUIRED_ROW_FIELDS = ("shot_id", "visual", "duration_sec")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_storyboard(rows: Any) -> dict[str, Any]:
    """Check a storyboard table row by row.

    Returns a report; it does not raise on a bad table, because the
    gate needs to list every broken row at once.
    """
    problems: list[dict[str, Any]] = []
    checked = 0
    if not isinstance(rows, list) or not rows:
        return {
            "ok": False,
            "rows_checked": 0,
            "problems": [{
                "row_index": None,
                "missing_fields": ["storyboard"],
                "detail": "storyboard: no storyboard table was supplied (empty or not a list)",
            }],
        }
    for index, row in enumerate(rows):
        checked += 1
        if not isinstance(row, dict):
            problems.append({
                "row_index": index,
                "missing_fields": list(_REQUIRED_ROW_FIELDS),
                "detail": "storyboard: row is not an object",
            })
            continue
        missing = [f for f in _REQUIRED_ROW_FIELDS
                   if row.get(f) in (None, "")]
        if not _is_number(row.get("duration_sec")) or (
                _is_number(row.get("duration_sec"))
                and float(row["duration_sec"]) <= 0):
            if "duration_sec" not in missing:
                missing.append("duration_sec")
        if missing:
            problems.append({
                "row_index": index,
                "shot_id": row.get("shot_id"),
                "missing_fields": missing,
                "detail": "storyboard: row is missing or has an invalid "
                          f"field: {', '.join(missing)}",
            })
    return {"ok": not problems, "rows_checked": checked, "problems": problems}


def gate_spend(
    storyboard: Any,
    *,
    confirmed: Any,
    smoke_passed: Any,
    batch_size: Any,
) -> dict[str, Any]:
    """Decide whether a paid generation batch may run.

    ``confirmed`` must be exactly ``True``; ``smoke_passed`` must be
    exactly ``True`` for any batch larger than one. A batch of one
    is the smoke run itself and is exempt from the smoke rule.
    """
    blockers: list[str] = []
    board = validate_storyboard(storyboard)
    if not board["ok"]:
        blockers.append(
            "storyboard: storyboard table is missing or has broken rows; "
            "fix every row (shot_id, visual, duration_sec) before spending"
        )
    if confirmed is not True:
        blockers.append(
            "confirmed: no machine-readable confirmation (confirmed=true "
            "required); a missing field, the string 'true', or 1 is not "
            "confirmation, so the batch is refused"
        )
    if not _is_number(batch_size) or int(batch_size) != batch_size \
            or int(batch_size) < 1:
        blockers.append(
            "batch_size: batch_size must be a whole number of at least 1"
        )
        batch = 0
    else:
        batch = int(batch_size)
    if batch > 1 and smoke_passed is not True:
        blockers.append(
            "smoke: no passing single-frame/single-segment smoke run on "
            "record; run one frame or one segment clean first, then batch"
        )
    mode = "smoke" if batch == 1 else "batch"
    return {
        "allowed": not blockers,
        "mode": mode,
        "batch_size": batch,
        "blockers": blockers,
        "storyboard": board,
    }


def authorize_spend(
    storyboard: Any,
    *,
    confirmed: Any,
    smoke_passed: Any,
    batch_size: Any,
    estimated_unit_cost: Any = None,
) -> dict[str, Any]:
    """Approve a spend, or refuse it loudly.

    Raises CapabilityError listing every blocker when the gate
    refuses, so a caller can never mistake a refusal for approval.
    """
    decision = gate_spend(
        storyboard, confirmed=confirmed,
        smoke_passed=smoke_passed, batch_size=batch_size,
    )
    if not decision["allowed"]:
        raise CapabilityError(
            "pipeline.spend_brake: paid generation refused: "
            + "; ".join(decision["blockers"])
        )
    approval: dict[str, Any] = {
        "approved": True,
        "mode": decision["mode"],
        "batch_size": decision["batch_size"],
        "rows_checked": decision["storyboard"]["rows_checked"],
        "note": "Approval covers this storyboard and batch only; a new "
                "storyboard or a larger batch needs a fresh check.",
    }
    if estimated_unit_cost is not None:
        if not _is_number(estimated_unit_cost) \
                or float(estimated_unit_cost) < 0:
            raise CapabilityError(
                "pipeline.spend_brake: estimated_unit_cost must be a "
                "non-negative number"
            )
        approval["estimated_unit_cost"] = float(estimated_unit_cost)
        approval["estimated_total_cost"] = (
            float(estimated_unit_cost) * decision["batch_size"]
        )
    return approval


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
             aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    approval = authorize_spend(
        params.get("storyboard"),
        confirmed=params.get("confirmed"),
        smoke_passed=params.get("smoke_passed"),
        batch_size=params.get("batch_size"),
        estimated_unit_cost=params.get("estimated_unit_cost"),
    )
    report_path = out_dir / "spend_brake_report.json"
    report_path.write_text(
        json.dumps(approval, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "approved": True,
            "mode": approval["mode"]},
    )


def register_spend_brake_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="pipeline.spend_brake",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "storyboard": {"type": "array"},
                    "confirmed": {"type": "boolean"},
                    "smoke_passed": {"type": "boolean"},
                    "batch_size": {"type": "integer", "minimum": 1},
                    "estimated_unit_cost": {"type": "number", "minimum": 0},
                },
                "required": ["storyboard", "confirmed", "smoke_passed",
                             "batch_size"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            description=(
                "Pre-spend brake: a paid generation batch is approved "
                "only when a complete storyboard table exists, "
                "confirmed is exactly true, and (for batches larger "
                "than one) a single-frame/single-segment smoke run has "
                "passed. Unconfirmed, storyboard-less, or unsmoked "
                "batches are refused with the missing step named. "
                "This gate calls no generator and spends nothing."
            ),
            line="pipeline",
            has_media_output=False,
        )
    )
    return ["pipeline.spend_brake"]


register_spend_brake_capabilities_once()


def check_spend_approval(
    params: dict[str, Any], *, capability: str
) -> dict[str, Any]:
    """Consult the spend gate for one generation call.

    The caller supplies an optional ``spend_approval`` block with
    ``{storyboard, confirmed, smoke_passed, batch_size,
    estimated_unit_cost}``. When the block is present,
    ``authorize_spend`` must approve or the call is refused here --
    before any key is read, any network call is made, or any GPU
    work starts -- by the CapabilityError it raises. When the block
    is absent, spending responsibility stays caller-side: the call
    proceeds and the returned verdict records
    ``spend_gate_not_consulted`` so no audit trail can mistake the
    call for gate-approved.
    """
    approval = params.get("spend_approval") if isinstance(params, dict) else None
    if not isinstance(approval, dict):
        return {
            "consulted": False,
            "spend_gate_not_consulted": True,
            "note": (
                f"{capability}: no spend_approval block supplied; "
                "spending responsibility stays caller-side"
            ),
        }
    decision = authorize_spend(
        approval.get("storyboard"),
        confirmed=approval.get("confirmed"),
        smoke_passed=approval.get("smoke_passed"),
        batch_size=approval.get("batch_size", 1),
        estimated_unit_cost=approval.get("estimated_unit_cost"),
    )
    return {
        "consulted": True,
        "approved": True,
        "mode": decision["mode"],
        "batch_size": decision["batch_size"],
    }
