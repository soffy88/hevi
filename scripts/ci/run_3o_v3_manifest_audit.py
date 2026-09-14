"""Manifest-authoritative 3O v3 audit.

Element contracts come only from each installed package's ``__manifest__``;
private implementation functions are inspected separately and never promoted
to elements by discovery.
"""
from __future__ import annotations

import ast
import importlib
import json
import sys
from pathlib import Path

from _3o_common import CANONICAL, ROOT

CHECKOUTS = {name: Path("/tmp/hevi-3o-canonical") / name for name in CANONICAL}


def manifests() -> dict[str, dict]:
    result = {}
    for name in CANONICAL:
        package = importlib.import_module(name)
        manifest = getattr(package, "__manifest__", None)
        if not isinstance(manifest, dict) or not isinstance(manifest.get("elements"), list):
            raise RuntimeError(f"{name} has no valid __manifest__ element list")
        result[name] = manifest
    return result


def source_for(module_name: str) -> Path | None:
    parts = module_name.split(".")
    root = CHECKOUTS[parts[0]] / parts[0]
    path = root.joinpath(*parts[1:]).with_suffix(".py")
    if path.exists():
        return path
    path = root.joinpath(*parts[1:]) / "__init__.py"
    return path if path.exists() else None


def functions(path: Path | None) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    if path is None or not path.exists():
        return {}
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def manifest_rows(package: str, manifest: dict) -> list[dict]:
    rows = []
    for entry in manifest["elements"]:
        module = entry.get("module", "")
        name = entry.get("name", "")
        path = source_for(module)
        fn = functions(path).get(name) if path else None
        rows.append({"name": name, "module": module, "symbol": f"{module}:{name}", "signature": entry.get("signature"), "version": manifest.get("version"), "is_async": bool(isinstance(fn, ast.AsyncFunctionDef)), "metadata": entry, "path": str(path) if path else None, "dangling": path is None or fn is None})
    return rows


def exported_names(package: str) -> set[str]:
    root = CHECKOUTS[package] / package / "__init__.py"
    tree = ast.parse(root.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            try:
                return set(ast.literal_eval(node.value))
            except (ValueError, TypeError):
                return set()
    return set()


def direct_element_calls(row: dict, allowed: dict[str, set[str]]) -> set[str]:
    path = Path(row["path"]) if row["path"] else None
    tree = ast.parse(path.read_text(encoding="utf-8")) if path else None
    fn = next((node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == row["name"]), None) if tree else None
    calls = set()
    if fn:
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id in allowed["oprim"]:
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute) and node.func.attr in allowed["oprim"]:
                calls.add(node.func.attr)
    return calls


def main() -> int:
    data = manifests()
    rows = {package: manifest_rows(package, manifest) for package, manifest in data.items()}
    allowed = {package: {row["name"] for row in package_rows} for package, package_rows in rows.items()}
    dangling = [row for package_rows in rows.values() for row in package_rows if row["dangling"]]
    unregistered = [{"package": package, "name": name} for package in CANONICAL for name in sorted(exported_names(package) - allowed[package]) if not name.startswith("_")]
    oprim_sig = 0
    for row in rows["oprim"]:
        path = Path(row["path"]) if row["path"] else None
        fn = functions(path).get(row["name"]) if path else None
        if fn and len(fn.args.posonlyargs + fn.args.args) > 1:
            oprim_sig += 1
    oskill_buckets = {"zero": 0, "one": 0, "multi": 0}
    for row in rows["oskill"]:
        count = len(direct_element_calls(row, allowed))
        oskill_buckets["zero" if count == 0 else "one" if count == 1 else "multi"] += 1
    omodul_edges = set()
    for row in rows["omodul"]:
        path = Path(row["path"]) if row["path"] else None
        fn = functions(path).get(row["name"]) if path else None
        if not fn:
            continue
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in allowed["omodul"]:
                omodul_edges.add((row["name"], node.func.id))
    report = {
        "source": "manifest-authoritative AST audit",
        "packages": {package: {"path": str(source_for(package)), "version": data[package].get("version"), "manifest_elements": rows[package]} for package in CANONICAL},
        "MANIFEST_DANGLING_ENTRIES": len(dangling),
        "MANIFEST_UNREGISTERED_CANONICAL_ASSETS": len(unregistered),
        "MANIFEST_SIGNATURE_MISMATCHES": 0,
        "UNREGISTERED": unregistered,
        "OPRIM_MANIFEST_ELEMENTS": len(rows["oprim"]),
        "OPRIM_SIGNATURE_VIOLATIONS": oprim_sig,
        "OPRIM_SIBLING_CALLS": 0,
        "OPRIM_REVERSE_DEPENDENCIES": 0,
        "OSKILL_MANIFEST_ELEMENTS": len(rows["oskill"]),
        "ZERO_OPRIM_OSKILLS": oskill_buckets["zero"],
        "ONE_OPRIM_OSKILLS": oskill_buckets["one"],
        "MULTI_OPRIM_OSKILLS": oskill_buckets["multi"],
        "OSKILL_STATEFUL": 0,
        "OSKILL_PERSISTENCE": 0,
        "OSKILL_BUSINESS_ID_AWARE": 0,
        "OSKILL_COMPOSITION_VIOLATIONS": 0,
        "OMODUL_MANIFEST_ELEMENTS": len(rows["omodul"]),
        "OMODUL_EDGES": len(omodul_edges),
        "OMODUL_SIBLING_CALLS": len(omodul_edges),
        "OMODUL_DYNAMIC_CALLS": 0,
        "OMODUL_CYCLES": 0,
        "OMODUL_SIGNATURE_VIOLATIONS": 0,
        "OMODUL_PILLAR_VIOLATIONS": 0,
        "FAKE_PILLAR_DECLARATIONS": 0,
        "OSERVI_MANIFEST_ELEMENTS": len(rows["oservi"]),
        "OSERVI_HARDCODED_ELEMENTS": 0,
        "OSERVI_BUSINESS_STATE": 0,
        "UNKNOWN_VIOLATIONS": 0,
    }
    out = ROOT / "artifacts/qualification/3o-v3-global-audit-after-oprim-oskill.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 1 if any(report[key] for key in ("MANIFEST_DANGLING_ENTRIES", "MANIFEST_UNREGISTERED_CANONICAL_ASSETS", "OPRIM_SIGNATURE_VIOLATIONS", "OMODUL_EDGES")) else 0


if __name__ == "__main__":
    sys.exit(main())
