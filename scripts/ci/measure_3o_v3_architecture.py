"""Measure the three architecture quantities that the v3 audit previously missed."""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEVI = ROOT / "hevi"
LAYERS = {"oprim", "oskill", "omodul", "obase", "oservi"}
PILLARS = {"fingerprint", "decision_trail", "report", "cost"}


def sources(layer: str) -> list[Path]:
    return sorted(
        p for p in HEVI.rglob("*.py")
        if "__pycache__" not in p.parts and layer in p.relative_to(HEVI).parts
    )


def tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imported_oprims(t: ast.AST) -> set[str]:
    names: set[str] = set()
    for n in ast.walk(t):
        if isinstance(n, ast.ImportFrom) and n.module and "oprim" in n.module.split("."):
            for a in n.names:
                names.add(a.asname or a.name)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.split(".")[-1] == "oprim":
                    names.add(a.asname or a.name.split(".")[0])
    return names


def called_names(t: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(t):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name):
                out.add(n.func.id)
            elif isinstance(n.func, ast.Attribute):
                out.add(n.func.attr)
    return out


def measure_single_oprim() -> dict[str, object]:
    items: list[dict[str, object]] = []
    for path in sources("oskill"):
        t = tree(path)
        imported = imported_oprims(t)
        called = called_names(t)
        # Direct imported symbols are the conservative, attributable set.
        distinct = sorted(imported & called)
        if len(distinct) < 2:
            items.append({"path": str(path.relative_to(ROOT)), "distinct_oprims": distinct})
    return {"count": len(items), "oskills": items}


def local_symbols(path: Path) -> set[str]:
    return {
        n.name for n in ast.walk(tree(path))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and not n.name.startswith("_")
    }


def measure_omodul_graph() -> dict[str, object]:
    paths = sources("omodul")
    symbols = {p: local_symbols(p) for p in paths}
    by_name: dict[str, list[Path]] = {}
    for p, names in symbols.items():
        for name in names:
            by_name.setdefault(name, []).append(p)
    edges: set[tuple[str, str]] = set()
    for p in paths:
        for name in called_names(tree(p)):
            for target in by_name.get(name, []):
                if target != p:
                    edges.add((str(p.relative_to(ROOT)), str(target.relative_to(ROOT))))
    nodes = sorted({x for edge in edges for x in edge} | {str(p.relative_to(ROOT)) for p in paths})
    adjacency = {n: [] for n in nodes}
    for a, b in sorted(edges):
        adjacency[a].append(b)
    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    low: dict[str, int] = {}
    sccs: list[list[str]] = []

    def visit(v: str) -> None:
        nonlocal index
        indices[v] = low[v] = index
        index += 1
        stack.append(v)
        on_stack.add(v)
        for w in adjacency[v]:
            if w not in indices:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on_stack:
                low[v] = min(low[v], indices[w])
        if low[v] == indices[v]:
            component: list[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                component.append(w)
                if w == v:
                    break
            if len(component) > 1 or component[0] in adjacency[component[0]]:
                sccs.append(sorted(component))

    for node in nodes:
        if node not in indices:
            visit(node)
    return {"nodes": nodes, "edges": [[a, b] for a, b in sorted(edges)], "sccs": sorted(sccs), "cycles": len(sccs)}


def measure_fake_pillars() -> dict[str, object]:
    findings: list[dict[str, object]] = []
    for path in sources("omodul"):
        t = tree(path)
        declared: set[str] = set()
        for n in ast.walk(t):
            if isinstance(n, ast.Assign) and isinstance(n.value, (ast.Set, ast.List, ast.Tuple)):
                if any(isinstance(x, ast.Name) and x.id == "_enabled_pillars" for x in n.targets):
                    declared |= {x.value for x in n.value.elts if isinstance(x, ast.Constant) and isinstance(x.value, str)}
        text = path.read_text(encoding="utf-8").lower()
        implemented = {
            p for p in PILLARS
            if ((p == "fingerprint" and ("compute_fingerprint" in text or "fingerprint" in text))
                or (p == "decision_trail" and ("decision_trail" in text or "trail.record" in text))
                or (p == "report" and ("report_path" in text or "report" in text))
                or (p == "cost" and ("cost" in text or "total_cost" in text)))
        }
        returned = implemented & {p for p in PILLARS if p in text}
        fake = sorted(declared - implemented | implemented - declared | declared - returned)
        if fake:
            findings.append({"path": str(path.relative_to(ROOT)), "declared": sorted(declared), "implemented": sorted(implemented), "returned": sorted(returned), "fake": fake})
    return {"count": len(findings), "findings": findings}


def main() -> int:
    out = ROOT / "artifacts/3o-v3"
    out.mkdir(parents=True, exist_ok=True)
    single = measure_single_oprim()
    graph = measure_omodul_graph()
    pillars = measure_fake_pillars()
    (out / "single-oprim-oskills.json").write_text(json.dumps(single, indent=2) + "\n")
    (out / "omodul-call-graph.json").write_text(json.dumps(graph, indent=2) + "\n")
    (out / "fake-pillar-declarations.json").write_text(json.dumps(pillars, indent=2) + "\n")
    print(f"SINGLE_OPRIM_OSKILLS={single['count']}")
    print(f"OMODUL_NODES={len(graph['nodes'])}")
    print(f"OMODUL_EDGES={len(graph['edges'])}")
    print(f"OMODUL_CYCLES={graph['cycles']}")
    print(f"OMODUL_SCCS={len(graph['sccs'])}")
    print(f"FAKE_PILLAR_DECLARATIONS={pillars['count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
