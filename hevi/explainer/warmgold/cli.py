"""命令行入口（本地渲染、拆解、自检、模板）。

python -m hevi.explainer.warmgold.cli parts
python -m hevi.explainer.warmgold.cli check script.json
python -m hevi.explainer.warmgold.cli render script.json --out out.mp4 --music bgm.mp3
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hevi.explainer.warmgold")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_parts = sub.add_parser("parts", help="写出零件清单 parts.json")
    p_parts.add_argument("--out", default="")

    p_card = sub.add_parser("style-card", help="写出风格卡 JSON")
    p_card.add_argument("--out", default="")

    p_check = sub.add_parser("check", help="逐拍脚本自检")
    p_check.add_argument("script")
    p_check.add_argument("--beats", default="")
    p_check.add_argument("--music", default="")

    p_render = sub.add_parser("render", help="渲染成片")
    p_render.add_argument("script")
    p_render.add_argument("--out", required=True)
    p_render.add_argument("--work", required=True)
    p_render.add_argument("--music", default="")
    p_render.add_argument("--no-voice", action="store_true")
    p_render.add_argument("--fps", type=int, default=24)

    p_ref = sub.add_parser("reference", help="拆对标")
    p_ref.add_argument("payload")
    p_ref.add_argument("--work", required=True)

    p_t10 = sub.add_parser("template10", help="生成 10 秒模板脚本")
    p_t10.add_argument("sentence")
    p_t10.add_argument("--part", default="random_walk")
    p_t10.add_argument("--out", required=True)

    p_beats = sub.add_parser("beats", help="音乐 → beats.json")
    p_beats.add_argument("music")
    p_beats.add_argument("--out", required=True)

    args = parser.parse_args(argv)

    if args.cmd == "parts":
        from hevi.explainer.warmgold import parts

        target = parts.write_parts(Path(args.out) if args.out else None)
        print(json.dumps({"written": str(target), "count": len(parts.PARTS)}, ensure_ascii=False))
        return 0

    if args.cmd == "style-card":
        from hevi.explainer.warmgold import style

        target = style.write_style_card(Path(args.out) if args.out else None)
        print(json.dumps({"written": str(target)}, ensure_ascii=False))
        return 0

    if args.cmd == "check":
        from hevi.explainer.warmgold import beats, scriptcheck

        script = _load(args.script)
        music = args.music or (script.get("music") or {}).get("path") or ""
        beat_data = (
            _load(args.beats) if args.beats else beats.build_beats(script, music_path=music or None)
        )
        result = scriptcheck.check_script(script, beat_data, music_present=bool(music))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["pass"] else 1

    if args.cmd == "render":
        from hevi.explainer.warmgold import render

        script = _load(args.script)
        report = render.render(
            script,
            args.out,
            workdir=args.work,
            music_path=args.music or None,
            voice=not args.no_voice,
            fps=args.fps,
        )
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0 if report.ok else 1

    if args.cmd == "reference":
        from hevi.explainer.warmgold import reference

        payload = reference.decompose(_load(args.payload), args.work)
        json_path, html_path = reference.write_report(payload, args.work)
        print(
            json.dumps(
                {"json": str(json_path), "html": str(html_path), "warnings": payload["warnings"]},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.cmd == "template10":
        from hevi.explainer.warmgold import template

        script = template.build_10s(args.sentence, part_id=args.part)
        Path(args.out).write_text(
            json.dumps(script, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps({"written": args.out}, ensure_ascii=False))
        return 0

    if args.cmd == "beats":
        from hevi.explainer.warmgold import beats

        data = beats.analyze_music(args.music)
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "bpm": data["bpm"],
                    "first_beat_s": data["first_beat_s"],
                    "beats": len(data["beats"]),
                },
                ensure_ascii=False,
            )
        )
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
