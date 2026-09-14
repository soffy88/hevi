"""3O v3 single-source gate: local implementations cannot shadow canonical code."""

from __future__ import annotations

import sys
from collections import defaultdict

from _3o_common import all_sources, has_real_implementation, parse


def main() -> int:
    names: defaultdict[str, list[str]] = defaultdict(list)
    violations: list[str] = []
    for source in all_sources():
        tree = parse(source.path)
        if source.local and has_real_implementation(tree):
            violations.append(f"{source.rel}: local implementation")
        for node in tree.body:
            if hasattr(node, "name") and isinstance(node.name, str):
                names[f"{source.layer}.{node.name}"].append(source.rel)
    for key, paths in names.items():
        if len(paths) > 1 and any("hevi/" in p for p in paths):
            violations.append(f"{key}: duplicate entries {paths}")
    for item in sorted(set(violations)):
        print(item)
    return int(bool(violations))


if __name__ == "__main__":
    sys.exit(main())
