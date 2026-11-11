"""Dataset attribution gate (``qa.sand3d_dataset_attribution_gate``).

The five known sand3d program datasets are all CC BY 4.0: a
dataset used in hevi must be named, carry its CC BY 4.0
license, carry its attribution text, and name its source
chain. A dataset outside the five known sets fails as
unverifiable: its license cannot be checked from this gate.
Dataset meshes are never hevi assets: a card claiming the
meshes are hevi assets fails outright.

Clean-room restatement of the Sandflow-ai/sand3d method (see
``SAND3D_ATTRIBUTION.md``); no upstream code appears here.
This gate judges dataset cards only; it never downloads,
copies, or runs any dataset program. Dataset meshes are not
hevi assets and are never imported by this module.
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

DATASETS: frozenset[str] = frozenset({"objaverse", "cad", "articraft", "simready", "automate"})
DATASET_LICENSE = "CC BY 4.0"


def _issue(code: str, detail: str) -> dict[str, Any]:
    return {"code": code, "detail": detail}


def check_sand3d_dataset_attribution(datasets: Any) -> dict[str, Any]:
    """Validate sand3d-style dataset attribution cards.

    Verdicts are ``pass`` / ``fail`` only. The list fails when
    it is not a non-empty list, when any card is not an object,
    when a dataset name is outside the five known sets, when
    its license is not CC BY 4.0, when its attribution text is
    missing, when its source chain is empty, or when it claims
    the dataset meshes are hevi assets.
    """
    issues: list[dict[str, Any]] = []

    def fail(code: str, detail: str) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "ok": False,
            "issues": [*issues, _issue(code, detail)],
            "executed_here": False,
        }

    if not isinstance(datasets, list) or not datasets:
        return fail("datasets_missing", "dataset list must be a non-empty list")
    for position, card in enumerate(datasets):
        if not isinstance(card, dict):
            return fail(
                "dataset_not_object",
                f"dataset {position} must be an object",
            )
        name = card.get("name")
        if not isinstance(name, str) or not name:
            return fail(
                "dataset_name_missing",
                f"dataset {position} must carry a name",
            )
        if name not in DATASETS:
            return fail(
                "unknown_dataset",
                f"dataset {position} name {name!r} is outside the "
                "five known sets; its license cannot be verified",
            )
        if card.get("license") != DATASET_LICENSE:
            return fail(
                "license_mismatch",
                f"dataset {position} {name!r} must be licensed {DATASET_LICENSE}",
            )
        attribution = card.get("attribution")
        if not isinstance(attribution, str) or not attribution.strip():
            return fail(
                "attribution_missing",
                f"dataset {position} {name!r} must carry its attribution text",
            )
        chain = card.get("source_chain")
        if not isinstance(chain, list) or not chain:
            return fail(
                "source_chain_missing",
                f"dataset {position} {name!r} must name its source chain",
            )
        if card.get("meshes_are_hevi_assets") is True:
            return fail(
                "meshes_claimed_as_hevi_assets",
                f"dataset {position} {name!r} meshes are not hevi "
                "assets and must never be claimed as such",
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
    report = check_sand3d_dataset_attribution(params.get("datasets"))
    report_path = out_dir / "sand3d_dataset_attribution_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return CapabilityResult(
        duration_s=0.0,
        sha256=compute_sha256(report_path),
        qa={"report_json": str(report_path), "verdict": report["verdict"]},
    )


def register_sand3d_dataset_attribution_gate_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="qa.sand3d_dataset_attribution_gate",
            kind="line",
            aspects=["16:9", "9:16"],
            params_schema={
                "type": "object",
                "properties": {
                    "datasets": {"type": "array"},
                },
                "required": ["datasets"],
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=False,
            layer="oskill",
            description=(
                "sand3d dataset attribution gate: five known sets, "
                "all CC BY 4.0, attribution text and source chain "
                "required; dataset meshes are never hevi assets."
            ),
        )
    )
    return ["qa.sand3d_dataset_attribution_gate"]


__all__ = [
    "DATASETS",
    "DATASET_LICENSE",
    "check_sand3d_dataset_attribution",
    "register_sand3d_dataset_attribution_gate_capabilities_once",
]
