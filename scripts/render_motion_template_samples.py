#!/usr/bin/env python
"""Render the full AMTPL-R2 sample matrix and emit an evidence report.

Matrix (16 clips):
  * 4 templates x 2 specs x 9:16
  * each template x 1 spec x 16:9
  * each template x 1 spec x 1:1

For every clip the script records ffprobe stream facts, the MP4 SHA256, the
contact-sheet SHA256 and the audio mean volume (when an audio track exists).
Output report: artifacts/motion_templates_r2/render_report.json
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from hevi.motion_templates.render import ASPECT_PRESETS, compute_file_sha256, render

REPO_ROOT = Path(__file__).resolve().parents[1]
SPECS_DIR = REPO_ROOT / "hevi" / "motion_templates" / "specs"
SAMPLES_DIR = REPO_ROOT / "samples" / "aimotion"
REPORT_DIR = REPO_ROOT / "artifacts" / "motion_templates_r2"

TEMPLATES = {
    "morph_ui": ["morph_ui_hevi_pipeline.json", "morph_ui_studio_ops.json"],
    "timeline_explainer": ["timeline_ai_video_evolution.json", "timeline_hevi_milestones.json"],
    "kinetic_lyrics": ["kinetic_bpm_beat_drop.json", "kinetic_engine_tempo.json"],
    "layer_build": ["layer_build_pipeline.json", "layer_build_datarun.json"],
}


def ffprobe(mp4_path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "stream=codec_type,codec_name,width,height,r_frame_rate,pix_fmt,duration",
        "-show_entries", "format=duration,size",
        "-of", "json", str(mp4_path),
    ]
    out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    return json.loads(out.stdout)


def audio_mean_volume(mp4_path: Path) -> float | None:
    res = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(mp4_path), "-af", "volumedetect", "-f", "null", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    for line in res.stderr.splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].strip().split()[0])
    return None


def render_one(template: str, spec_file: str, aspect: str) -> dict:
    w, h = ASPECT_PRESETS[aspect]
    spec_path = SPECS_DIR / spec_file
    out_mp4 = SAMPLES_DIR / f"{spec_path.stem}_{aspect.replace(':', '_')}.mp4"
    print(f"[AMTPL-R2] {template} {spec_file} {aspect} -> {out_mp4.name}", flush=True)
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
    info = ffprobe(out_mp4)
    vstream = next(s for s in info["streams"] if s["codec_type"] == "video")
    astream = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
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
        "audio_codec": astream["codec_name"] if astream else None,
        "audio_mean_volume_db": audio_mean_volume(out_mp4) if astream else None,
    }
    return rec


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    records = []

    for template, specs in TEMPLATES.items():
        for spec_file in specs:
            records.append(render_one(template, spec_file, "9:16"))
        records.append(render_one(template, specs[0], "16:9"))
        records.append(render_one(template, specs[0], "1:1"))

    report = {"count": len(records), "clips": records}
    out = REPORT_DIR / "render_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[AMTPL-R2] wrote {out} ({len(records)} clips)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
