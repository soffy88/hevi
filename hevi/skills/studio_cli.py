"""hevi-studio CLI —— 列产线 / 调工具 / 签发工单。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any


def _parse_slot(raw: str) -> tuple[str, Any]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("slot must be key=value")
    key, value = raw.split("=", 1)
    if value.startswith(("[", "{")):
        try:
            return key, json.loads(value)
        except json.JSONDecodeError:
            return key, value
    return key, value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="hevi-studio: 制片厂产线")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("lines", help="列出产线")
    sub.add_parser("tools", help="列出工具")
    run_p = sub.add_parser("run", help="签发工单")
    run_p.add_argument("line_id")
    run_p.add_argument("--slot", action="append", default=[], type=_parse_slot)
    args = parser.parse_args(argv)

    if args.cmd == "lines":
        from hevi.studio.recipes import list_recipes

        for rec in list_recipes():
            print(f"{rec.id}\t{rec.product}\t{rec.handoff}\t{rec.summary}")
        return 0
    if args.cmd == "tools":
        from hevi.studio.tools import list_tools

        for spec in list_tools():
            print(f"{spec.tool_id}\t{spec.kind}\t{spec.summary}")
        return 0

    from hevi.studio.slate import Slate, run_slate

    slots = dict(args.slot)
    result = asyncio.run(run_slate(Slate(line_id=args.line_id, slots=slots)))
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.status in {"scheduled", "planned", "blocked"} else 1


if __name__ == "__main__":
    sys.exit(main())
