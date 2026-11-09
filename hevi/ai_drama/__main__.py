"""CLI: python -m hevi.ai_drama --episode <json> --out <dir> [--provider offline]."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import Pipeline


def main() -> int:
    ap = argparse.ArgumentParser(prog="hevi.ai_drama")
    ap.add_argument("--episode", help="episode JSON (script or {script:...})")
    ap.add_argument("--theme", help="theme when no episode file is given")
    ap.add_argument("--style", default="live_action")
    ap.add_argument("--out", required=True)
    ap.add_argument("--provider", default=None)
    ap.add_argument("--budget", type=float, default=None)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-images", action="store_true", help="skip local image rendering")
    ap.add_argument("--no-lipsync", action="store_true")
    args = ap.parse_args()

    if args.episode:
        data = json.loads(Path(args.episode).read_text(encoding="utf-8"))
        episode = {"script": data["script"]} if "script" in data else ({"script": data} if data.get("scenes") else data)
    else:
        episode = {"theme": args.theme or "一个日常里的异常", "style": args.style}
    report = Pipeline(
        args.out,
        budget_cny=args.budget,
        prefer_provider=args.provider,
        seed=args.seed,
        render_images=not args.no_images,
        lipsync=False if args.no_lipsync else None,
    ).run(episode)
    print(json.dumps({"passed": report.get("passed"), "delivery": report.get("delivery")}, ensure_ascii=False, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
