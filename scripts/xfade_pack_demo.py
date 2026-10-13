#!/usr/bin/env python3
"""T2 xfade pack E2E 样片生成脚本。

生成 output/xfadepack_e2e/ 下：
  - xfadepack_e2e.mp4  : 5镜头 × 4种转场（含custom）, d=0.6s
  - xfadepack_hardcut.mp4 : 同素材硬切基线
  - contact_sheet.png     : 每个注册转场一格中点帧
  - record.json           : 命令、filter_complex、ffprobe、sha256
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "xfadepack_e2e"
OUTPUT.mkdir(parents=True, exist_ok=True)

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")

from hevi.assembly.assembler import build_xfade_chain
from hevi.assembly.xfade_transitions import ALL_TRANSITIONS, resolve


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, **kw)


def _probe(path: Path) -> dict:
    out = _run([FFPROBE, "-v", "error", "-show_format", "-show_streams",
                "-of", "json", str(path)]).stdout
    return json.loads(out)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    RECORD: dict = {}

    # ── 1. 生成 5 个不同颜色/图案的 lavfi 镜头（每段 3s，1080x1920，30fps）──
    SHOT_DUR = 3.0
    WIDTH, HEIGHT = 1080, 1920
    FPS = 30
    XFADE_D = 0.6

    shot_configs = [
        f"testsrc=duration={SHOT_DUR}:size={WIDTH}x{HEIGHT}:rate={FPS}",
        f"color=c=red:s={WIDTH}x{HEIGHT}:d={SHOT_DUR}:rate={FPS}",
        f"color=c=green:s={WIDTH}x{HEIGHT}:d={SHOT_DUR}:rate={FPS}",
        f"color=c=blue:s={WIDTH}x{HEIGHT}:d={SHOT_DUR}:rate={FPS}",
        f"testsrc=duration={SHOT_DUR}:size={WIDTH}x{HEIGHT}:rate={FPS}",
    ]
    clips = []
    for i, src in enumerate(shot_configs):
        c = OUTPUT / f"shot{i}.mp4"
        _run([FFMPEG, "-y", "-f", "lavfi", "-i", src,
              "-pix_fmt", "yuv420p", str(c)])
        clips.append(c)

    # ── 2. 逐接缝转场成片（fade, dissolve, whip, zoom_punch）─────────────
    transitions = ["fade", "dissolve", "whip", "zoom_punch"]
    fc, label, total = build_xfade_chain(
        [SHOT_DUR] * 5, transitions, XFADE_D
    )
    RECORD["xfadepack_e2e"] = {
        "transitions": transitions,
        "xfade_d": XFADE_D,
        "filter_complex": fc,
        "expected_total": total,
    }

    e2e_out = OUTPUT / "xfadepack_e2e.mp4"
    inputs = []
    for c in clips:
        inputs.extend(["-i", str(c)])
    _run([FFMPEG, "-y", *inputs, "-filter_complex", fc, "-map", label,
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
          "-pix_fmt", "yuv420p", str(e2e_out)])

    e2e_probe = _probe(e2e_out)
    RECORD["xfadepack_e2e"]["ffprobe"] = {
        "duration": float(e2e_probe["format"]["duration"]),
        "size_bytes": e2e_out.stat().st_size,
        "sha256": _sha256(e2e_out),
    }
    print(f"✓ xfadepack_e2e.mp4  duration={RECORD['xfadepack_e2e']['ffprobe']['duration']:.3f}s  "
          f"size={RECORD['xfadepack_e2e']['ffprobe']['size_bytes']}B  "
          f"sha256={RECORD['xfadepack_e2e']['ffprobe']['sha256'][:16]}...")

    # ── 3. 硬切基线 ────────────────────────────────────────────────────
    concat_list = OUTPUT / "concat.txt"
    concat_list.write_text("".join(f"file '{p.resolve()}'\n" for p in clips))
    hardcut_out = OUTPUT / "xfadepack_hardcut.mp4"
    _run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
          "-pix_fmt", "yuv420p", str(hardcut_out)])

    hc_probe = _probe(hardcut_out)
    RECORD["hardcut_baseline"] = {
        "ffprobe": {
            "duration": float(hc_probe["format"]["duration"]),
            "size_bytes": hardcut_out.stat().st_size,
            "sha256": _sha256(hardcut_out),
        }
    }
    print(f"✓ xfadepack_hardcut.mp4  duration={RECORD['hardcut_baseline']['ffprobe']['duration']:.3f}s  "
          f"sha256={RECORD['hardcut_baseline']['ffprobe']['sha256'][:16]}...")

    # ── 4. Contact sheet：每个注册转场一格中点帧（320x240，快速预览）─────
    CELL_W, CELL_H = 320, 240
    SHORT_D = 1.0
    SHORT_XFADE = 0.5
    MID = SHORT_D - SHORT_XFADE / 2  # 0.75s
    COLS = 8
    ROWS = (len(ALL_TRANSITIONS) + COLS - 1) // COLS

    # 生成两个短素材
    a_short = OUTPUT / "_a_short.mp4"
    b_short = OUTPUT / "_b_short.mp4"
    _run([FFMPEG, "-y", "-f", "lavfi",
          "-i", f"testsrc=duration={SHORT_D}:size={CELL_W}x{CELL_H}:rate={FPS}",
          "-pix_fmt", "yuv420p", str(a_short)])
    _run([FFMPEG, "-y", "-f", "lavfi",
          "-i", f"color=c=red:s={CELL_W}x{CELL_H}:d={SHORT_D}:rate={FPS}",
          "-pix_fmt", "yuv420p", str(b_short)])

    from PIL import Image
    canvas = Image.new("RGB", (CELL_W * COLS, CELL_H * ROWS))
    labels: list[str] = []

    for idx, trans in enumerate(ALL_TRANSITIONS):
        row, col = divmod(idx, COLS)
        fc_t, lbl_t, _ = build_xfade_chain([SHORT_D, SHORT_D], [trans.id], SHORT_XFADE)
        tmp = OUTPUT / f"_tmp_{idx}.mp4"
        _run([FFMPEG, "-y", "-i", str(a_short), "-i", str(b_short),
              "-filter_complex", fc_t, "-map", lbl_t,
              "-c:v", "libx264", "-pix_fmt", "yuv420p", str(tmp)])
        res = subprocess.run(
            [FFMPEG, "-y", "-ss", str(MID), "-i", str(tmp),
             "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True,
        )
        frame = Image.frombytes("RGB", (CELL_W, CELL_H), res.stdout)
        canvas.paste(frame, (col * CELL_W, row * CELL_H))
        labels.append(trans.id)

    sheet_path = OUTPUT / "contact_sheet.png"
    canvas.save(sheet_path)
    RECORD["contact_sheet"] = {
        "path": str(sheet_path),
        "cells": len(ALL_TRANSITIONS),
        "labels": labels,
        "size_bytes": sheet_path.stat().st_size,
    }
    print(f"✓ contact_sheet.png  {len(ALL_TRANSITIONS)} cells  "
          f"{sheet_path.stat().st_size}B")

    # 清理临时文件
    for p in [a_short, b_short] + [OUTPUT / f"_tmp_{i}.mp4" for i in range(len(ALL_TRANSITIONS))]:
        p.unlink(missing_ok=True)

    # ── 5. 写 record.json ─────────────────────────────────────────────
    record_path = OUTPUT / "record.json"
    record_path.write_text(json.dumps(RECORD, indent=2, ensure_ascii=False))
    print(f"✓ record.json written")
    print(f"\n产物目录: {OUTPUT}")
    for f in sorted(OUTPUT.iterdir()):
        print(f"  {f.name}  ({f.stat().st_size}B)")


if __name__ == "__main__":
    main()
