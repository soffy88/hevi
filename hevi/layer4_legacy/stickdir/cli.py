"""stickdir 命令行入口。

    PYTHONPATH=$PWD .venv/bin/python -m hevi.layer4_legacy.stickdir.cli \
        --copy-file x.txt --aspect 9:16 --duration 30 --style 1B --out out/

``--render`` 时进一步走 CPU 渲染器出 mp4(见 :mod:`hevi.layer4_legacy.stickdir.render`)。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hevi.layer4_legacy.stickdir import llm, proposal


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stickdir", description="火柴人导演线: 提案 + CPU 渲染")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--copy-file", type=Path, help="文案文件路径(UTF-8)")
    src.add_argument("--copy", type=str, help="文案字符串")
    p.add_argument("--aspect", required=True, choices=["9:16", "16:9"])
    p.add_argument("--style", required=True, choices=["1A", "1B", "2A", "2B", "3"])
    p.add_argument("--duration", type=int, default=None, help="30/60/90/120, 缺省 60")
    p.add_argument("--out", type=Path, required=True, help="输出目录")
    p.add_argument("--no-llm", action="store_true", help="强制确定性 fallback, 不调 ollama")
    p.add_argument("--render", action="store_true", help="生成提案后继续 CPU 渲染 mp4")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--name", type=str, default=None, help="输出文件名(不含扩展名)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    copy = args.copy_file.read_text(encoding="utf-8") if args.copy_file else args.copy
    completer = None if args.no_llm else llm.make_completer()
    prop = proposal.build_proposal(
        copy=copy, aspect=args.aspect, style=args.style, duration=args.duration, complete=completer
    )
    jpath, mpath = proposal.write(prop, args.out)
    print(f"proposal.json -> {jpath}")
    print(f"proposal.md   -> {mpath}")
    print(json.dumps(prop.data["self_checks"], ensure_ascii=False))

    if args.render:
        from hevi.layer4_legacy.stickdir import render

        stem = (
            args.name
            or f"stickdir_{args.style}_{args.aspect.replace(':', 'x')}_{prop.data['duration']}s"
        )
        out_mp4 = args.out / f"{stem}.mp4"
        render.render_proposal(prop.data, out_mp4, fps=args.fps)
        print(f"mp4           -> {out_mp4}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
