#!/usr/bin/env python
"""Render the required AMTPL-R3 sample set and record evidence.

Target clips per AMTPL_FIX.md:
  * timeline 2 specs x 9:16 / 16:9 / 1:1 (6 clips)
  * morph_ui 2 specs x 9:16 / 16:9 (4 clips)
  * layer_build 2 specs x 9:16 / 16:9 (4 clips)
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from hevi.motion_templates.render import ASPECT_PRESETS, render

REPO_ROOT = Path(__file__).resolve().parents[1]
SPECS_DIR = REPO_ROOT / "hevi" / "motion_templates" / "specs"
SAMPLES_DIR = REPO_ROOT / "samples" / "aimotion"
REPORT_DIR = REPO_ROOT / "artifacts" / "motion_templates_r3"

R3_JOBS = [
    # timeline (2 specs x 3 aspects = 6 clips)
    ("timeline_explainer", "timeline_ai_video_evolution.json", "9:16"),
    ("timeline_explainer", "timeline_ai_video_evolution.json", "16:9"),
    ("timeline_explainer", "timeline_ai_video_evolution.json", "1:1"),
    ("timeline_explainer", "timeline_hevi_milestones.json", "9:16"),
    ("timeline_explainer", "timeline_hevi_milestones.json", "16:9"),
    ("timeline_explainer", "timeline_hevi_milestones.json", "1:1"),

    # morph_ui (2 specs x 9:16 and 16:9 = 4 clips)
    ("morph_ui", "morph_ui_hevi_pipeline.json", "9:16"),
    ("morph_ui", "morph_ui_hevi_pipeline.json", "16:9"),
    ("morph_ui", "morph_ui_studio_ops.json", "9:16"),
    ("morph_ui", "morph_ui_studio_ops.json", "16:9"),

    # layer_build (2 specs x 9:16 and 16:9 = 4 clips)
    ("layer_build", "layer_build_pipeline.json", "9:16"),
    ("layer_build", "layer_build_pipeline.json", "16:9"),
    ("layer_build", "layer_build_datarun.json", "9:16"),
    ("layer_build", "layer_build_datarun.json", "16:9"),
]


def ffprobe(mp4_path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt,duration",
        "-show_entries", "format=duration,size",
        "-of", "json", str(mp4_path),
    ]
    out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    return json.loads(out.stdout)


def render_job(template: str, spec_file: str, aspect: str) -> dict:
    w, h = ASPECT_PRESETS[aspect]
    spec_path = SPECS_DIR / spec_file
    out_mp4 = SAMPLES_DIR / f"{spec_path.stem}_{aspect.replace(':', '_')}.mp4"
    t0 = time.time()
    print(f"[{time.strftime('%X')}] [AMTPL-R3] Rendering {template} | {spec_file} | {aspect} -> {out_mp4.name}...", flush=True)

    result = render(
        template=template,
        spec=spec_path,
        out_mp4=out_mp4,
        aspect=aspect,
        w=w,
        h=h,
        fps=30,
        contact_sheet=True,
    )
    dt = time.time() - t0
    info = ffprobe(out_mp4)
    vstream = next(s for s in info["streams"] if s["codec_type"] == "video")
    rec = {
        "template": template,
        "spec": spec_file,
        "aspect": aspect,
        "mp4": str(out_mp4.relative_to(REPO_ROOT)),
        "width": int(vstream["width"]),
        "height": int(vstream["height"]),
        "fps": vstream["r_frame_rate"],
        "pix_fmt": vstream.get("pix_fmt"),
        "vcodec": vstream["codec_name"],
        "duration": float(info["format"]["duration"]),
        "size_bytes": out_mp4.stat().st_size,
        "mp4_sha256": result.sha256,
        "contact_sheet": str(result.contact_sheet_path.relative_to(REPO_ROOT)) if result.contact_sheet_path else None,
        "contact_sha256": result.contact_sha256,
        "render_time_s": round(dt, 2),
    }
    print(f"[{time.strftime('%X')}] Finished in {dt:.1f}s | mp4_sha={result.sha256[:12]}... | contact_sha={result.contact_sha256[:12]}...", flush=True)
    return rec


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    records = []

    for template, spec_file, aspect in R3_JOBS:
        rec = render_job(template, spec_file, aspect)
        records.append(rec)

    report = {"count": len(records), "clips": records}
    out = REPORT_DIR / "render_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[AMTPL-R3] Successfully wrote {out} ({len(records)} clips)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
