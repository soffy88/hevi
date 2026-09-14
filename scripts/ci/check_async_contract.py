"""3O v3.0 CI check: async workflow contract (SPEC §5.3 / §5.4).

Any coroutine declared inside a 3O layer must honour the fail-closed workflow
contract:

  - it never ``raise``s; failures are returned as a ``status`` payload, and
  - a ``*_workflow`` coroutine takes ``(config, input_data, output_dir)`` and
    declares ``_enabled_pillars``.

The check is a no-op until a new coroutine is admitted, at which point it is the
gate that keeps a new async element compliant from line one.

Exit code: 0 = pass, 1 = violation.
"""

from __future__ import annotations

import ast
import sys

from _3o_common import CREATIVE, LAYERS, rel, report

REQUIRED_ARGS = ("config", "input_data", "output_dir")


def _returns_status(node: ast.AsyncFunctionDef) -> bool:
    for inner in ast.walk(node):
        if isinstance(inner, ast.Return) and isinstance(inner.value, ast.Dict):
            for key in inner.value.keys:
                if isinstance(key, ast.Constant) and key.value == "status":
                    return True
    return False


def _declares_pillars(node: ast.AsyncFunctionDef) -> bool:
    for stmt in node.body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_enabled_pillars" for t in stmt.targets
        ):
            return True
    return False


def _raises(node: ast.AsyncFunctionDef) -> bool:
    return any(isinstance(inner, ast.Raise) for inner in ast.walk(node))


def main() -> int:
    violations: list[str] = []
    for layer in LAYERS:
        for path in sorted((CREATIVE / layer).glob("*.py")):
            if path.name == "__init__.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            except SyntaxError:
                violations.append(f"unparseable::{rel(path)}")
                continue
            for node in tree.body:
                if not isinstance(node, ast.AsyncFunctionDef):
                    continue
                if _raises(node):
                    violations.append(f"{rel(path)}::{node.name}::raises")
                if node.name.endswith("_workflow"):
                    argnames = [a.arg for a in node.args.args]
                    if any(name not in argnames for name in REQUIRED_ARGS):
                        violations.append(f"{rel(path)}::{node.name}::bad_signature")
                    if not _returns_status(node):
                        violations.append(f"{rel(path)}::{node.name}::no_status_return")
                    if not _declares_pillars(node):
                        violations.append(f"{rel(path)}::{node.name}::no_enabled_pillars")
    return report("check_async_contract", violations, header="3O async contract violations:")


if __name__ == "__main__":
    sys.exit(main())
