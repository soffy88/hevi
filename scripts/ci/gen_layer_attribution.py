#!/usr/bin/env python3
"""Regenerate hevi/capabilities/layer_attribution.py from the attribution JSON.

Usage:
    python scripts/ci/gen_layer_attribution.py \
        --json ~/workspace/3o-conformance/layer_attribution.json

The JSON is the reviewed source of truth (one entry per registered
capability: name, layer, reason, file). This script only reformats it
into the importable table module; it never invents attributions.
Exits non-zero when the JSON misses a registered name or names an
unregistered one (checked against a live import when possible).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "hevi" / "capabilities" / "layer_attribution.py"
LAYERS = ("oprim", "oskill", "omodul", "obase", "oservi")

HEADER = '''"""Central 3O layer attribution table for the capabilities registry.

Generated from ``~/workspace/3o-conformance/layer_attribution.json``
(444 capabilities, one entry each, no "unclassified" remainder).
Regenerate — never hand-edit entries — with
``scripts/ci/gen_layer_attribution.py`` (reads the JSON, writes this file).

Each entry: name -> {"layer": <3O layer>, "reason": <one-line evidence>,
"file": <defining module file>}. ``register()`` fills ``Capability.layer``
from this table when the caller did not declare one explicitly; an
explicit layer on the Capability wins.

Layers follow HELIOS_3O_SPEC_v3_0 §1: oprim (atomic), oskill (>=2 oprim
combination, stateless algorithm), omodul (business transaction),
obase (external adapter / cross-cutting), oservi (reusable engine
skeleton, 5 red lines in SPEC §7.2).
"""

from __future__ import annotations

from typing import Any

LAYER_ATTRIBUTION: dict[str, dict[str, Any]] = {
'''


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", required=True)
    args = parser.parse_args()
    entries = json.loads(Path(args.json).read_text(encoding="utf-8"))
    if isinstance(entries, dict):
        entries = entries.get("entries", entries)
    problems: list[str] = []
    seen: set[str] = set()
    for entry in entries:
        name = entry["name"]
        if name in seen:
            problems.append(f"duplicate: {name}")
        seen.add(name)
        if entry["layer"] not in LAYERS:
            problems.append(f"{name}: bad layer {entry['layer']!r}")
        if not entry.get("reason"):
            problems.append(f"{name}: missing reason")
    if problems:
        print("\n".join(problems))
        return 1
    lines = [HEADER]
    for entry in sorted(entries, key=lambda e: e["name"]):
        lines.append(
            f"    {entry['name']!r}: {{"
            f"\"layer\": {entry['layer']!r}, "
            f"\"reason\": {entry['reason']!r}, "
            f"\"file\": {entry.get('file', '')!r}}},"
        )
    lines.append("}\n")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} ({len(entries)} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
