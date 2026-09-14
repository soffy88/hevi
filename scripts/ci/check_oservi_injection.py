"""3O v3.0 CI check: oservi is mechanism-only, handlers are injected (SPEC §3.5).

``oservi`` exposes an externally callable surface.  It must not import the
business layers directly and must not own business state: dispatch tables are
instance state injected by the Layer 4 runtime, never module-level mutable
containers keyed by business identity.

Exit code: 0 = pass, 1 = violation.
"""

from __future__ import annotations

import ast
import sys

from _3o_common import CREATIVE, rel, report

FORBIDDEN_IMPORTS = (
    "hevi.creative.omodul",
    "hevi.creative.oprim",
    "hevi.creative.oskill",
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
    for path in sorted((CREATIVE / "oservi").glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        except SyntaxError:
            violations.append(f"unparseable::{rel(path)}")
            continue
        violations.extend(
            f"business_import::{rel(path)}::{module}"
            for module in _imported_modules(tree)
            if any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in FORBIDDEN_IMPORTS
            )
        )
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, (ast.Dict, ast.List, ast.Set)):
                violations.extend(
                    f"module_state::{rel(path)}::{target.id}"
                    for target in node.targets
                    if isinstance(target, ast.Name) and target.id != "__all__"
                )
    return report("check_oservi_injection", violations, header="3O oservi injection violations:")


if __name__ == "__main__":
    sys.exit(main())
