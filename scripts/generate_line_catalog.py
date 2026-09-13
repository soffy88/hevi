#!/usr/bin/env python3
"""Generate the line catalog from the YAML authority, never a hard-coded count."""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lines-dir", type=Path, default=Path("hevi/studio/lines"))
    parser.add_argument("--output", type=Path, default=Path("docs/generated/line_catalog.md"))
    args = parser.parse_args()
    rows: list[str] = ["# HEVI Studio line catalog", "", "Generated from `hevi/studio/lines/*.yaml`; do not edit manually.", "", "| Name | Version | Description | Stages | Provider dependencies | Renderer/backend | Qualification status | Last qualified SHA |", "|---|---|---|---|---|---|---|---|"]
    for path in sorted(args.lines_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        stages = ", ".join(stage["name"] for stage in data.get("pipeline", {}).get("stages", []))
        tools = ", ".join(data.get("tools", []))
        rows.append(f"| {data['id']} | {data.get('version', '1')} | {data.get('summary', '')} | {stages} | {tools} | {data.get('render_runtime', '')} | UNQUALIFIED | — |")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
