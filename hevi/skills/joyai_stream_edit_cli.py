"""JoyAI streaming V2V skill CLI."""

from __future__ import annotations

import argparse
import json
import sys

from hevi.joyai.omodul.stream_edit import capabilities, create_session, get_session
from hevi.joyai.oprim.stream_contract import frame_budget


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="joyai-stream-edit: causal V2V session contracts")
    sub = parser.add_subparsers(dest="verb", required=True)

    sub.add_parser("capabilities", help="显示真实 Provider 与协议能力")
    budget = sub.add_parser("budget", help="估算原始帧预算")
    budget.add_argument("--width", type=int, default=840)
    budget.add_argument("--height", type=int, default=480)
    budget.add_argument("--fps", type=int, default=24)
    budget.add_argument("--seconds", type=float, default=1.0)
    create = sub.add_parser("create", help="创建会话")
    create.add_argument("--prompt", required=True)
    create.add_argument("--source-mode", choices=["live", "upload"], default="live")
    create.add_argument("--width", type=int, default=840)
    create.add_argument("--height", type=int, default=480)
    create.add_argument("--fps", type=int, default=24)
    create.add_argument("--model", default="joyai-video-edit")
    inspect = sub.add_parser("inspect", help="检查进程内会话")
    inspect.add_argument("--session", required=True)
    args = parser.parse_args(argv)

    if args.verb == "capabilities":
        payload = capabilities()
    elif args.verb == "budget":
        payload = frame_budget(
            width=args.width,
            height=args.height,
            fps=args.fps,
            seconds=args.seconds,
        )
    elif args.verb == "create":
        payload = create_session(
            prompt=args.prompt,
            source_mode=args.source_mode,
            width=args.width,
            height=args.height,
            fps=args.fps,
            model=args.model,
        ).to_dict()
    else:
        session = get_session(args.session)
        if session is None:
            print("session not found", file=sys.stderr)
            return 1
        payload = session.to_dict()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
