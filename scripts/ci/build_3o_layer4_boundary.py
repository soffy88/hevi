"""Find HEVI business authority leaking into local 3O namespaces."""
from __future__ import annotations

import ast
import json
import sys

from _3o_common import CANONICAL, ROOT, local_sources, parse


def main() -> int:
    rows = []
    tokens = ("user_id", "tenant_id", "project_id", "job_id", "production_run_id", "creative_project_id", "creativeproject", "narrativecanon", "presenterjob", "productionrun")
    for source in local_sources():
        if source.layer not in CANONICAL:
            continue
        tree = parse(source.path)
        for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_")):
            text = ast.unparse(fn).lower()
            found = [token for token in tokens if token in text]
            if not found:
                continue
            kind = "BUSINESS_STATE_IN_3O" if any(x in text for x in (".status =", ".state =", ".output =", ".timeline =", ".save(", ".commit(")) else "PROJECT_IDENTITY_IN_3O"
            rows.append({"symbol": f"{source.rel}::{fn.name}", "path": source.rel, "violation": kind, "current_layer": source.layer, "expected_owner": "hevi Layer4", "evidence": found})
    out = ROOT / "artifacts/3o-v3/layer4-boundary-violations.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"source": "direct AST scan", "count": len(rows), "violations": rows}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"LAYER4_BOUNDARY_VIOLATIONS={len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
