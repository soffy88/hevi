"""SVFACTORY Render Workflow.

Performs local CPU-only video assembly:
1. Generate narration TTS via local Piper (CPU, zero paid API).
2. Generate/obtain video segments (via auto-montage or explicit files).
3. Build FFmpeg filter complex (scale/pad to 9:16 or 16:9, CJK subtitle burn with bold/large preset).
4. Run kids_gate_workflow check.
5. Return manifest + gate report.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from oprim import probe_duration

from hevi.assembly.subtitle_burner import get_subtitle_filter
from hevi.audio.piper_tts_service import synth_with_piper
from hevi.quality.kids_gate import kids_gate_workflow
from hevi.svfactory.montage import auto_montage_segments


async def render_svfactory_episode(
    *,
    script_text: str,
    asset_dir: str | Path | None = None,
    video_files: list[str] | None = None,
    time_ranges: list[list[str]] | None = None,
    output_path: str | Path,
    aspect: str = "16:9",
    seed: int = 42,
    voice: str = "zh_CN-huayan-medium.onnx",
    subtitle_style: str = "large_white",
    bgm_path: str | Path | None = None,
) -> dict[str, Any]:
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    work_dir = out_p.parent / f"work_{out_p.stem}"
    work_dir.mkdir(parents=True, exist_ok=True)

    # 1. TTS Synthesis
    voice_audio = work_dir / "narration.wav"
    await synth_with_piper(script_text, voice_audio, voice=voice)
    audio_dur = float(probe_duration(voice_audio))
    min_dur_for_speech = len(script_text) / 3.0
    if audio_dur < min_dur_for_speech:
        padded_audio = work_dir / "narration_padded.wav"
        subprocess.run([
            "ffmpeg", "-y", "-i", str(voice_audio),
            "-af", f"apad=pad_dur={min_dur_for_speech - audio_dur}",
            str(padded_audio)
        ], check=True, capture_output=True)
        voice_audio = padded_audio
        audio_dur = min_dur_for_speech
    if audio_dur <= 0.1:
        audio_dur = max(3.0, len(script_text) * 0.4)

    # Generate SRT subtitle file
    srt_path = work_dir / "narration.srt"
    srt_content = f"1\n00:00:00,000 --> 00:00:{int(audio_dur):02d},000\n{script_text}\n\n"
    srt_path.write_text(srt_content, encoding="utf-8")

    # 2. Get video segments
    if not video_files or not time_ranges:
        if asset_dir and Path(asset_dir).exists():
            montage = auto_montage_segments(asset_dir, audio_dur, seed=seed, aspect=aspect)
            video_files = montage["video_files"]
            time_ranges = montage["time_ranges"]
        else:
            # Fallback: color source via lavfi
            color_src = work_dir / "color.mp4"
            w, h = (720, 1280) if aspect == "9:16" else (1280, 720)
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=navy:s={w}x{h}:r=30",
                "-t", f"{audio_dur:.2f}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(color_src)
            ], check=True, capture_output=True)
            video_files = [str(color_src)]
            time_ranges = [["0.000", f"{audio_dur:.3f}"]]

    # 3. FFmpeg assemble command
    w, h = (720, 1280) if aspect == "9:16" else (1280, 720)
    args = ["ffmpeg", "-y"]
    for vf in video_files:
        args.extend(["-i", vf])
    args.extend(["-i", str(voice_audio)])
    if bgm_path and Path(bgm_path).exists():
        args.extend(["-i", str(bgm_path)])

    filters = []
    video_streams = []
    for idx, (start, end) in enumerate(time_ranges):
        label = f"v{idx}"
        video_streams.append(label)
        filters.append(
            f"[{idx}:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,"
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps=30,format=yuv420p,setsar=1[{label}]"
        )

    filters.append(f"[{']['.join(video_streams)}]concat=n={len(video_files)}:v=1:a=0[vconcat]")

    # Burn subtitles using CJK font and style preset
    sub_filter = get_subtitle_filter(srt_path, style=subtitle_style)
    filters.append(f"[vconcat]{sub_filter}[vout]")

    # Audio normalization
    voice_idx = len(video_files)
    filters.append(f"[{voice_idx}:a]loudnorm=I=-16:TP=-1.5:LRA=11[voice_norm]")
    if bgm_path and Path(bgm_path).exists():
        bgm_idx = voice_idx + 1
        filters.append(f"[{bgm_idx}:a]volume=0.25,loudnorm=I=-25:TP=-1.5[bgm_norm]")
        filters.append("[voice_norm][bgm_norm]amix=inputs=2:duration=first:dropout_transition=0[final_audio]")
    else:
        filters.append("[voice_norm]acopy[final_audio]")

    args.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "[final_audio]",
        "-t", f"{audio_dur:.2f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        str(out_p)
    ])

    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg render failed: {proc.stderr[-800:]}")

    # 4. Run kids_gate quality check
    gate_report = kids_gate_workflow(out_p, srt_path=srt_path)

    manifest = {
        "output_path": str(out_p),
        "duration": audio_dur,
        "aspect": aspect,
        "seed": seed,
        "video_files": video_files,
        "time_ranges": time_ranges,
        "gate_passed": gate_report.get("passed", False),
        "gate_status": gate_report.get("status", "red"),
        "gate_report": gate_report,
    }

    manifest_path = out_p.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return manifest
