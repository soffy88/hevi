"""3O v3 gate: public oprim has at most one positional core argument."""

from __future__ import annotations

import sys

from _3o_common import canonical_sources, parse, public_functions


def main() -> int:
    violations: list[str] = []
    for source in canonical_sources("oprim"):
        for fn in public_functions(parse(source.path)):
            positional = fn.args.posonlyargs + fn.args.args
            if len(positional) > 1:
                violations.append(
                    f"{source.rel}:{fn.lineno}:{fn.name} positional={len(positional)}"
                )
    for item in violations:
        print(item)
    return int(bool(violations))


if __name__ == "__main__":
    sys.exit(main())
