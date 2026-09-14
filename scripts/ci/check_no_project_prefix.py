"""3O v3.0 CI check: no project prefix on 3O module identity (SPEC §2.1).

Element identity is derived from the flat element name alone.  A module file
inside a 3O layer must not encode the owning project (``hevi_*``/``inkos_*``),
and a layer module path must not be nested under a project package.

Exit code: 0 = pass, 1 = violation.
"""

from __future__ import annotations

import sys

from _3o_common import LAYERS, has_project_prefix, rel, report


def main() -> int:
    from _3o_common import CREATIVE

    violations: list[str] = []
    for layer in LAYERS:
        directory = CREATIVE / layer
        for path in sorted(directory.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            parts = path.relative_to(directory).with_suffix("").parts
            for part in parts:
                if part == "__init__":
                    continue
                if has_project_prefix(part):
                    violations.append(f"{layer}::{rel(path)}")
                    break
    return report("check_no_project_prefix", violations, header="3O project-prefixed module paths:")


if __name__ == "__main__":
    sys.exit(main())
