"""Post-batch spend ledger (``pipeline.spend_ledger``).

This is the second half of ``pipeline.spend_brake``. The brake sits
before spending; this ledger sits around and after it:

1. Freeze before batch. ``freeze_batch`` re-runs the spend-brake
   gate (complete storyboard, ``confirmed`` exactly ``True``,
   single-frame/segment smoke for batches larger than one) and only
   then records a frozen batch: frozen parameters, batch size and
   the estimated total. An unconfirmed batch is never written to
   the ledger at all.
2. Settle after batch. ``settle_batch`` takes the caller-supplied
   actual total and compares it with the frozen estimate. When the
   estimate was higher, the difference is refunded and recorded as
   ``refund``; when the actual is higher, the overrun is recorded
   as ``overrun`` (no refund is invented, and no extra charge is
   silently approved -- the numbers are just recorded).
3. Failed items keep their originals. ``record_failed_item`` marks
   an item ``failed`` and stores its original input. ``retrieve_``
   ``failed_item`` returns that original input, and
   ``generation_route`` for a failed item always returns
   ``return_original`` with ``generate: False`` -- a failed item
   must never be silently rerouted to the ordinary generation path.

Pricing discipline: this module contains no price table, no default
price and no fallback rate. Every amount is computed from a
unit price supplied by the caller at freeze time (``unit_price``);
a freeze without a caller-supplied unit price is refused, naming
that the price must come from the caller. The ledger never invents
a price, and the caller-supplied price is stored with the batch so
the arithmetic is auditable.
"""

from __future__ import annotations

import copy
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
from hevi.capabilities.spend_brake import authorize_spend

_Registered = False

LEDGER_FILENAME = "spend_ledger.json"


def _fail(message: str) -> None:
    raise CapabilityError(f"pipeline.spend_ledger: {message}")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _round(value: float) -> float:
    return round(float(value), 6)


def _load_ledger(path: Path) -> dict[str, Any]:
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            _fail(f"ledger is not valid JSON: {path}")
        if not isinstance(data, dict) or "batches" not in data:
            _fail(f"ledger has no batches list: {path}")
        return data
    return {"capability": "pipeline.spend_ledger", "batches": []}


def _save_ledger(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def _find_batch(data: dict[str, Any], batch_id: str) -> dict[str, Any]:
    for batch in data["batches"]:
        if batch.get("batch_id") == batch_id:
            return batch
    _fail(
        f"batch not found in ledger: {batch_id!r}; known: "
        f"{[b.get('batch_id') for b in data['batches']]}"
    )


def freeze_batch(
    ledger_path: Path,
    *,
    batch_id: str,
    storyboard: Any,
    confirmed: Any,
    smoke_passed: Any,
    batch_size: Any,
    unit_price: Any,
) -> dict[str, Any]:
    """Freeze parameters + estimate, under the spend-brake gate.

    Raises (and writes nothing) when the brake refuses -- in
    particular when ``confirmed`` is not exactly ``True`` -- or when
    no caller-supplied unit price is given.
    """
    path = Path(ledger_path)
    if not batch_id or not isinstance(batch_id, str):
        _fail("freeze_batch: batch_id must be a non-empty string")
    if unit_price is None:
        _fail(
            "freeze_batch: unit_price must be supplied by the caller; "
            "this ledger contains no price table and invents no price"
        )
    if not _is_number(unit_price) or float(unit_price) < 0:
        _fail("freeze_batch: unit_price must be a non-negative number")
    # The brake is the authority on confirmation / storyboard / smoke.
    # authorize_spend raises naming the blocker; nothing is recorded
    # when it raises, so an unconfirmed batch never reaches the ledger.
    approval = authorize_spend(
        storyboard, confirmed=confirmed, smoke_passed=smoke_passed,
        batch_size=batch_size,
    )
    data = _load_ledger(path)
    if any(b.get("batch_id") == batch_id for b in data["batches"]):
        _fail(f"freeze_batch: batch_id already frozen: {batch_id!r}")
    batch = {
        "batch_id": batch_id,
        "status": "frozen",
        "frozen_params": {
            "storyboard": copy.deepcopy(storyboard),
            "batch_size": approval["batch_size"],
            "mode": approval["mode"],
            "rows_checked": approval["rows_checked"],
        },
        "unit_price_caller_supplied": float(unit_price),
        "estimated_total": _round(float(unit_price) * approval["batch_size"]),
        "actual_total": None,
        "refund": 0.0,
        "overrun": 0.0,
        "items": [],
    }
    data["batches"].append(batch)
    _save_ledger(path, data)
    return copy.deepcopy(batch)


def settle_batch(
    ledger_path: Path, *, batch_id: str, actual_total: Any
) -> dict[str, Any]:
    """Settle a frozen batch against its caller-supplied actual total."""
    path = Path(ledger_path)
    if not _is_number(actual_total) or float(actual_total) < 0:
        _fail("settle_batch: actual_total must be a non-negative number")
    data = _load_ledger(path)
    batch = _find_batch(data, batch_id)
    if batch["status"] != "frozen":
        _fail(
            f"settle_batch: batch {batch_id!r} has status "
            f"{batch['status']!r}, not 'frozen'; a batch settles once"
        )
    actual = _round(float(actual_total))
    estimated = float(batch["estimated_total"])
    batch["actual_total"] = actual
    batch["refund"] = _round(estimated - actual) if actual < estimated else 0.0
    batch["overrun"] = _round(actual - estimated) if actual > estimated else 0.0
    batch["status"] = "settled"
    _save_ledger(path, data)
    return copy.deepcopy(batch)


def record_failed_item(
    ledger_path: Path,
    *,
    batch_id: str,
    item_id: str,
    original_input: Any,
) -> dict[str, Any]:
    """Mark one batch item failed and keep its original input."""
    path = Path(ledger_path)
    data = _load_ledger(path)
    batch = _find_batch(data, batch_id)
    item = {
        "item_id": item_id,
        "status": "failed",
        "original_input": copy.deepcopy(original_input),
    }
    batch["items"] = [
        i for i in batch.get("items", []) if i.get("item_id") != item_id
    ]
    batch["items"].append(item)
    _save_ledger(path, data)
    return copy.deepcopy(item)


def retrieve_failed_item(
    ledger_path: Path, *, batch_id: str, item_id: str
) -> dict[str, Any]:
    """Return a failed item's original input; never generate instead."""
    data = _load_ledger(Path(ledger_path))
    batch = _find_batch(data, batch_id)
    for item in batch.get("items", []):
        if item.get("item_id") == item_id:
            if item.get("status") != "failed":
                _fail(
                    f"retrieve_failed_item: item {item_id!r} in batch "
                    f"{batch_id!r} has status {item.get('status')!r}, "
                    "not 'failed'"
                )
            return {
                "item_id": item_id,
                "status": "failed",
                "original_input": copy.deepcopy(item.get("original_input")),
                "route": "return_original",
                "generate": False,
            }
    _fail(
        f"retrieve_failed_item: item {item_id!r} not found in batch "
        f"{batch_id!r}"
    )


def generation_route(item_status: str) -> dict[str, Any]:
    """Route for one item. A failed item never routes to generation."""
    if item_status == "failed":
        return {
            "route": "return_original",
            "generate": False,
            "reason": (
                "Item is failed: return its original input; it must not "
                "be automatically rerouted to the ordinary generation path."
            ),
        }
    return {
        "route": "normal_generation",
        "generate": True,
        "reason": "Item is not failed.",
    }


def ledger_summary(ledger_path: Path) -> dict[str, Any]:
    data = _load_ledger(Path(ledger_path))
    batches = data["batches"]
    return {
        "batches": len(batches),
        "frozen": sum(1 for b in batches if b["status"] == "frozen"),
        "settled": sum(1 for b in batches if b["status"] == "settled"),
        "total_estimated": _round(sum(float(b["estimated_total"]) for b in batches)),
        "total_actual": _round(sum(
            float(b["actual_total"]) for b in batches
            if b.get("actual_total") is not None
        )),
        "total_refund": _round(sum(float(b.get("refund", 0.0)) for b in batches)),
        "total_overrun": _round(sum(float(b.get("overrun", 0.0)) for b in batches)),
        "failed_items": sum(
            1 for b in batches for i in b.get("items", [])
            if i.get("status") == "failed"
        ),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
             aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    action = params.get("action", "freeze")
    ledger_path = Path(params["ledger_path"])
    if action == "freeze":
        result: dict[str, Any] = {
            "capability": "pipeline.spend_ledger",
            "batch": freeze_batch(
                ledger_path,
                batch_id=str(params["batch_id"]),
                storyboard=params.get("storyboard"),
                confirmed=params.get("confirmed"),
                smoke_passed=params.get("smoke_passed"),
                batch_size=params.get("batch_size"),
                unit_price=params.get("unit_price"),
            ),
        }
    elif action == "settle":
        result = {
            "capability": "pipeline.spend_ledger",
            "batch": settle_batch(
                ledger_path, batch_id=str(params["batch_id"]),
                actual_total=params.get("actual_total"),
            ),
        }
    elif action == "fail":
        result = {
            "capability": "pipeline.spend_ledger",
            "item": record_failed_item(
                ledger_path, batch_id=str(params["batch_id"]),
                item_id=str(params["item_id"]),
                original_input=params.get("original_input"),
            ),
        }
    elif action == "retrieve":
        result = {
            "capability": "pipeline.spend_ledger",
            "item": retrieve_failed_item(
                ledger_path, batch_id=str(params["batch_id"]),
                item_id=str(params["item_id"]),
            ),
        }
    elif action == "summary":
        result = {
            "capability": "pipeline.spend_ledger",
            **ledger_summary(ledger_path),
        }
    else:
        _fail(
            f"unknown action {action!r}; known: freeze, settle, fail, "
            "retrieve, summary"
        )
    report_path = out_dir / "spend_ledger_report.json"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "result": result},
    )


def register_spend_ledger_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="pipeline.spend_ledger",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "ledger_path": {"type": "string"},
                    "action": {"type": "string", "enum": [
                        "freeze", "settle", "fail", "retrieve",
                        "summary"]},
                    "batch_id": {"type": "string"},
                    "storyboard": {"type": "array"},
                    "confirmed": {"type": "boolean"},
                    "smoke_passed": {"type": "boolean"},
                    "batch_size": {"type": "integer", "minimum": 1},
                    "unit_price": {"type": "number", "minimum": 0},
                    "actual_total": {"type": "number", "minimum": 0},
                    "item_id": {"type": "string"},
                    "original_input": {},
                },
                "required": ["ledger_path"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Post-batch spend ledger completing pipeline.spend_brake: "
                "freeze parameters and caller-supplied estimate before a "
                "batch (unconfirmed batches are never recorded), settle "
                "against the actual total with overcharge refunded, and "
                "failed items marked failed with their original input "
                "retrievable -- never silently rerouted to ordinary "
                "generation. No price table lives in this module; every "
                "amount is computed from a caller-supplied unit price."
            ),
            line="pipeline",
        )
    )
    return ["pipeline.spend_ledger"]


register_spend_ledger_capabilities_once()
