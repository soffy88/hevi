"""Build the complete, source-derived oprim contract reclassification map.

The map includes the pinned canonical package as well as HEVI sources.  It is
an input to migration; it is deliberately not used by any compliance gate.
"""

from __future__ import annotations

import ast
import json
import sys

from _3o_common import ROOT, all_sources, parse


def _caller_index() -> dict[str, list[str]]:
    index: dict[str, set[str]] = {}
    for source in all_sources():
        tree = parse(source.path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            owner = f"{source.rel}::{node.name}"
            for call in ast.walk(node):
                if isinstance(call, ast.Call):
                    name = (
                        call.func.id
                        if isinstance(call.func, ast.Name)
                        else call.func.attr
                        if isinstance(call.func, ast.Attribute)
                        else None
                    )
                    if name:
                        index.setdefault(name, set()).add(owner)
    return {name: sorted(owners) for name, owners in index.items()}


def _callers(index: dict[str, list[str]], function_name: str) -> list[str]:
    return index.get(function_name, [])


def _classify(source, node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[str, str, str, str]:
    segment = ast.unparse(node).lower()
    path_text = source.path.read_text(encoding="utf-8").lower()
    joined = f"{segment}\n{path_text}"
    if any(
        token in segment
        for token in (
            ".status =",
            ".timeline =",
            ".rendered =",
            ".caption_json =",
            ".save(",
            ".commit(",
        )
    ):
        return "LAYER4", "MOVE_LAYER4", "hevi.layer4", "mutates HEVI business state"
    if any(
        token in joined
        for token in (
            "subprocess",
            "httpx",
            "requests.",
            "database",
            "db.",
            "providerregistry",
            "credential",
            "mkdir(",
            "write_text",
            "write_bytes",
        )
    ):
        return "INFRASTRUCTURE", "MOVE_OBASE", "obase", "owns infrastructure or persistent IO"
    if any(
        token in segment
        for token in ("for ", "while ", "build_", "plan_", "assemble", "compose", "resolve_")
    ):
        return (
            "MISCLASSIFIED_OSKILL",
            "RECLASSIFY_OSKILL",
            "oskill",
            "combines multiple algorithmic steps",
        )
    return (
        "TRUE_OPRIM",
        "RECLASSIFY_OPRIM",
        "oprim",
        "single reusable operation with a positional contract",
    )


def main() -> int:
    rows: list[dict[str, object]] = []
    caller_index = _caller_index()
    for source in all_sources("oprim"):
        tree = parse(source.path)
        for node in tree.body:
            if not isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) or node.name.startswith("_"):
                continue
            positional = len(node.args.posonlyargs + node.args.args)
            if positional <= 1:
                continue
            classification, action, target, reason = _classify(source, node)
            symbol = f"{source.rel}::{node.name}"
            rows.append(
                {
                    "symbol": symbol,
                    "path": source.rel,
                    "current_signature": ast.unparse(node.args),
                    "reason_for_violation": reason,
                    "classification": classification,
                    "target_layer": target,
                    "target_symbol": f"{target}.{node.name}",
                    "callers": _callers(caller_index, node.name),
                    "migration_action": action,
                }
            )
    out = ROOT / "artifacts/3o-v3/oprim-reclassification.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"source": "direct AST inventory", "count": len(rows), "symbols": rows},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"OPRIM_RECLASSIFICATION_FINDINGS={len(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
