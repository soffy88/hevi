"""hevi-interactive CLI —— 交互动画 skill 执行入口(预算/决策/清单)。

用法:
    uv run python -m hevi.skills.interactive_cli budget --display 240x240 --dpr 2 --frames 180
    uv run python -m hevi.skills.interactive_cli decide \
    --transparency --frames 200 --display 240x240 --control scroll
    uv run python -m hevi.skills.interactive_cli manifest \
    --frames 180 --cols 15 --rows 12 --cell 480 --mapping scroll
"""

from __future__ import annotations

import argparse
import json
import sys

from hevi.motion.interactive import (
    atlas_budget,
    build_atlas_manifest,
    decide_resource_form,
    interactive_frame_budget,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="hevi-interactive: 交互动画预算/决策/清单")
    sub = parser.add_subparsers(dest="verb", required=True)

    b = sub.add_parser("budget", help="图集预算(单元/纹理/内存)")
    b.add_argument("--display", required=True, help="显示尺寸 WxH")
    b.add_argument("--dpr", type=float, required=True)
    b.add_argument("--frames", type=int, required=True)

    d = sub.add_parser("decide", help="资源形式决策")
    d.add_argument("--transparency", action="store_true")
    d.add_argument("--frames", type=int, required=True)
    d.add_argument("--display", required=True)
    d.add_argument("--control", required=True, choices=["scroll", "drag", "ring", "state"])

    f = sub.add_parser("frames", help="按控制方式估算帧数")
    f.add_argument("--control", required=True, choices=["scroll", "drag", "ring", "state"])
    f.add_argument("--scroll-pages", type=float, default=1.0)

    m = sub.add_parser("manifest", help="图集清单")
    m.add_argument("--frames", type=int, required=True)
    m.add_argument("--cols", type=int, required=True)
    m.add_argument("--rows", type=int, required=True)
    m.add_argument("--cell", type=int, required=True)
    m.add_argument("--mapping", default="scroll", choices=["scroll", "ring", "drag", "state"])

    args = parser.parse_args(argv)

    if args.verb == "budget":
        w, h = (int(v) for v in args.display.split("x"))
        res = atlas_budget(display_size=(w, h), dpr=args.dpr, frames=args.frames)
        print(json.dumps(res.__dict__, ensure_ascii=False, indent=2))
        return 0 if res.within_texture_limit else 1
    if args.verb == "decide":
        w, h = (int(v) for v in args.display.split("x"))
        form = decide_resource_form(
            transparency=args.transparency,
            frames=args.frames,
            display_size=(w, h),
            control_kind=args.control,
        )
        print(form)
        return 0
    if args.verb == "frames":
        print(interactive_frame_budget(args.control, scroll_pages=args.scroll_pages))
        return 0
    if args.verb == "manifest":
        manifest = build_atlas_manifest(
            frames=args.frames, cols=args.cols, rows=args.rows,
            cell_width=args.cell, cell_height=args.cell, mapping=args.mapping,
        )
        print(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
