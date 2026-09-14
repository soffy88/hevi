"""Emit a per-function oskill purity inventory from source AST."""
from __future__ import annotations

import ast
import json
import sys

from _3o_common import ROOT, all_sources, parse
from measure_3o_v3 import _imported_functions


def main() -> int:
    rows = []
    for source in all_sources("oskill"):
        tree = parse(source.path)
        functions, modules = _imported_functions(tree)
        for fn in tree.body:
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name.startswith("_"):
                continue
            calls = set()
            for call in ast.walk(fn):
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in functions and functions[call.func.id][0] == "oprim":
                    calls.add(f"oprim.{functions[call.func.id][1]}")
                elif isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id in modules and modules[call.func.value.id].startswith("oprim"):
                    calls.add(f"oprim.{call.func.attr}")
            text = ast.unparse(fn).lower()
            rows.append({
                "symbol": f"{source.rel}::{fn.name}",
                "called_oprims": sorted(calls),
                "distinct_oprim_count": len(calls),
                "called_oskills": [],
                "state_mutations": [x for x in ("self.", "status =", "timeline =", "rendered =", "caption_json =", "current_status") if x in text],
                "filesystem_io": [x for x in ("write_text", "write_bytes", "mkdir(") if x in text],
                "db_io": [x for x in ("commit(", "insert(", "update(") if x in text],
                "network_io": [x for x in ("httpx", "requests.") if x in text],
                "subprocess_io": [x for x in ("subprocess", "run(") if x in text],
                "business_ids": [x for x in ("user_id", "tenant_id", "project_id", "job_id", "production_run_id", "creative_project_id") if x in text],
                "provider_selection": any(x in text for x in ("provider", "model")),
                "target_classification": "oskill" if len(calls) >= 2 and not any(x in text for x in ("status =", "write_text", "commit(", "job_id")) else "reclassify",
            })
    out = ROOT / "artifacts/3o-v3/oskill-inventory.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"source": "direct AST inventory", "count": len(rows), "symbols": rows}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"OSKILL_INVENTORY_SYMBOLS={len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
