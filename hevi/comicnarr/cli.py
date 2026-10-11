"""CLI entry point for Comic Narration line.

Usage:
    python -m hevi.comicnarr.cli --topic "为什么猫总爱把东西推下桌" --style comic_color --output output/comic_cat/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hevi.layer4_legacy.comicnarr.omodul_impl.comicnarr_pipeline import (
    comic_narration_workflow,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="HEVI Comic Narration (Pixelle-style zero-cost line)")
    parser.add_argument("--topic", required=True, help="Topic or story snippet")
    parser.add_argument(
        "--style",
        default="comic_color",
        choices=["comic_color", "manga_bw"],
        help="Visual style template",
    )
    parser.add_argument(
        "--subtitle-style",
        default="bottom",
        choices=["bottom", "bubble"],
        help="Subtitle layout",
    )
    parser.add_argument(
        "--engine",
        default="sdturbo_cpu",
        help="Keyframe engine (default: sdturbo_cpu)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/comicnarr"),
        help="Output directory",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Base RNG seed",
    )

    args = parser.parse_args()

    input_data = {
        "topic": args.topic,
        "style": args.style,
        "subtitle_style": args.subtitle_style,
        "keyframe_engine": args.engine,
        "base_seed": args.seed,
    }

    result = comic_narration_workflow({}, input_data, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in {"completed", "succeeded"} else 1


if __name__ == "__main__":
    sys.exit(main())
