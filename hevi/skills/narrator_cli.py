"""hevi 侧 Narrator AI CLI 入口。无 key 时打印安装提示并退出 2。"""

from __future__ import annotations

import argparse
import json
import sys

from hevi.narrator.client import ALLOWED, NarratorUnavailable, narrator_status, run_narrator


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="hevi narrator-ai-cli wrapper")
    parser.add_argument("verb", nargs="?", help=f"one of {sorted(ALLOWED)}")
    parser.add_argument("extra", nargs=argparse.REMAINDER, default=[])
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)
    if args.status or not args.verb:
        print(json.dumps(narrator_status(), ensure_ascii=False, indent=2))
        return 0 if narrator_status()["cli"] and narrator_status()["app_key"] else 2
    try:
        print(json.dumps(run_narrator(args.verb, list(args.extra)), ensure_ascii=False, indent=2))
    except NarratorUnavailable as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
