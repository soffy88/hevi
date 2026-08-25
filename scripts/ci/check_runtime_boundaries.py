"""Fail CI when API routers regain a durable-task execution escape hatch.

The API may submit a PostgreSQL task, but it must not call the compatibility
``run_task_background`` method itself.  The only allowed in-process seam is
``hevi.tasks.dispatch`` which rejects PostgreSQL repositories at runtime.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTERS = ROOT / "hevi" / "api" / "routers"


def main() -> int:
    violations: list[str] = []
    for path in ROUTERS.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "run_task_background":
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    if violations:
        print("runtime boundary violations:")
        for violation in violations:
            print(f"  - {violation}")
        return 1
    print("check_runtime_boundaries: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
