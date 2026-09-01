"""Standalone short-drama screenwriter CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from hevi.director.pipeline_schemas import Concept
from hevi.director.screenplay import generate_screenplay_draft
from hevi.shortdrama.screenwriter import review_screenplay, screenplay_markdown


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ai-short-drama-screenwriter")
    parser.add_argument("--premise", required=True)
    parser.add_argument("--raw-text", default="")
    parser.add_argument("--title", default="短剧单集")
    parser.add_argument("--genre", default="")
    parser.add_argument("--tone", default="")
    parser.add_argument("--style", default="电影感")
    parser.add_argument("--mode", choices=("adaptive", "literal", "staged"), default="adaptive")
    parser.add_argument("--out-dir", type=Path, default=Path(".hevi_shortdrama"))
    args = parser.parse_args(argv)
    screenplay = asyncio.run(
        generate_screenplay_draft(
            concept=Concept(theme=args.premise, tone=args.tone, style=args.style, quality_bar=args.genre),
            material_text=args.raw_text.strip() or args.premise,
            mode=args.mode,
        )
    )
    review = review_screenplay(screenplay)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "screenplay.json").write_text(
        json.dumps(screenplay.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out_dir / "screenplay.md").write_text(
        screenplay_markdown(screenplay, title=args.title), encoding="utf-8"
    )
    (args.out_dir / "review.json").write_text(
        json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"status": "ok", "out_dir": str(args.out_dir), "review": review}, ensure_ascii=False))
    return 0 if review["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
