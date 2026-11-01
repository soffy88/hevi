"""Spend preflight checklist (``qa.spend_preflight_checklist``).

Clean-room rewrite of the *discipline* described in
``hevi-vs-open-3d-skills.md`` section 2.3 (motion-assets): before
any money is spent on generated assets, the payer must see a
plan, an asset list, the model capabilities the plan relies on,
and a cost calibration -- and must confirm explicitly. This
module judges the preflight *plan* only; it calls no model, sets
no price, and spends nothing.

Budget discipline is reused, not reinvented: the storyboard /
confirmation / smoke-run rule is ``pipeline.spend_brake``
(``hevi.capabilities.spend_brake.gate_spend``), and this gate
requires that gate to allow the spend. No second budget
mechanism, no price table, and no model account is introduced
here. Cost numbers are caller-supplied calibration values only;
this module never invents a price for a model.

Failure contract: a malformed plan (not a JSON object, missing
``preflight`` section) raises :class:`CapabilityError`. A
well-formed plan missing any checklist item returns
``verdict: "fail"`` with named issues; it never raises.
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
from hevi.capabilities.spend_brake import gate_spend

_Registered = False

_ASSET_FIELDS = ("name", "prompt", "model", "cost_estimate")


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    issue.update(extra)
    return issue


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_spend_preflight(plan: Any) -> dict[str, Any]:
    """Judge one spend preflight plan against the checklist."""
    if not isinstance(plan, dict):
        raise CapabilityError(
            "qa.spend_preflight_checklist: plan must be a JSON object"
        )
    preflight = plan.get("preflight")
    if not isinstance(preflight, dict):
        raise CapabilityError(
            "qa.spend_preflight_checklist: plan requires a 'preflight' object"
        )
    issues: list[dict[str, Any]] = []

    description = preflight.get("plan")
    if isinstance(description, dict):
        description_ok = bool(description)
    elif isinstance(description, str):
        description_ok = bool(description.strip())
    else:
        description_ok = False
    if not description_ok:
        issues.append(
            _issue(
                "plan_missing",
                "preflight must include a non-empty 'plan' describing "
                "what will be generated and in what order",
            )
        )

    assets = preflight.get("asset_list")
    if not isinstance(assets, list) or not assets:
        issues.append(
            _issue(
                "asset_list_missing",
                "preflight must include a non-empty 'asset_list'; one "
                "entry per asset to be generated",
            )
        )
        assets = []
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            issues.append(
                _issue(
                    "asset_not_object",
                    f"asset_list entry {index} must be an object",
                    index=index,
                )
            )
            continue
        for field in _ASSET_FIELDS:
            value = asset.get(field)
            if field == "cost_estimate":
                if not _is_num(value) or float(value) < 0:
                    issues.append(
                        _issue(
                            "asset_cost_missing",
                            f"asset {index} must carry a caller-supplied "
                            "non-negative numeric 'cost_estimate'; prices "
                            "are never invented by this gate",
                            index=index,
                            asset=asset.get("name"),
                        )
                    )
            elif not isinstance(value, str) or not value.strip():
                issues.append(
                    _issue(
                        "asset_field_missing",
                        f"asset {index} must carry a non-empty {field!r}",
                        index=index,
                        field=field,
                    )
                )

    capability = preflight.get("model_capability")
    if not isinstance(capability, dict) or not capability:
        issues.append(
            _issue(
                "model_capability_missing",
                "preflight must include a non-empty 'model_capability' "
                "object stating, per model used, which capabilities the "
                "plan relies on",
            )
        )

    calibration = preflight.get("cost_calibration")
    if not isinstance(calibration, dict):
        issues.append(
            _issue(
                "cost_calibration_missing",
                "preflight must include a 'cost_calibration' object "
                "with a caller-supplied total and its basis",
            )
        )
        calibration = {}
    total = calibration.get("total_estimate")
    if not _is_num(total) or float(total) < 0:
        issues.append(
            _issue(
                "cost_calibration_total_missing",
                "cost_calibration must carry a caller-supplied "
                "non-negative numeric 'total_estimate'",
                total_estimate=total,
            )
        )
    basis = calibration.get("basis")
    if not isinstance(basis, str) or not basis.strip():
        issues.append(
            _issue(
                "cost_calibration_basis_missing",
                "cost_calibration must name its 'basis' (how the total "
                "was calibrated); an unexplained total is not a "
                "calibration",
            )
        )

    confirmed = preflight.get("confirmed")
    if confirmed is not True:
        issues.append(
            _issue(
                "confirmation_missing",
                "spending requires an explicit confirmation: "
                "confirmed must be exactly true; a missing field, the "
                "string 'yes', or 1 is not confirmation",
                confirmed=confirmed,
            )
        )
    confirmer = preflight.get("confirmed_by")
    if not isinstance(confirmer, str) or not confirmer.strip():
        issues.append(
            _issue(
                "confirmer_missing",
                "preflight must name who confirmed in 'confirmed_by'",
            )
        )

    brake = preflight.get("spend_brake")
    if not isinstance(brake, dict):
        issues.append(
            _issue(
                "spend_brake_missing",
                "preflight must carry a 'spend_brake' block (storyboard, "
                "confirmed, smoke_passed, batch_size) judged by "
                "pipeline.spend_brake; this gate adds no second budget "
                "mechanism",
            )
        )
    else:
        decision = gate_spend(
            brake.get("storyboard"),
            confirmed=brake.get("confirmed"),
            smoke_passed=brake.get("smoke_passed"),
            batch_size=brake.get("batch_size"),
        )
        if not decision["allowed"]:
            issues.append(
                _issue(
                    "spend_brake_refused",
                    "pipeline.spend_brake refuses this spend: "
                    + "; ".join(decision["blockers"]),
                    blockers=decision["blockers"],
                )
            )
    verdict = "fail" if issues else "pass"
    return {
        "verdict": verdict,
        "issues": issues,
        "note": (
            "This gate judges the preflight plan only. It calls no "
            "model and spends nothing; prices are caller-supplied "
            "calibration values, and the budget rule is "
            "pipeline.spend_brake."
        ),
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float,
            aspect: str, seed: int) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_spend_preflight(params.get("plan"))
    report_path = out_dir / "spend_preflight_checklist.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"],
            "ok": report["verdict"] == "pass"},
    )


def register_spend_preflight_checklist_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.spend_preflight_checklist",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {"plan": {"type": "object"}},
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            description=(
                "Spend preflight checklist (open-3d-skills "
                "motion-assets discipline, clean-room): before "
                "spending, the plan must show a generation plan, an "
                "asset list with caller-supplied cost estimates, the "
                "model capabilities relied on, a cost calibration with "
                "its basis, and an explicit confirmation; the budget "
                "rule is reused from pipeline.spend_brake. Judges "
                "plans only; calls no model, spends nothing. See "
                "OPEN_3D_SKILLS_ATTRIBUTION.md."
            ),
            line="qa",
        )
    )
    return ["qa.spend_preflight_checklist"]


register_spend_preflight_checklist_capabilities_once()
