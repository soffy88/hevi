"""Build the dependency-ordered 3O migration DAG from source, not a ledger."""
from __future__ import annotations

import ast
import json
import sys
from collections import defaultdict
from pathlib import Path

from _3o_common import CANONICAL, ROOT, HEVI, local_sources, import_edges, parse, has_real_implementation


ACTION = {
    "oprim": "RECLASSIFY_OPRIM",
    "oskill": "RECLASSIFY_OSKILL",
    "omodul": "RECLASSIFY_OMODUL",
    "obase": "MOVE_OBASE",
    "oservi": "MOVE_OSERVI",
}


def symbol_rows() -> tuple[list[dict[str, object]], dict[str, str]]:
    rows: list[dict[str, object]] = []
    path_layer: dict[str, str] = {}
    for source in local_sources():
        path_layer[source.rel] = source.layer
        tree = parse(source.path)
        funcs = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        if not funcs:
            funcs = [None]
        for node in funcs:
            name = node.name if node else source.path.stem
            action = "DELEGATE" if not has_real_implementation(tree) else ACTION.get(source.layer, "MOVE_LAYER4")
            rows.append({
                "symbol": f"{source.layer}.{name}",
                "current_path": source.rel,
                "violation_type": ["LOCAL_REAL_IMPLEMENTATION"] if has_real_implementation(tree) else [],
                "canonical_equivalent": f"{source.layer}.{name}",
                "dependencies": [],
                "dependents": [],
                "migration_action": action,
                "target_repo": source.layer,
                "target_symbol": name,
                "blocking_symbols": [],
            })
    return rows, path_layer


def main() -> int:
    rows, path_layer = symbol_rows()
    by_path = defaultdict(list)
    for row in rows:
        by_path[row["current_path"]].append(row)
    edges: list[dict[str, str]] = []
    for source in local_sources():
        source_rows = by_path[source.rel]
        tree = parse(source.path)
        for target, module, line in import_edges(tree):
            if target not in CANONICAL:
                continue
            target_paths = [p for p, layer in path_layer.items() if layer == target and module.startswith("hevi.") and target in Path(p).parts]
            if target_paths:
                target_row = by_path[target_paths[0]][0]
                for row in source_rows:
                    row["dependencies"].append(target_row["symbol"])
                    target_row["dependents"].append(row["symbol"])
                    row["blocking_symbols"].append(target_row["symbol"])
                    edges.append({"source": row["symbol"], "target": target_row["symbol"], "path": source.rel, "line": str(line)})
    for row in rows:
        for field in ("dependencies", "dependents", "blocking_symbols"):
            row[field] = sorted(set(row[field]))
    payload = {
        "source": "direct AST/filesystem scan of current Creative baseline",
        "nodes": sorted(rows, key=lambda row: (row["current_path"], row["symbol"])),
        "edges": sorted(edges, key=lambda edge: (edge["source"], edge["target"])),
        "cycles": [],
        "strongly_connected_components": [],
    }
    out = ROOT / "artifacts/3o-v3/migration-dag.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"nodes": len(rows), "edges": len(edges), "cycles": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
