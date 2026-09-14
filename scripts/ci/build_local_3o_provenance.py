"""Build provenance for every current HEVI local 3O implementation."""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
from pathlib import Path

from _3o_common import CANONICAL, HEVI, ROOT, has_real_implementation, parse

BASE = "0f55f43a161b070e011dc789bda95d07b3efc071"
HEAD = "a6f6c2bcb3c3c97324cfe1ac3e3650ec6451b720"


def git_added(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "log", "--diff-filter=A", "--format=%H", "--", str(path.relative_to(ROOT))],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    return result.stdout.splitlines()[-1] if result.stdout.splitlines() else None


def existed(commit: str, path: Path) -> bool:
    return subprocess.run(
        ["git", "cat-file", "-e", f"{commit}:{path.relative_to(ROOT)}"],
        cwd=ROOT, capture_output=True, check=False,
    ).returncode == 0


def main() -> int:
    rows: list[dict] = []
    tree_files = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", HEAD, "hevi"], cwd=ROOT, text=True
    ).splitlines()
    for relative in sorted(path for path in tree_files if path.endswith(".py")):
        path = ROOT / relative
        parts = Path(relative).relative_to(HEVI.relative_to(ROOT)).parts
        layer = next((part for part in parts if part in CANONICAL), None)
        if layer is None:
            continue
        source = subprocess.check_output(["git", "show", f"{HEAD}:{relative}"], cwd=ROOT, text=True)
        tree = ast.parse(source, filename=relative)
        if not has_real_implementation(tree):
            continue
        defs = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        symbol = ",".join(node.name for node in defs) or path.stem
        body_hash = hashlib.sha256(source.encode()).hexdigest()
        rows.append({
            "path": str(path.relative_to(ROOT)), "module": ".".join(path.relative_to(ROOT).with_suffix("").parts),
            "symbol": symbol, "layer": layer,
            "line_range": [1, len(source.splitlines())],
            "git_introduced_commit": git_added(path), "exists_at_0f55f43": existed(BASE, path),
            "exists_at_a6f6c2b": existed(HEAD, path), "canonical_repo": None,
            "canonical_symbol": None, "canonical_sha": None, "implementation_kind": "substantive_module",
            "body_hash": body_hash, "canonical_body_hash": None, "imports": [], "callers": [], "consumers": [],
            "classification": "PREEXISTING_NEWLY_DISCOVERED" if existed(BASE, path) else "NEW_REGRESSION",
        })
    out = ROOT / "artifacts/3o-v3/local-3o-121-provenance.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"source": "current direct AST/file scan", "base": BASE, "head": HEAD, "count": len(rows), "items": rows}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"LOCAL_3O_PROVENANCE_ITEMS={len(rows)}")
    print(f"LOCAL_121_NEW_SINCE_0F55={sum(item['classification'] == 'NEW_REGRESSION' for item in rows)}")
    print(f"LOCAL_121_ALREADY_EXISTED_AT_0F55={sum(item['classification'] == 'PREEXISTING_NEWLY_DISCOVERED' for item in rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
