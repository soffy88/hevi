"""3O v3 Layer4 gate: business code cannot recreate canonical 3O algorithms."""
from __future__ import annotations

import sys

from _3o_common import CANONICAL, HEVI, import_edges, parse


def main() -> int:
    violations: list[str] = []
    for path in HEVI.rglob("*.py"):
        if "__pycache__" in path.parts or any(part in CANONICAL for part in path.relative_to(HEVI).parts):
            continue
        tree = parse(path)
        # A Layer4 function name is not evidence of duplicated 3O logic.  The
        # authority signal is importing a project-local 3O namespace.
        for _target, module, line in import_edges(tree):
            if module.startswith(("hevi.oprim", "hevi.oskill", "hevi.omodul")):
                violations.append(f"{path.relative_to(HEVI)}:{line}: local 3O import {module}")
    for item in violations:
        print(item)
    return int(bool(violations))


if __name__ == "__main__":
    sys.exit(main())
