#!/usr/bin/env python3
"""S11 line verification: topic-only order -> rendered film -> measured evidence.

Runs the same Studio ``run_slate`` path the public API uses, with only a topic
in the slots.  Writes one MP4 + contact sheet per (line, topic) and a JSON
matrix with ffprobe facts (aspect, duration, audio) plus the zero-line QA.

Usage:
    python scripts/s11_verify.py --line explainer --topic 敦煌壁画 --out DIR
    python scripts/s11_verify.py --matrix matrix.json --out DIR
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

os.environ.setdefault("HEVI_LINE_ENGINE", "zero")
os.environ.setdefault("HEVI_LAUNCH_STRICT", "0")


def probe(path: Path) -> dict:
    raw = subprocess.check_output(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration:stream=codec_type,width,height,codec_name",
            "-of", "json", str(path),
        ],
        text=True,
    )
    info = json.loads(raw)
    video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), {})
    return {
        "duration": round(float(info["format"]["duration"]), 3),
        "width": video.get("width"),
        "height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
    }


def contact(path: Path, out: Path, seconds: float = 30.0, n: int = 6) -> Path:
    stamps = [seconds * i / (n - 1) for i in range(n)]
    frames = out.parent / f".{out.stem}_frames"
    frames.mkdir(parents=True, exist_ok=True)
    inputs: list[str] = []
    for i, t in enumerate(stamps):
        p = frames / f"f{i}.jpg"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{min(t, seconds - 0.2):.3f}",
             "-i", str(path), "-frames:v", "1", "-q:v", "2", str(p)],
            check=False,
        )
        inputs += ["-i", str(p)]
    cmd = ["ffmpeg", "-y", "-v", "error"]
    cmd += inputs
    cmd += ["-filter_complex", f"hstack=inputs={n}", str(out)]
    subprocess.run(cmd, check=False)
    return out


async def one(line_id: str, topic: str, out_root: Path) -> dict:
    from hevi.studio.slate import Slate, run_slate

    out_dir = out_root / f"{line_id}_{topic}"
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    result = await run_slate(
        Slate(line_id=line_id, slots={"topic": topic, "output_dir": str(out_dir)}, execute=True)
    )
    elapsed = round(time.time() - started, 1)
    row: dict = {
        "line": line_id,
        "topic": topic,
        "status": result.status,
        "reason": result.reason,
        "elapsed_s": elapsed,
        "video": "",
        "probe": {},
        "contact": "",
        "quality": result.data.get("quality") or {},
        "zero_qa": ((result.data.get("quality") or {}).get("checks") or {}).get("zero_line_qa") or [],
    }
    video = str(result.data.get("result_video_path") or "")
    if video and Path(video).is_file():
        row["video"] = video
        row["probe"] = probe(Path(video))
        sheet = contact(Path(video), out_dir / "contact.jpg", row["probe"]["duration"])
        row["contact"] = str(sheet)
    return row


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--line", action="append", default=[])
    ap.add_argument("--topic", action="append", default=[])
    ap.add_argument("--matrix", help="JSON [[line, topic], ...]")
    ap.add_argument("--out", default="/data/soffy/projects/seq-1108/verify_s11/local")
    args = ap.parse_args()
    pairs: list[tuple[str, str]] = []
    if args.matrix:
        for line, topic in json.loads(Path(args.matrix).read_text(encoding="utf-8")):
            pairs.append((line, topic))
    else:
        pairs = [(line, topic) for line in args.line for topic in args.topic]
    if not pairs:
        raise SystemExit("no (line, topic) pairs")
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    rows = []
    for line, topic in pairs:
        try:
            row = await one(line, topic, out_root)
        except Exception as exc:  # evidence must survive failures
            row = {"line": line, "topic": topic, "status": "exception",
                   "reason": f"{type(exc).__name__}: {exc}", "video": "", "probe": {},
                   "contact": "", "quality": {}, "zero_qa": []}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))
        (out_root / "s11_matrix.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    asyncio.run(main())
