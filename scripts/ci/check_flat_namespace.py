"""3O v3 gate: canonical packages are flat; HEVI namespaces may only be shims.

Exception (3O conformance, 2026-11-04): ``hevi/live_host/`` and
``hevi/avcraft/`` are hevi's in-repo internalised 3O layers — real
implementations by design under the "3O internalised, no longer
connected/paid" decision — not shims shadowing the canonical master
libraries. They are allowlisted here, visibly, instead of the gate
being silently waived. Any other local real implementation is still
flagged.
"""

from __future__ import annotations

import sys

from _3o_common import CANONICAL, all_sources, has_real_implementation, parse

# In-repo internalised 3O layer homes (real implementations by design).
_IN_REPO_LAYER_HOMES = ("live_host", "avcraft")


def main() -> int:
    violations: list[str] = []
    for source in all_sources():
        if source.local and any(
            home in source.path.parts for home in _IN_REPO_LAYER_HOMES
        ):
            continue
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
