"""3O v3 gate: canonical packages are flat; HEVI namespaces may only be shims."""
from __future__ import annotations

import sys

from _3o_common import CANONICAL, all_sources, has_real_implementation, parse


def main() -> int:
    violations: list[str] = []
    for source in all_sources():
        if source.local and has_real_implementation(parse(source.path)):
            violations.append(f"{source.rel}: local real {source.layer} implementation")
        if not source.local:
            rel = source.path.name
            if "." in rel and rel.split(".")[0] in CANONICAL:
                violations.append(f"{source.rel}: non-flat canonical module")
    for item in violations:
        print(item)
    return int(bool(violations))


if __name__ == "__main__":
    sys.exit(main())
