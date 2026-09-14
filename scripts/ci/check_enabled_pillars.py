"""3O v3 gate for real pillars on every canonical omodul."""
from __future__ import annotations

import ast
import sys
from _3o_common import PILLARS, canonical_sources, parse


def main() -> int:
    violations: list[str] = []
    for source in canonical_sources("omodul"):
        tree = parse(source.path)
        declarations: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "_enabled_pillars" and isinstance(node.value, (ast.Set, ast.Tuple, ast.List)):
                        declarations |= {x.value for x in node.value.elts if isinstance(x, ast.Constant) and isinstance(x.value, str)}
        bad = declarations - PILLARS
        if not declarations:
            violations.append(f"{source.rel}: missing _enabled_pillars")
        if not declarations & PILLARS:
            violations.append(f"{source.rel}: no enabled pillar")
        if bad:
            violations.append(f"{source.rel}: invalid pillars {sorted(bad)}")
        if "fingerprint" in declarations and not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "compute_fingerprint_for" for n in ast.walk(tree)):
            violations.append(f"{source.rel}: fingerprint without compute_fingerprint_for")
    for item in violations:
        print(item)
    return int(bool(violations))


if __name__ == "__main__":
    sys.exit(main())
