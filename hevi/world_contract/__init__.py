"""hevi.world_contract — the spatial world contract for procedural worlds.

One contract (JSON, metres) is the single source of spatial truth for a
world: bounds, zones, landmarks, exclusion / height rules, interface
formulas shared across zone boundaries, published camera anchors, the
ground-height provider, the global lighting timeline and the shot-local
time convention.  Zone builders read the contract; they never invent
coordinates.  ``validate`` enforces that, given a contract plus a world
manifest declaring what each builder placed.

Public surface:
    load_json / evaluate_formula / ContractError   (model)
    validate / validate_contract / validate_manifest
    examples_dir() — bundled example contract + manifests

See ``docs/rules/world_contract.md`` for the normative spec and
``schema.json`` (in this package) for the machine-readable format.
"""

from __future__ import annotations

from pathlib import Path

from .model import ContractError, evaluate_formula, load_json
from .validate import validate, validate_contract, validate_manifest

__all__ = [
    "ContractError",
    "evaluate_formula",
    "examples_dir",
    "load_json",
    "validate",
    "validate_contract",
    "validate_manifest",
]


def examples_dir() -> Path:
    return Path(__file__).parent / "examples"
