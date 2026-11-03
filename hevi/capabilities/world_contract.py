"""World-contract validation capability (``world.contract_validate``).

Registers one ``hevi.capabilities`` entry:

* ``world.contract_validate`` — validate a spatial world contract JSON
  plus a world manifest JSON (the placements each zone builder declares)
  with the pure-Python validator in ``hevi.world_contract`` and write the
  structured report (pass/fail + per-rule violations) as JSON.  Fully
  local: no keys, no network, no rendering cost.  This is the gate a
  multi-zone procedural world must pass before any zone is rendered.

Registration note: this module registers itself on import (guarded,
idempotent), following the ``image.generative_art`` / ``image.brush_scene``
precedent.  ``hevi/capabilities/__init__.py`` is intentionally NOT edited
here because that file carries unrelated uncommitted work; once that
lands, move the import there and drop the import-time call.
"""

from __future__ import annotations

import json
import time
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


def _render_contract_validate(
    params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int
) -> CapabilityResult:
    from hevi.world_contract import load_json, validate

    contract_path = params.get("contract_path")
    manifest_path = params.get("manifest_path")
    if not contract_path:
        raise CapabilityError("world.contract_validate: params.contract_path is required")
    try:
        contract = load_json(contract_path)
        manifest = load_json(manifest_path) if manifest_path else None
    except ValueError as exc:
        raise CapabilityError(f"world.contract_validate: {exc}") from exc

    started = time.time()
    result = validate(contract, manifest)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "world_contract_report.json"
    report_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return CapabilityResult(
        duration_s=round(time.time() - started, 4),
        sha256=compute_sha256(report_path),
        qa={
            "pass": result["pass"],
            "violations": result["violations"],
            "checked": result["checked"],
            "report_path": str(report_path),
        },
    )


def register_world_contract_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="world.contract_validate",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "contract_path": {
                        "type": "string",
                        "description": "Path to the world contract JSON.",
                    },
                    "manifest_path": {
                        "type": "string",
                        "description": "Path to the world manifest JSON (optional).",
                    },
                },
                "required": ["contract_path"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.01,
            render=_render_contract_validate,
            description=(
                "Validate a spatial world contract + zone manifest "
                "(bounds, zones, no-place / max-height rules, interface "
                "formulas, anchor bounds, coordinate provenance, global "
                "lighting timeline) and emit a structured JSON report. "
                "Zero cost, offline, deterministic."
            ),
            line="world",
        )
    )
    return ["world.contract_validate"]


# Import-time registration (see module docstring for why this is not
# wired through hevi/capabilities/__init__.py yet).
register_world_contract_capabilities_once()
