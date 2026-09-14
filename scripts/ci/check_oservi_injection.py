"""3O v3 gate: oservi consumes manifests/contracts, never concrete elements."""

from __future__ import annotations

import sys

from _3o_common import canonical_sources, import_edges, parse


def main() -> int:
    violations = [
        f"{s.rel}:{line}: concrete {target} import"
        for s in canonical_sources("oservi")
        for target, _, line in import_edges(parse(s.path))
        if target in {"oprim", "oskill", "omodul"}
    ]
    for item in violations:
        print(item)
    return int(bool(violations))


if __name__ == "__main__":
    sys.exit(main())
