"""3O v3 gate: obase is infrastructure and never depends upward."""
from __future__ import annotations

import sys

from _3o_common import canonical_sources, import_edges, parse


def main() -> int:
    violations = [f"{s.rel}:{line}: obase -> {target}" for s in canonical_sources("obase") for target, _, line in import_edges(parse(s.path)) if target in {"oprim", "oskill", "omodul"}]
    for item in violations:
        print(item)
    return int(bool(violations))


if __name__ == "__main__":
    sys.exit(main())
