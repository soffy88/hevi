"""hevi-story CLI —— 手绘日记漫画 skill 入口(plan/preview/full)。

用法:
    uv run python -m hevi.skills.story_cli --text "故事文本" --mode plan [--transition cut]
    uv run python -m hevi.skills.story_cli \
      --images a.jpg b.jpg --mode preview --transition page-flip
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from hevi.assembly.story_to_animation_workflow import (
    STORY_MODES,
    STORY_TRANSITIONS,
    StoryConfig,
    StoryInput,
    story_to_animation_workflow,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="hevi-story: 故事 → 手绘动画计划")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", default="", help="中文故事文本")
    src.add_argument("--images", nargs="*", type=Path, default=[], help="有序图片路径")
    parser.add_argument("--mode", choices=STORY_MODES, default="plan")
    parser.add_argument("--transition", choices=STORY_TRANSITIONS, default="cut")
    parser.add_argument("--title", default="")
    parser.add_argument("--out-dir", type=Path, default=Path(".hevi_story"))
    args = parser.parse_args(argv)

    config = StoryConfig(
        out_path=Path("out.mp4"),
        mode=args.mode,
        transition=args.transition,
        title=args.title,
    )
    input_data = StoryInput(text=args.text, images=args.images)

    import asyncio

    res = asyncio.run(story_to_animation_workflow(config, input_data, args.out_dir))
    print(f"story: {res['status']}")
    if res.get("plan"):
        beats = res["plan"]["beats"]
        print(f"  beats: {len(beats)}  transition: {res['plan']['transition']}")
        for b in beats[:6]:
            preview = b["text"][:24] if b["text"] else f"<page {b['page_index']}>"
            print(f"    #{b['index']} [{b['mode']}] {preview}")
    if res.get("render_note"):
        print(f"  render: {res['render_note'][:80]}")
    return 0 if res["status"] == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
