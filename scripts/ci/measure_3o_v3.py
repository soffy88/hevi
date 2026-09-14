"""Direct AST measurements for the 3O v3 closure gates.

This module deliberately reports unresolved/dynamic calls as unresolved instead
of treating imports, aliases, or re-exports as composition.
"""
from __future__ import annotations

import ast
import json
import sys
from collections import defaultdict

from _3o_common import CANONICAL, ROOT, all_sources, canonical_sources, local_sources, parse


def _element_nodes(layer: str) -> list[tuple[object, ast.Module, ast.FunctionDef | ast.AsyncFunctionDef]]:
    out = []
    for source in all_sources(layer):
        tree = parse(source.path)
        out.extend(
            (source, tree, node)
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
        )
    return out


def _imported_functions(tree: ast.Module) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    funcs: dict[str, tuple[str, str]] = {}
    modules: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            target = root if root in CANONICAL else next((part for part in node.module.split(".") if part in CANONICAL), None)
            if target:
                for alias in node.names:
                    funcs[alias.asname or alias.name] = (target, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in CANONICAL:
                    modules[alias.asname or root] = alias.name
    return funcs, modules


def single_oprim_measurement() -> dict[str, object]:
    rows = []
    counts = {"zero": 0, "one": 0, "multi": 0}
    for source, tree, fn in _element_nodes("oskill"):
        funcs, modules = _imported_functions(tree)
        called: set[str] = set()
        for call in ast.walk(fn):
            if not isinstance(call, ast.Call):
                continue
            if isinstance(call.func, ast.Name) and call.func.id in funcs and funcs[call.func.id][0] == "oprim":
                called.add(f"oprim.{funcs[call.func.id][1]}")
            elif isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id in modules and modules[call.func.value.id].startswith("oprim"):
                called.add(f"oprim.{call.func.attr}")
        bucket = "zero" if not called else "one" if len(called) == 1 else "multi"
        counts[bucket] += 1
        if bucket != "multi":
            rows.append({"symbol": f"{source.rel}::{fn.name}", "oprim_calls": sorted(called), "distinct_oprims": len(called), "reason": "fewer than two distinct direct oprim call sites"})
    return {"count": len(rows), "zero": counts["zero"], "one": counts["one"], "multi": counts["multi"], "oskills": rows, "source": "AST function call sites"}


def _omodul_graph() -> dict[str, object]:
    nodes: set[str] = set()
    edges: set[tuple[str, str]] = set()
    self_calls = 0
    dynamic_calls = 0
    unresolved = 0
    direct_calls = 0
    elements = _element_nodes("omodul")
    by_name: defaultdict[str, list[str]] = defaultdict(list)
    for source, _, fn in elements:
        by_name[fn.name].append(f"{source.rel}::{fn.name}")
    for source, tree, fn in elements:
        current = f"{source.rel}::{fn.name}"
        nodes.add(current)
        funcs, modules = _imported_functions(tree)
        for call in ast.walk(fn):
            if not isinstance(call, ast.Call):
                continue
            target = None
            if isinstance(call.func, ast.Name) and call.func.id in funcs and funcs[call.func.id][0] == "omodul":
                target = funcs[call.func.id][1]
            elif isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name) and call.func.value.id in modules and modules[call.func.value.id].startswith("omodul"):
                target = call.func.attr
            if target:
                direct_calls += 1
                candidates = by_name[target]
                for candidate in candidates[:1]:
                    nodes.add(candidate)
                    edges.add((current, candidate))
                    if candidate == current:
                        self_calls += 1
            elif (isinstance(call.func, ast.Name) and call.func.id in {"eval", "exec", "getattr", "__import__"}) or (isinstance(call.func, ast.Attribute) and call.func.attr in {"getattr", "import_module"}):
                dynamic_calls += 1
            elif isinstance(call.func, ast.Name) and call.func.id in funcs and funcs[call.func.id][0] == "omodul":
                unresolved += 1
    adjacency = defaultdict(list)
    for left, right in edges:
        adjacency[left].append(right)
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    sccs: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indices[node] = low[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for child in adjacency[node]:
            if child not in indices:
                visit(child)
                low[node] = min(low[node], low[child])
            elif child in on_stack:
                low[node] = min(low[node], indices[child])
        if low[node] == indices[node]:
            component = []
            while True:
                child = stack.pop()
                on_stack.remove(child)
                component.append(child)
                if child == node:
                    break
            if len(component) > 1 or node in adjacency[node]:
                sccs.append(sorted(component))

    for node in sorted(nodes):
        if node not in indices:
            visit(node)
    return {"nodes": sorted(nodes), "edges": [{"source": a, "target": b} for a, b in sorted(edges)], "cycles": sccs, "strongly_connected_components": sccs, "OMODUL_NODES": len(nodes), "OMODUL_EDGES": len(edges), "OMODUL_DIRECT_CALL_SITES": direct_calls, "OMODUL_CYCLES": len(sccs), "OMODUL_SCCS": len(sccs), "OMODUL_SELF_CALLS": self_calls, "OMODUL_DYNAMIC_CALLS": dynamic_calls, "OMODUL_UNRESOLVED_CALL_TARGETS": unresolved, "source": "AST direct call graph"}


def _pillar_measurement() -> dict[str, object]:
    rows = []
    allowed = {"fingerprint", "decision_trail", "report", "cost"}
    for source in canonical_sources("omodul") + local_sources("omodul"):
        tree = parse(source.path)
        declared: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Set, ast.Tuple, ast.List)) and any(isinstance(t, ast.Name) and t.id == "_enabled_pillars" for t in node.targets):
                declared |= {x.value for x in node.value.elts if isinstance(x, ast.Constant) and isinstance(x.value, str)}
        for pillar in sorted(declared):
            text = source.path.read_text(encoding="utf-8").lower()
            implemented = {
                "fingerprint": "compute_fingerprint_for" in text,
                "decision_trail": "decision_trail" in text and any(x in text for x in ("append(", "trail =", "trail:")),
                "report": any(x in text for x in ("report_path", "report =", "write_report", "report.json")),
                "cost": any(x in text for x in ("cost =", "cost:", "cost_tracker", "estimate_cost", "total_cost")),
            }.get(pillar, False)
            returned = any(isinstance(node, ast.Return) and isinstance(node.value, ast.Dict) and any(isinstance(k, ast.Constant) and k.value in {pillar, f"{pillar}_path"} for k in node.value.keys) for node in ast.walk(tree))
            if pillar not in allowed or not implemented or not returned:
                rows.append({"symbol": source.rel, "pillar": pillar, "declared": True, "implemented": implemented, "returned": returned})
    return {"count": len(rows), "declarations": rows, "source": "AST declaration/implementation/return scan"}


def main() -> int:
    single = single_oprim_measurement()
    graph = _omodul_graph()
    fake = _pillar_measurement()
    targets = {
        "single-oprim-oskills.json": single,
        "omodul-call-graph.json": graph,
        "fake-pillar-declarations.json": fake,
    }
    for name, payload in targets.items():
        out = ROOT / "artifacts/3o-v3" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"SINGLE_OPRIM_OSKILLS={single['count']}")
    print(f"ZERO_OPRIM_OSKILLS={single['zero']}")
    print(f"ONE_OPRIM_OSKILLS={single['one']}")
    print(f"MULTI_OPRIM_OSKILLS={single['multi']}")
    print(f"OMODUL_NODES={graph['OMODUL_NODES']}")
    print(f"OMODUL_EDGES={graph['OMODUL_EDGES']}")
    print(f"OMODUL_DIRECT_CALL_SITES={graph['OMODUL_DIRECT_CALL_SITES']}")
    print(f"OMODUL_CYCLES={graph['OMODUL_CYCLES']}")
    print(f"OMODUL_SCCS={graph['OMODUL_SCCS']}")
    print(f"OMODUL_SELF_CALLS={graph['OMODUL_SELF_CALLS']}")
    print(f"OMODUL_DYNAMIC_CALLS={graph['OMODUL_DYNAMIC_CALLS']}")
    print(f"OMODUL_UNRESOLVED_CALL_TARGETS={graph['OMODUL_UNRESOLVED_CALL_TARGETS']}")
    print(f"FAKE_PILLAR_DECLARATIONS={fake['count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
