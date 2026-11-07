"""CLI for collage_broll."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .metaphor import generate_metaphors
from .spec import build_visual_spec
from .render import procedural_render
from .qa import run_qa


def _sentences_from_args(args) -> list[str]:
    if args.sentences_file:
        p = Path(args.sentences_file)
        lines = [l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
        return lines
    if args.sentence:
        return [args.sentence]
    # default 3 example sentences
    return [
        "一只橘猫第一次看海",
        "它把爪子伸进沙里",
        "风把它的耳朵吹起来",
    ]


def cmd_run(args) -> int:
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    sentences = _sentences_from_args(args)
    metaphors = generate_metaphors(sentences)
    mode = args.mode
    if mode in ("procedural", "codex"):
        mode = "broll"
    narration = (mode == "narration") or bool(args.narration)
    if args.duration is not None:
        duration = float(args.duration)
    else:
        duration = 30.0 if narration else 5.0
    results = []
    for i, (sent, meta) in enumerate(zip(sentences, metaphors)):
        item_dir = out_root / f"{i+1:02d}-{_slug(sent)}"
        item_dir.mkdir(parents=True, exist_ok=True)
        build_visual_spec(meta, item_dir / "visual-spec.json")
        meta_path = item_dir / "metaphor.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        t0 = time.time()
        res = procedural_render(meta, item_dir, "clip", duration=duration, narration=narration, narration_text=sent)
        dt = time.time() - t0
        gif_path = Path(res.get("gif", item_dir / "clip.gif"))
        qa = run_qa(gif_path, Path(res["mp4"]))
        results.append({"sentence": sent, "dir": str(item_dir), "render": res, "qa": qa, "elapsed_s": round(dt, 3)})
        print(json.dumps({"sentence": sent, "mp4": res["mp4"], "gif": res.get("gif"), "qa_passed": qa["passed"], "elapsed_s": round(dt, 3), "duration": duration, "narration": narration}, ensure_ascii=False))

    summary = {"sentences": len(sentences), "results": results, "duration": duration, "narration": narration}
    (out_root / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def _slug(s: str) -> str:
    import re

    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", s).strip("_")
    return s[:40] or "item"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="hevi.collage_broll")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--out", default="samples")
    r.add_argument("--sentence", default=None)
    r.add_argument("--sentences-file", default=None)
    r.add_argument("--mode", default="narration", choices=["broll", "narration", "procedural", "codex"])
    r.add_argument("--duration", type=float, default=None)
    r.add_argument("--narration", action="store_true", default=False)
    r.set_defaults(func=cmd_run)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
