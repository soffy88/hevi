"""3O v3.0 CI check: oprim exported primitives are keyword-only (SPEC §4.2).

A 3O primitive (``hevi/creative/oprim``) exposes a stable, self-describing
interface: every parameter is keyword-only so call sites cannot depend on
positional order.  Legacy primitives written before v3.0 are recorded in the
legacy debt ledger; **new** primitives must comply from line one.

Exit code: 0 = pass, 1 = violation.
"""

from __future__ import annotations

import ast
import sys

from _3o_common import LAYERS, rel, report  # noqa: F401  (LAYERS kept for symmetry)


def _positional(param: ast.arguments) -> list[str]:
    names = [a.arg for a in param.posonlyargs]
    names.extend(a.arg for a in param.args)
    return [name for name in names if name not in {"self", "cls"}]


def main() -> int:
    from _3o_common import CREATIVE

    violations: list[str] = []
    for path in sorted((CREATIVE / "oprim").glob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        except SyntaxError:
            violations.append(f"unparseable::{rel(path)}")
            continue
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("_"):
                continue
            positional = _positional(node.args)
            if positional:
                violations.append(f"{rel(path)}::{node.name}")
    return report("check_oprim_keyword_only", violations, header="3O oprim positional parameters:")


if __name__ == "__main__":
    sys.exit(main())
