"""Build the M2 provenance and OPRIM contract migration artifacts."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEVI = ROOT / "hevi"
PLATFORM = Path("/data/soffy/projects/platform/3O")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def layer(path: Path) -> str | None:
    return next((x for x in ("oprim", "oskill", "omodul", "obase", "oservi") if x in path.parts), None)


def public_nodes(path: Path) -> list[ast.AST]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not n.name.startswith("_")]


def main() -> int:
    local_rows: list[dict[str, object]] = []
    signature_rows: list[dict[str, object]] = []
    for path in sorted(HEVI.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        current_layer = layer(path)
        if current_layer is None:
            continue
        for node in public_nodes(path):
            local_path = str(path.relative_to(ROOT))
            # These are Hevi project namespaces, not a second canonical copy.
            local_rows.append({
                "name": node.name,
                "layer": current_layer,
                "canonical_path": None,
                "canonical_sha": None,
                "local_path": local_path,
                "canonical_hash": None,
                "local_hash": digest(path),
                "relationship": "LAYER4",
                "classification": "LAYER4_IMPLEMENTATION",
            })
            if current_layer == "oprim" and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                positional = node.args.posonlyargs + node.args.args
                if len(positional) > 1:
                    names = [a.arg for a in positional]
                    kind = "TOO_MANY_POSITIONAL_ARGS"
                    text = path.read_text(encoding="utf-8").lower()
                    if any(x in text for x in ("user_id", "project_id", "job_id", "subprocess", "write_text", "httpx", "requests")):
                        kind = "BUSINESS_OBJECT_POSITIONAL"
                    signature_rows.append({
                        "symbol": node.name,
                        "file": local_path,
                        "current_signature": f"{node.name}({', '.join(names)})",
                        "violation_type": kind,
                        "public": True,
                        "call_sites": [],
                        "proposed_signature": f"{node.name}({names[0]}, *, {', '.join(names[1:])})",
                        "breaking_change": True,
                        "compatibility_strategy": "classify Layer4 before changing canonical API",
                        "tests": [],
                    })
    out = ROOT / "artifacts/3o-v3"
    out.mkdir(parents=True, exist_ok=True)
    (out / "implementation-provenance-matrix.json").write_text(json.dumps({"scope": [str(PLATFORM / x) for x in ("obase", "oprim", "oskill", "omodul", "oservi")], "symbols": local_rows}, ensure_ascii=False, indent=2) + "\n")
    (out / "oprim-signature-migration.json").write_text(json.dumps({"initial_count": len(signature_rows), "violations": signature_rows}, ensure_ascii=False, indent=2) + "\n")
    print(f"LOCAL_SYMBOLS={len(local_rows)}")
    print(f"OPRIM_SIGNATURE_ROWS={len(signature_rows)}")
    print("CLASSIFICATION=MNEME_PLATFORM_3O_V3_M2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
