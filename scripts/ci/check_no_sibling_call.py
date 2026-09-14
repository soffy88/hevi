"""3O v3 import/call graph direction gate."""

from __future__ import annotations

import sys

from _3o_common import CANONICAL, all_sources, import_edges, parse

FORBIDDEN = {
    ("oprim", "oskill"),
    ("oprim", "omodul"),
    ("oskill", "omodul"),
    ("obase", "oprim"),
    ("obase", "oskill"),
    ("obase", "omodul"),
}


def main() -> int:
    violations: list[str] = []
    for source in all_sources():
        if source.layer not in CANONICAL:
            continue
        tree = parse(source.path)
        for target, module, line in import_edges(tree):
            if (source.layer, target) in FORBIDDEN:
                violations.append(f"{source.rel}:{line}: {source.layer} -> {target} ({module})")
            if (
                source.layer == "omodul"
                and target == "omodul"
                and not any(part.startswith("_") for part in module.split("."))
            ):
                violations.append(f"{source.rel}:{line}: sibling omodul import ({module})")
            if source.layer == "oservi" and target in {"oprim", "oskill", "omodul"}:
                violations.append(f"{source.rel}:{line}: hardcoded oservi element ({module})")
        # Detect direct calls through imported canonical module aliases, not merely co-imports.
        imported = {root for root, _, _ in import_edges(tree)}
        if source.layer == "oprim" and imported & {"oskill", "omodul"}:
            violations.append(f"{source.rel}: forbidden oprim lower-boundary call graph edge")
    for item in sorted(set(violations)):
        print(item)
    return int(bool(violations))


if __name__ == "__main__":
    sys.exit(main())
