"""解说一键入口 —— MoneyPrinterTurbo 式:主题 → 脚本 → 时间线(可选装配)。"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="hevi explainer: 主题出脚本/时间线")
    parser.add_argument("topic")
    parser.add_argument("--source-text", default="", help="史料原文,借用通鉴讲解拆 cue")
    parser.add_argument("--out-dir", type=Path, default=Path("output/explainer_cli"))
    args = parser.parse_args(argv)

    async def _run() -> dict:
        from hevi.studio.kit import explainer_cues_from_text, nle_recut
        from hevi.studio.tools import invoke_tool

        script = await invoke_tool("script.quick", {"topic": args.topic})
        cues = await explainer_cues_from_text(
            {"texts": [row.get("text") for row in script.payload.get("script_lines") or []]}
        )
        if args.source_text:
            from hevi.studio.mix import plan_history_mix

            mix = await plan_history_mix(
                {
                    "lines": [
                        {
                            "type": "narration",
                            "speaker": "NARRATOR",
                            "text": args.source_text[:2000],
                        }
                    ]
                }
            )
            cues["cues"] = [*(mix.commentary_cues or []), *(cues.get("cues") or [])]
        plan = await invoke_tool(
            "nle.edit_plan",
            {"script_lines": [{"text": c.get("text")} for c in cues.get("cues") or []]},
        )
        args.out_dir.mkdir(parents=True, exist_ok=True)
        dest = args.out_dir / "plan.json"
        dest.write_text(
            json.dumps(
                {
                    "topic": args.topic,
                    "cues": cues.get("cues"),
                    "edit_plan": plan.payload.get("edit_plan"),
                    "recut": nle_recut(
                        {"clips": [], "output_path": str(args.out_dir / "recut.mp4")}
                    ),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return {"plan_path": str(dest), "cues": len(cues.get("cues") or [])}

    result = asyncio.run(_run())
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
