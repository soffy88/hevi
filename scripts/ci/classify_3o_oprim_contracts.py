"""Classify oprim signature findings before changing any call site."""
from __future__ import annotations

import ast
import json
import sys

from _3o_common import ROOT, local_sources, parse


def main() -> int:
    rows: list[dict[str, object]] = []
    for source in local_sources("oprim"):
        tree = parse(source.path)
        text = source.path.read_text(encoding="utf-8").lower()
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name.startswith("_"):
                continue
            positional = len(node.args.posonlyargs + node.args.args)
            if positional <= 1:
                continue
            segment = ast.unparse(node).lower()
            io = any(token in segment or token in text for token in ("subprocess", "write_text", "write_bytes", "mkdir(", "provider", "httpx", "database", "db."))
            mutates = any(token in segment for token in (".status =", ".timeline =", ".append(", ".update("))
            if mutates:
                action = "MOVE_LAYER4"
                classification = "MISCLASSIFIED_LAYER4"
            elif io:
                action = "MOVE_OBASE" if any(token in segment for token in ("subprocess", "httpx", "database", "db.")) else "RECLASSIFY_OMODUL"
                classification = "MOVE_OBASE" if action == "MOVE_OBASE" else "MISCLASSIFIED_OMODUL"
            else:
                action = "RECLASSIFY_OPRIM"
                classification = "TRUE_OPRIM"
            rows.append({
                "symbol": f"{source.rel}::{node.name}",
                "current_path": source.rel,
                "positional_arguments": positional,
                "classification": classification,
                "migration_action": action,
                "canonical_equivalent": f"oprim.{node.name}",
                "consumer_search_root": str(ROOT),
                "blocking_symbols": [],
            })
    out = ROOT / "artifacts/3o-v3/oprim-contract-classification.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"source": "local HEVI AST", "count": len(rows), "symbols": rows}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"LOCAL_OPRIM_SIGNATURE_FINDINGS={len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
