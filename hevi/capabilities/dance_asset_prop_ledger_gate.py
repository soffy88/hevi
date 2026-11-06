"""Dance asset and prop ledger gate (``qa.dance_asset_prop_ledger_gate``).

Clean-room restatement of the dance MV methodology (see
``DANCE_MV_METHODOLOGY_ATTRIBUTION.md``): before any
segment is written, the film's assets and props are
written down in a ledger. Each asset names its one
source and says what may change about it and what may
never change. Each prop names its source, its count,
its place, the first and last segment it appears in,
whether it may be picked up, and whether it may stay
continuous across shots. Nothing may appear on screen
that the ledger does not already hold. This gate judges
the ledger only. It draws nothing, renders nothing, and
spends nothing: ``executed_here`` is always false.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

ASSET_FIELDS: tuple[str, ...] = ("name", "source", "changeable", "unchangeable")
PROP_FIELDS: tuple[str, ...] = (
    "name",
    "source",
    "quantity",
    "position",
    "first_appearance",
    "last_appearance",
    "may_be_held",
    "may_persist_across_shots",
)


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_dance_asset_prop_ledger(ledger: Any) -> dict[str, Any]:
    """Validate an asset and prop ledger for one dance MV.

    Verdicts are ``pass`` / ``fail`` only. The ledger fails
    when an asset is missing a field, when an asset names
    nothing that may never change, when a prop is missing
    a field or carries a count below one, or when any prop
    appears that the ledger did not already hold.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(ledger, dict):
        return fail("ledger_not_object", "asset ledger must be a JSON object")
    assets = ledger.get("assets")
    if not isinstance(assets, list) or not assets:
        return fail("assets_missing", "ledger must carry at least one asset")
    for position, asset in enumerate(assets):
        if not isinstance(asset, dict):
            return fail(
                "asset_not_object",
                f"asset {position} must be an object",
            )
        for field in ASSET_FIELDS:
            if field not in asset:
                return fail(
                    "asset_field_missing",
                    f"asset {position} is missing {field}",
                )
        if not isinstance(asset["name"], str) or not asset["name"].strip():
            return fail(
                "asset_name_missing",
                f"asset {position} must name the asset",
            )
        if not isinstance(asset["source"], str) or not asset["source"].strip():
            return fail(
                "asset_source_missing",
                f"asset {position} must name its one source",
            )
        if not isinstance(asset["changeable"], list):
            return fail(
                "asset_changeable_missing",
                f"asset {position} must list what may change",
            )
        if not isinstance(asset["unchangeable"], list) or not asset["unchangeable"]:
            return fail(
                "asset_unchangeable_empty",
                f"asset {position} must name at least one thing that may never change",
            )
    props = ledger.get("props")
    if not isinstance(props, list):
        return fail("props_missing", "ledger must carry a props list")
    for position, prop in enumerate(props):
        if not isinstance(prop, dict):
            return fail(
                "prop_not_object",
                f"prop {position} must be an object",
            )
        for field in PROP_FIELDS:
            if field not in prop:
                return fail(
                    "prop_field_missing",
                    f"prop {position} is missing {field}",
                )
        if not isinstance(prop["name"], str) or not prop["name"].strip():
            return fail(
                "prop_name_missing",
                f"prop {position} must name the prop",
            )
        quantity = prop["quantity"]
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            return fail(
                "prop_quantity_invalid",
                f"prop {position} must carry a count of at least one",
            )
        if not isinstance(prop["position"], str) or not prop["position"].strip():
            return fail(
                "prop_position_missing",
                f"prop {position} must state its place",
            )
        if not isinstance(prop["first_appearance"], str) or not prop["first_appearance"].strip():
            return fail(
                "prop_first_appearance_missing",
                f"prop {position} must state where it first appears",
            )
        if not isinstance(prop["last_appearance"], str) or not prop["last_appearance"].strip():
            return fail(
                "prop_last_appearance_missing",
                f"prop {position} must state where it last appears",
            )
        if not isinstance(prop["may_be_held"], bool):
            return fail(
                "prop_may_be_held_missing",
                f"prop {position} must say whether it may be picked up",
            )
        if not isinstance(prop["may_persist_across_shots"], bool):
            return fail(
                "prop_persist_missing",
                f"prop {position} must say whether it may stay continuous across shots",
            )
    added = ledger.get("added_props")
    if not isinstance(added, list):
        return fail(
            "added_props_missing",
            "ledger must carry an added-props list, empty when clean",
        )
    if added:
        return fail(
            "prop_added_undeclared",
            f"{len(added)} prop(s) appear on screen that the ledger did not already hold",
        )
    return {
        "verdict": "pass",
        "ok": True,
        "issues": [],
        "executed_here": False,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_dance_asset_prop_ledger(params.get("ledger"))
    report_path = out_dir / "dance_asset_prop_ledger_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_dance_asset_prop_ledger_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.dance_asset_prop_ledger_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "ledger": {"type": "object"},
                },
                "required": ["ledger"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Dance asset and prop ledger gate: one source and "
                "changeable versus unchangeable facts per asset, and "
                "a full record per prop; nothing appears undeclared."
            ),
        )
    )
    return ["qa.dance_asset_prop_ledger_gate"]


__all__ = [
    "ASSET_FIELDS",
    "PROP_FIELDS",
    "check_dance_asset_prop_ledger",
    "register_dance_asset_prop_ledger_gate_capabilities_once",
]
