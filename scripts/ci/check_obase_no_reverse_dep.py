"""3O v3.0 CI check: obase never depends on an upper layer (SPEC §3.1).

``obase`` owns canonical objects, identity, authority and provenance.  The
dependency direction is strictly downward: obase may only depend on stdlib and
third-party libraries, never on ``oprim``/``oskill``/``omodul``/``oservi`` or
any other HEVI creative layer.

Exit code: 0 = pass, 1 = violation.
"""

from __future__ import annotations

import ast
import sys

from _3o_common import OBASE, rel, report

FORBIDDEN_PREFIXES = (
    "hevi.creative.oprim",
    "hevi.creative.oskill",
    "hevi.creative.omodul",
    "hevi.creative.oservi",
    "hevi.creative",
)


def _imported_modules(tree: ast.AST) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


def main() -> int:
    violations: list[str] = []
    for path in sorted(OBASE.glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        except SyntaxError:
            violations.append(f"unparseable::{rel(path)}")
            continue
        violations.extend(
            f"{rel(path)}::{module}"
            for module in _imported_modules(tree)
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in FORBIDDEN_PREFIXES
            )
        )
    return report("check_obase_no_reverse_dep", violations, header="3O obase reverse dependencies:")


if __name__ == "__main__":
    sys.exit(main())
