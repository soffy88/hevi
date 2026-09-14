"""Inventory the first-party 3O assets for the per-Wave admission gate.

Emits ``artifacts/qualification/creative-runtime/3o-asset-inventory.json`` with,
for every 3O layer, the flat element names it currently exports.  The inventory
is a *read-only* observation: it never changes status and exists so a new
element can be checked for single-source ownership before it is admitted.

Usage::

    python scripts/qualification/inventory_3o_assets.py
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[2]
HEVI = ROOT / "hevi"
CREATIVE = HEVI / "creative"
LAYERS = ("oprim", "oskill", "omodul", "oservi")
OUT = ROOT / "artifacts/qualification/creative-runtime/3o-asset-inventory.json"


def _module_elements(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    except SyntaxError:
        return []
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
        elif isinstance(node, ast.Assign):
            names.extend(
                target.id
                for target in node.targets
                if isinstance(target, ast.Name) and target.id != "__all__"
            )
    return names


def build_inventory() -> dict[str, Any]:
    layers: dict[str, Any] = {}
    for layer in LAYERS:
        directory = CREATIVE / layer
        modules: dict[str, list[str]] = {}
        for path in sorted(directory.glob("*.py")):
            if path.name == "__init__.py":
                continue
            modules[path.name] = _module_elements(path)
        layers[layer] = {"module_count": len(modules), "modules": modules}
    obase_modules: dict[str, list[str]] = {}
    for path in sorted((HEVI / "obase").glob("*.py")):
        if path.name == "__init__.py":
            continue
        obase_modules[path.name] = _module_elements(path)
    layers["obase"] = {"module_count": len(obase_modules), "modules": obase_modules}
    return {
        "spec": "3O Paradigm SPEC v3.0",
        "purpose": "flat-namespace asset inventory for single-source admission",
        "layers": layers,
    }


def main() -> int:
    inventory = build_inventory()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    total = sum(entry["module_count"] for entry in inventory["layers"].values())
    print(f"3O asset inventory written: {OUT.relative_to(ROOT)} (modules={total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
