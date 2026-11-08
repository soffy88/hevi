"""Variant reuse gate (``qa.variant_reuse_gate``).

Discipline gate only. A variant is produced by changing lines
in the project and re-running only what changed: unchanged
assets are reused under their recorded build ids, and the
re-run scope names only the changed parts. Claiming reuse for
a changed asset, reusing without a build id, or re-running
everything while calling it a reuse all fail. This gate judges
the variant plan only and renders nothing. See
HYPIT_ATTRIBUTION.md. Method restated in our own words.
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


def _issue(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def check_variant_reuse(plan: Any) -> dict[str, Any]:
    """Check a variant plan for honest change-and-reuse claims.

    Returns a report dict with ``verdict`` pass/fail, ``ok``,
    and ``issues``. Unchanged assets without a reuse declaration
    or build id, changed assets claimed as reused, and a
    re-run scope that reaches beyond the changed assets all
    fail.
    """
    issues: list[dict[str, str]] = []
    if not isinstance(plan, dict):
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [_issue("plan_not_object", "plan must be a JSON object")],
        }
    base_build_id = plan.get("base_build_id")
    if not isinstance(base_build_id, str) or not base_build_id.strip():
        issues.append(
            _issue("base_build_id_missing", "plan must name the base build id it varies from")
        )
    assets = plan.get("assets")
    changed_ids: set[str] = set()
    if not isinstance(assets, list) or not assets:
        issues.append(_issue("assets_missing", "plan must declare a non-empty assets list"))
        assets = assets if isinstance(assets, list) else []
    for index, asset in enumerate(assets):
        where = f"assets[{index}]"
        if not isinstance(asset, dict):
            issues.append(_issue(f"{where}:not_object", "each asset must be an object"))
            continue
        asset_id = asset.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id.strip():
            issues.append(_issue(f"{where}:asset_id_missing", "each asset needs a non-empty id"))
            continue
        changed = asset.get("changed")
        if changed is True:
            changed_ids.add(asset_id)
            if asset.get("reused") is True:
                issues.append(
                    _issue(
                        f"{where}:changed_claimed_reused",
                        "a changed asset must be rebuilt, not claimed as reused",
                    )
                )
            if isinstance(asset.get("build_id"), str) and asset["build_id"] == base_build_id:
                issues.append(
                    _issue(
                        f"{where}:changed_reuses_base_build",
                        "a changed asset must not keep the base build id",
                    )
                )
        elif changed is False:
            if asset.get("reused") is not True:
                issues.append(
                    _issue(
                        f"{where}:unchanged_not_reused",
                        "an unchanged asset must be declared reused",
                    )
                )
            build_id = asset.get("build_id")
            if not isinstance(build_id, str) or not build_id.strip():
                issues.append(
                    _issue(
                        f"{where}:build_id_missing",
                        "a reused asset needs a non-empty build id",
                    )
                )
        else:
            issues.append(
                _issue(
                    f"{where}:changed_flag_missing",
                    "each asset must declare changed true or false",
                )
            )
    rerun_scope = plan.get("rerun_scope")
    if not isinstance(rerun_scope, list) or not rerun_scope:
        issues.append(
            _issue(
                "rerun_scope_missing",
                "plan must declare a non-empty re-run scope naming only changed parts",
            )
        )
    else:
        for entry in rerun_scope:
            if not isinstance(entry, str) or not entry.strip():
                issues.append(
                    _issue("rerun_scope:entry_invalid", "re-run scope entries must be asset ids")
                )
            elif entry not in changed_ids:
                issues.append(
                    _issue(
                        f"rerun_scope:unchanged:{entry}",
                        "re-run scope must name only changed assets",
                    )
                )
    return {
        "verdict": "fail" if issues else "pass",
        "ok": not issues,
        "issues": issues,
    }


def _render(
    params: dict[str, Any], out_dir: Any, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = check_variant_reuse(params.get("plan"))
    report_path = out_dir / "variant_reuse.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_variant_reuse_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.variant_reuse_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "Variant reuse gate (discipline only): variants "
                "re-run only changed parts and reuse unchanged "
                "assets under recorded build ids."
            ),
        )
    )
    return ["qa.variant_reuse_gate"]


__all__ = [
    "check_variant_reuse",
    "register_variant_reuse_gate_capabilities_once",
]
