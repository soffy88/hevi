"""3O v3 gate for every public canonical omodul transaction."""
from __future__ import annotations

import ast
import sys
from _3o_common import canonical_sources, public_functions, parse


def main() -> int:
    violations: list[str] = []
    for source in canonical_sources("omodul"):
        tree = parse(source.path)
        for fn in public_functions(tree):
            args = [a.arg for a in fn.args.posonlyargs + fn.args.args]
            if args[:3] != ["config", "input_data", "output_dir"]:
                violations.append(f"{source.rel}:{fn.lineno}:{fn.name}: signature")
            if not any(isinstance(n, ast.Return) and isinstance(n.value, ast.Dict) and any(isinstance(k, ast.Constant) and k.value == "status" for k in n.value.keys) for n in ast.walk(fn)):
                violations.append(f"{source.rel}:{fn.lineno}:{fn.name}: missing status/error return")
    for item in violations:
        print(item)
    return int(bool(violations))


if __name__ == "__main__":
    sys.exit(main())
