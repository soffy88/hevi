"""3O v3 gate: canonical public element names describe capability, not owner."""

from __future__ import annotations

import sys

from _3o_common import PROJECT_PREFIXES, canonical_sources, defined_functions, parse


def main() -> int:
    violations: list[str] = []
    for source in canonical_sources():
        tree = parse(source.path)
        violations.extend(
            f"{source.rel}:{node.lineno}:{node.name}"
            for node in defined_functions(tree)
            if node.name.startswith(PROJECT_PREFIXES)
        )
    for item in violations:
        print(item)
    return int(bool(violations))


if __name__ == "__main__":
    sys.exit(main())
