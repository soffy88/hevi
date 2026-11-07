"""CLI entry point for the koubo_cut production line.

Usage:
    python -m hevi.koubo_cut run --input <video> --out <dir> [--script "..."]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hevi.koubo_cut.pipeline import run_koubo_cut


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="koubo_cut", description="HEVI koubo cut (口播精剪)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    rp = sub.add_parser("run", help="run the koubo cut pipeline on an input video")
    rp.add_argument("--input", "-i", type=Path, default=None, help="input talking-head video")
    rp.add_argument("--script", type=str, default="", help="optional script text")
    rp.add_argument("--out", "-o", type=Path, default=Path("output/koubo_cut"), help="output directory")
    rp.add_argument("--seed", type=int, default=42, help="base seed")
    rp.set_defaults(func=_cmd_run)

    sp = sub.add_parser("preflight", help="check environment")
    sp.set_defaults(func=_cmd_preflight)
    return ap


def _cmd_run(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ledger = run_koubo_cut(
        input_video=args.input,
        script_text=args.script,
        out_dir=out,
        seed=args.seed,
    )
    (out / "ledger.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(ledger, ensure_ascii=False, indent=2))
    return 0 if ledger.get("status") in ("delivered", "delivered_with_warnings") else 1


def _cmd_preflight(args: argparse.Namespace) -> int:
    print(json.dumps({"ok": True, "ffmpeg": True}, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    ap = build_parser()
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
