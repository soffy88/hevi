"""Build auditable M2 inventories without conflating platform and consumer code."""

from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = Path("/data/soffy/projects/platform/3O")
MNEME = Path("/data/soffy/projects/mneme")
LAYERS = ("obase", "oprim", "oskill", "omodul", "oservi")
SCAN_ROOTS = tuple(
    [PLATFORM / layer / layer for layer in LAYERS]
    + [MNEME / x for x in ("vendor", "services", "tests", "scripts")]
    + [ROOT / x for x in ("hevi", "tests", "scripts")]
)
_CALL_INDEX: dict[str, set[str]] | None = None


def classify_path(path: str, *, exact_replica: bool = False, thin_reexport: bool = False) -> str:
    """Classify a repository role; replicas are not duplicates."""
    p = Path(path)
    if PLATFORM in p.parents or p == PLATFORM:
        return "CANONICAL_SOURCE"
    if exact_replica:
        return "CONTROLLED_EXACT_REPLICA"
    if thin_reexport:
        return "THIN_REEXPORT"
    if "services" in p.parts or "routers" in p.parts or "workers" in p.parts:
        return "LAYER4_IMPLEMENTATION"
    return "REAL_DUPLICATE_IMPLEMENTATION"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_blob_hash(repo: Path, commit: str | None, rel: str | None) -> str | None:
    if not commit or not rel:
        return None
    for candidate in (rel, f"{repo.name}/{rel}"):
        try:
            data = subprocess.check_output(
                ["git", "-C", str(repo), "show", f"{commit}:{candidate}"]
            )
        except OSError, subprocess.CalledProcessError:
            continue
        return hashlib.sha256(data).hexdigest()
    return None


def parse(path: Path):
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except OSError, SyntaxError, UnicodeDecodeError:
        return None


def manifest_elements(package: Path) -> list[str]:
    tree = parse(package / "_manifest.py")
    if tree:
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Name) and t.id == "ELEMENTS" for t in targets):
                    try:
                        value = ast.literal_eval(node.value)
                    except ValueError, TypeError:
                        value = []
                    if isinstance(value, list):
                        return [x for x in value if isinstance(x, str)]
    tree = parse(package / "__init__.py")
    if tree:
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
            ):
                try:
                    value = ast.literal_eval(node.value)
                except ValueError, TypeError:
                    value = []
                if isinstance(value, list):
                    return [x for x in value if isinstance(x, str)]
    return []


def definitions(package: Path):
    result = {}
    for path in sorted(package.rglob("*.py")):
        if any(x in path.parts for x in ("tests", "__pycache__")):
            continue
        tree = parse(path)
        if not tree:
            continue
        for node in tree.body:
            if isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ) and not node.name.startswith("_"):
                result.setdefault(node.name, (path, node))
    return result


def signature(node) -> str:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return type(node).__name__
    return ast.unparse(
        ast.arguments(
            posonlyargs=node.args.posonlyargs,
            args=node.args.args,
            vararg=node.args.vararg,
            kwonlyargs=node.args.kwonlyargs,
            kw_defaults=node.args.kw_defaults,
            kwarg=node.args.kwarg,
            defaults=node.args.defaults,
        )
    )


def call_sites(name: str) -> list[str]:
    global _CALL_INDEX
    if _CALL_INDEX is None:
        _CALL_INDEX = defaultdict(set)
        for root in SCAN_ROOTS:
            if not root.exists():
                continue
            for path in root.rglob("*.py"):
                if any(
                    x in path.parts
                    for x in (
                        ".git",
                        "__pycache__",
                        ".venv",
                        ".mypy_cache",
                        ".ruff_cache",
                        ".pytest_cache",
                        "node_modules",
                    )
                ):
                    continue
                tree = parse(path)
                if not tree:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        called = (
                            node.func.id
                            if isinstance(node.func, ast.Name)
                            else node.func.attr
                            if isinstance(node.func, ast.Attribute)
                            else None
                        )
                        if called:
                            _CALL_INDEX[called].add(f"{path}:{getattr(node, 'lineno', '?')}")
    return sorted(_CALL_INDEX.get(name, set()))


def build_public_inventory():
    package = PLATFORM / "oprim" / "oprim"
    names = manifest_elements(package)
    defs = definitions(package)
    rows, violations = [], []
    for name in names:
        found = defs.get(name)
        if not found:
            rows.append(
                {
                    "name": name,
                    "definition_file": None,
                    "public_export_path": f"from oprim import {name}",
                    "manifest_entry": True,
                    "signature": None,
                    "call_site_count": 0,
                    "status": "UNRESOLVED_DEFINITION",
                }
            )
            continue
        path, node = found
        callers = call_sites(name)
        row = {
            "name": name,
            "definition_file": str(path.relative_to(PLATFORM / "oprim")),
            "public_export_path": f"from oprim import {name}",
            "manifest_entry": True,
            "signature": signature(node),
            "call_site_count": len(callers),
        }
        rows.append(row)
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and len(node.args.posonlyargs + node.args.args) > 1
        ):
            positional = [x.arg for x in node.args.posonlyargs + node.args.args]
            violations.append(
                {
                    "symbol": name,
                    "file": row["definition_file"],
                    "current_signature": row["signature"],
                    "violation_type": "TOO_MANY_POSITIONAL_ARGS",
                    "public": True,
                    "call_sites": callers,
                    "proposed_signature": f"{name}({positional[0]}, *, {', '.join(positional[1:])})",
                    "breaking_change": bool(callers),
                    "compatibility_strategy": "review callers before canonical signature change",
                    "tests": [],
                }
            )
    return rows, violations


def provenance():
    rows, counts = [], defaultdict(int)
    for layer in LAYERS:
        package = PLATFORM / layer / layer
        defs = definitions(package)
        manifest = set(manifest_elements(package))
        selected = {n: v for n, v in defs.items() if not manifest or n in manifest}
        sha = subprocess.check_output(
            ["git", "-C", str(PLATFORM / layer), "rev-parse", "HEAD"], text=True
        ).strip()
        for name, (path, _node) in sorted(selected.items()):
            rel = path.relative_to(PLATFORM / layer).as_posix()
            rows.append(
                {
                    "name": name,
                    "layer": layer,
                    "canonical_path": rel,
                    "canonical_sha": sha,
                    "local_path": None,
                    "canonical_hash": sha256(path),
                    "local_hash": None,
                    "relationship": "CANONICAL",
                    "classification": "CANONICAL_SOURCE",
                }
            )
            counts["CANONICAL_SOURCE"] += 1
    lock = MNEME / "3o-replication-lock.json"
    if lock.exists():
        data = json.loads(lock.read_text(encoding="utf-8"))
        entries = []
        for pkg in data.get("packages", {}).values():
            for entry in pkg.get("closure", []):
                entry = dict(entry)
                entry.setdefault("canonical_sha", pkg.get("commit"))
                entry.setdefault("canonical_repo", pkg.get("repo"))
                entries.append(entry)
        entries.extend(
            x
            for x in data.get("runtime_closure", [])
            if x.get("classification") == "EXACT_CANONICAL_COPY"
        )
        for item in entries:
            local = MNEME / item["local_path"]
            canonical = (
                Path(item["canonical_repo"]) / item.get("canonical_path", "")
                if item.get("canonical_repo")
                else None
            )
            lh = sha256(local) if local.exists() else None
            canonical_hash = (
                git_blob_hash(
                    Path(item["canonical_repo"]),
                    item.get("canonical_sha"),
                    item.get("canonical_path"),
                )
                if item.get("canonical_repo")
                else None
            )
            if canonical_hash is None and canonical and canonical.exists():
                canonical_hash = sha256(canonical)
            exact = bool(
                local.exists()
                and canonical_hash
                and lh == canonical_hash
                and item.get("exact_match") is True
            )
            cls = "CONTROLLED_EXACT_REPLICA" if exact else "REAL_DUPLICATE_IMPLEMENTATION"
            rows.append(
                {
                    "name": item.get("canonical_element", item.get("element")),
                    "layer": item.get("canonical_element", "").split(".")[0],
                    "canonical_path": item.get("canonical_path"),
                    "canonical_sha": item.get("canonical_sha"),
                    "local_path": item.get("local_path"),
                    "canonical_hash": canonical_hash or item.get("canonical_sha256"),
                    "local_hash": lh,
                    "relationship": "EXACT_REPLICA" if exact else "INDEPENDENT_IMPLEMENTATION",
                    "classification": cls,
                    "exact_match": exact,
                }
            )
            counts[cls] += 1
    return rows, dict(counts)


def main() -> int:
    inventory, violations = build_public_inventory()
    prov, counts = provenance()
    out = ROOT / "artifacts/3o-v3"
    out.mkdir(parents=True, exist_ok=True)
    source_sha = subprocess.check_output(
        ["git", "-C", str(PLATFORM / "oprim"), "rev-parse", "HEAD"], text=True
    ).strip()
    (out / "oprim-public-api.json").write_text(
        json.dumps(
            {"schema_version": 1, "source_sha": source_sha, "elements": inventory},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "oprim-signature-migration.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "initial_count": len(violations),
                "recalculated_count": len(violations),
                "violations": violations,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "implementation-provenance-matrix.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "scope": [str(PLATFORM / x) for x in LAYERS],
                "counts": counts,
                "symbols": prov,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    prior = ROOT / "artifacts/3o-v3/single-oprim-oskills.json"
    old = json.loads(prior.read_text(encoding="utf-8")).get("oskills", []) if prior.exists() else []
    classified = []
    for row in old:
        n = row.get("distinct_oprims", 0)
        category = (
            "DEAD_OR_STALE"
            if n == 0
            else "NEEDS_REDESIGN"
            if n == 1
            else "LEGIT_OSKILL_WITH_UNDETECTED_COMPOSITION"
        )
        classified.append(
            {
                **row,
                "classification": category,
                "classification_basis": "AST direct distinct oprim call count; M3 migration intentionally not performed",
            }
        )
    (out / "single-oprim-oskill-classification.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": str(prior),
                "count": len(classified),
                "items": classified,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "PLATFORM_CANONICAL_SYMBOLS": counts.get("CANONICAL_SOURCE", 0),
                "CONTROLLED_EXACT_REPLICA": counts.get("CONTROLLED_EXACT_REPLICA", 0),
                "REAL_DUPLICATE_IMPLEMENTATIONS": counts.get("REAL_DUPLICATE_IMPLEMENTATION", 0),
                "OPRIM_PUBLIC_ELEMENTS": len(inventory),
                "OPRIM_SIGNATURE_VIOLATIONS_RECALCULATED": len(violations),
                "AFFECTED_CALL_SITES": sum(len(x["call_sites"]) for x in violations),
                "SINGLE_OPRIM_ROWS": len(classified),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
