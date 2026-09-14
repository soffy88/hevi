"""3O v3.0 CI check: flat namespace (SPEC §2.1).

Rules enforced over the first-party 3O layers (``hevi/creative/{oprim,oskill,
omodul,oservi}`` and ``hevi/obase``):

  - A layer is *flat*: no nested project sub-package may be introduced under it.
  - A public symbol may not carry a project/vendor prefix (``hevi_*``/``inkos_*``
    and their case variants).  Names are global and unprefixed.

Exit code: 0 = pass, 1 = violation.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from _3o_common import CREATIVE, LAYERS, OBASE, has_project_prefix, rel, report


def _layer_containers() -> list[Path]:
    containers = [CREATIVE / layer for layer in LAYERS]
    containers.append(OBASE)
    return containers


def main() -> int:
    violations: list[str] = []
    for container in _layer_containers():
        violations.extend(
            f"nested_package::{rel(child)}"
            for child in sorted(container.iterdir())
            if child.is_dir() and child.name != "__pycache__"
        )
        for py in sorted(container.glob("*.py")):
            try:
                tree = ast.parse(py.read_text(encoding="utf-8"), str(py))
            except SyntaxError:
                violations.append(f"unparseable::{rel(py)}")
                continue
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if has_project_prefix(node.name):
                        violations.append(f"prefixed_symbol::{rel(py)}::{node.name}")
                elif isinstance(node, ast.Assign):
                    violations.extend(
                        f"prefixed_symbol::{rel(py)}::{target.id}"
                        for target in node.targets
                        if isinstance(target, ast.Name)
                        and target.id != "__all__"
                        and has_project_prefix(target.id)
                    )
    return report("check_flat_namespace", violations, header="3O flat namespace violations:")


if __name__ == "__main__":
    sys.exit(main())
