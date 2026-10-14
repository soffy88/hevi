"""Video compositing engine for RISO B-roll overlays on spoken master video.

Composites RISO animation clips onto a master vertical video (1080x1920)
aligned with spoken speech audio and subtitles.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hevi.riso.constants import CANVAS_HEIGHT, CANVAS_WIDTH, FPS
from hevi.riso.render import check_disk_space, probe_video


def composite_master_video(
    audio_path: Path | str,
    overlay_clips: list[dict[str, Any]],
    out_mp4_path: Path | str,
    subtitles_srt: Path | str | None = None,
    bg_color: str = "#18181B",
    width: int = CANVAS_WIDTH,
    height: int = CANVAS_HEIGHT,
    fps: int = FPS,
) -> Path:
    """Composite spoken audio, RISO B-roll overlays, and subtitles into a final video.

    overlay_clips is a list of dicts with:
      - 'mp4_path': Path | str
      - 'start_s': float
      - 'end_s': float
    """
    check_disk_space()
    audio_file = Path(audio_path).resolve()
    out_file = Path(out_mp4_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # 1. Get audio duration
    probe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(audio_file),
    ]
    res = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
    audio_dur = float(json.loads(res.stdout)["format"]["duration"])

    # 2. Build ffmpeg filter_complex
    # Input 0: audio
    # Input 1: color background (virtual)
    # Input 2..N+1: overlay mp4 files
    inputs = ["-i", str(audio_file)]

    # Background source
    bg_input = f"color=c={bg_color}:s={width}x{height}:r={fps}:d={audio_dur}"
    inputs.extend(["-f", "lavfi", "-i", bg_input])

    filter_chains = []
    curr_v = "1:v"

    # Add overlay inputs
    for i, clip in enumerate(overlay_clips):
        clip_path = Path(clip["mp4_path"]).resolve()
        inputs.extend(["-i", str(clip_path)])
        inp_idx = i + 2
        start_t = clip["start_s"]
        end_t = clip["end_s"]
        next_v = f"v_ov_{i+1}"
        # Setpts to align overlay timeline with presentation time
        filter_chains.append(
            f"[{curr_v}][{inp_idx}:v]overlay=0:0:enable='between(t,{start_t:.3f},{end_t:.3f})':eof_action=pass[{next_v}]"
        )
        curr_v = next_v

    # Subtitles burning
    if subtitles_srt and Path(subtitles_srt).exists():
        srt_resolved = Path(subtitles_srt).resolve()
        # Escape path for ffmpeg subtitles filter
        srt_filter_path = str(srt_resolved).replace(":", "\\:").replace("'", "\\'")
        sub_style = (
            "FontName=Source Han Sans SC,FontSize=28,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H0018181A,BorderStyle=3,Outline=2,MarginV=140"
        )
        final_v = "v_sub"
        filter_chains.append(
            f"[{curr_v}]subtitles='{srt_filter_path}':force_style='{sub_style}'[{final_v}]"
        )
        curr_v = final_v

    filter_complex_str = ";".join(filter_chains)

    cmd = ["ffmpeg", "-y"]
    cmd.extend(inputs)
    cmd.extend([
        "-filter_complex",
        filter_complex_str,
        "-map",
        f"[{curr_v}]",
        "-map",
        "0:a",
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        str(out_file),
    ])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Master video composition failed: {proc.stderr}")

    # Validate with ffprobe
    probe = probe_video(out_file)
    streams = probe.get("streams", [])
    if len(streams) < 2:
        raise RuntimeError(f"Composited video missing video or audio stream: {out_file}")

    return out_file
