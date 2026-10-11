"""Whiteboard video production pipeline (omodul layer)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.whiteboard.oprim_impl.contracts import (
    WhiteboardGate,
    WhiteboardRecord,
)
from hevi.layer4_legacy.whiteboard.oskill_impl.compiler import (
    compile_storyboard_to_dsl,
    parse_storyboard,
)
from hevi.layer4_legacy.whiteboard.omodul_impl.tts_asr import tts_and_align

FFMPEG = "/home/soffy/.local/bin/ffmpeg"
FFPROBE = "/home/soffy/.local/bin/ffprobe"
REPO_ROOT = Path(__file__).resolve().parents[4]
RUNTIME_ROOT = REPO_ROOT / "hevi-remotion-whiteboard"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def probe_video(path: Path) -> dict[str, Any]:
    cmd = [
        FFPROBE,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    raw = subprocess.check_output(cmd)
    data = json.loads(raw)
    duration_s = float(data.get("format", {}).get("duration", 0.0))
    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    return {
        "duration_s": duration_s,
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "video_codec": video_stream.get("codec_name", ""),
        "audio_codec": audio_stream.get("codec_name", ""),
        "sample_rate": int(audio_stream.get("sample_rate", 0)),
    }


def make_contact_sheet(
    *,
    video_path: Path,
    out_image: Path,
    total_s: float,
    orientation: str = "landscape",
) -> Path:
    cols, rows = 3, 2
    n = cols * rows
    rate = max(0.05, n / max(total_s, 1.0))
    if orientation == "portrait":
        scale_filter = "scale=270:480"
    else:
        scale_filter = "scale=480:270"

    vf = f"fps={rate:.4f},{scale_filter},tile={cols}x{rows}:padding=6:color=white"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-v", "error",
            "-i", str(video_path),
            "-vf", vf,
            "-frames:v", "1",
            str(out_image),
        ],
        check=True,
    )
    return out_image


def produce_whiteboard(
    storyboard_data: dict[str, Any],
    output_dir: Path,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute complete whiteboard production transaction for both landscape and portrait."""
    config = config or {}
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    t_start = time.monotonic()

    topic = str(storyboard_data.get("topic") or "白板讲解")
    parsed_segments = parse_storyboard(storyboard_data)
    if not parsed_segments:
        raise ValueError("Storyboard has no narration segments")

    # Brand configuration
    brand_input = storyboard_data.get("brand") or config.get("brand")
    if brand_input and isinstance(brand_input, dict) and brand_input.get("name"):
        brand_cfg = {
            "name": str(brand_input["name"]).strip(),
            "slogan": str(brand_input.get("slogan") or "").strip(),
            "accent": "#2f9e44",
            "ink": "#1e1e1e",
            "watermark": {
                "enabled": True,
                "position": "top-right",
                "opacity": 0.72,
                "size": 36,
                "margin": 56,
                "drawInSeconds": 1.2,
                "sparkle": True,
                "underline": True,
            },
            "endCard": {
                "enabled": True,
                "seconds": 5.5,
                "cta": str(brand_input.get("cta") or "点赞 · 关注 · 评论区聊聊"),
                "holdSeconds": 1.5,
            },
        }
    elif isinstance(brand_input, str) and brand_input.strip():
        brand_cfg = {
            "name": brand_input.strip(),
            "slogan": "",
            "accent": "#2f9e44",
            "ink": "#1e1e1e",
            "watermark": {"enabled": True, "position": "top-right"},
            "endCard": {"enabled": True, "seconds": 5.5},
        }
    else:
        # No brand provided: completely disable watermark and end card
        brand_cfg = {
            "name": "",
            "slogan": "",
            "watermark": {"enabled": False},
            "endCard": {"enabled": False},
        }

    # Working directories
    landscape_dir = output_dir / "landscape"
    portrait_dir = output_dir / "portrait"
    landscape_dir.mkdir(parents=True, exist_ok=True)
    portrait_dir.mkdir(parents=True, exist_ok=True)

    # Base configuration template
    base_config_obj = {
        "dirs": {"projects": "./episodes", "build": "./build"},
        "tts": {"speed": 1.2},
        "bgm": {"file": "", "gain": 0.3},
        "render": {
            "fps": 30,
            "leadSeconds": 0.3,
            "holdSeconds": 0.7,
            "workers": 4,
            "pen": {
                "speed": 1200,
                "fillSpeed": 9000,
                "minSeconds": 0.35,
                "gapSeconds": 0.12,
                "charSeconds": [0.06, 0.2],
                "overflow": 0.35,
                "travelMax": 1.6,
                "fillMaxSeconds": 1.2,
            },
        },
        "captions": {
            "enabled": True,
            "fontSize": 46,
            "baselineY": 1022,
            "safeTop": 960,
            "minChars": 6,
            "maxChars": 20,
            "leadSeconds": 0.08,
            "tailSeconds": 0.25,
        },
        "brand": brand_cfg,
    }

    landscape_cfg_path = landscape_dir / "config.json"
    portrait_cfg_path = portrait_dir / "config.json"
    landscape_cfg_path.write_text(json.dumps(base_config_obj, ensure_ascii=False, indent=2), encoding="utf-8")
    portrait_cfg_path.write_text(json.dumps(base_config_obj, ensure_ascii=False, indent=2), encoding="utf-8")

    # Generate scenes.js for Landscape and Portrait
    runtime_root_str = str(RUNTIME_ROOT)
    landscape_js = compile_storyboard_to_dsl(storyboard_data, orientation="landscape", runtime_root=runtime_root_str)
    portrait_js = compile_storyboard_to_dsl(storyboard_data, orientation="portrait", runtime_root=runtime_root_str)

    (landscape_dir / "scenes.js").write_text(landscape_js, encoding="utf-8")
    (portrait_dir / "scenes.js").write_text(portrait_js, encoding="utf-8")

    # Build scene Excalidraw documents
    subprocess.run(["node", "scenes.js"], cwd=landscape_dir, check=True)
    subprocess.run(["node", "scenes.js"], cwd=portrait_dir, check=True)

    # Audio synthesis and alignment: done once and shared
    audio_dir = landscape_dir / "work" / "audio"
    tts_and_align(project_dir=landscape_dir, audio_dir=audio_dir, speed=1.2)

    # Share audio with portrait project
    portrait_audio_dir = portrait_dir / "work" / "audio"
    portrait_audio_dir.parent.mkdir(parents=True, exist_ok=True)
    if portrait_audio_dir.exists():
        shutil.rmtree(portrait_audio_dir)
    shutil.copytree(audio_dir, portrait_audio_dir)

    # Render Landscape (1920x1080)
    env_ls = os.environ.copy()
    env_ls["PATH"] = f"/home/soffy/.local/bin:{env_ls.get('PATH', '')}"
    env_ls["WB_CONFIG_PATH"] = str(landscape_cfg_path)
    subprocess.run(["node", f"{runtime_root_str}/render.js", str(landscape_dir)], check=True, env=env_ls)
    subprocess.run(["node", f"{runtime_root_str}/mix-bgm.mjs", str(landscape_dir)], check=True, env=env_ls)

    ls_master = landscape_dir / "work" / "out" / "master.mp4"
    ls_final = landscape_dir / "outputs" / "final.mp4"
    ls_source = ls_final if ls_final.exists() else ls_master
    if not ls_source.exists():
        raise RuntimeError(f"Landscape video failed to produce: {ls_source}")

    landscape_dest = output_dir / "whiteboard_landscape.mp4"
    shutil.copy2(ls_source, landscape_dest)

    # Render Portrait (1080x1920)
    env_pt = os.environ.copy()
    env_pt["PATH"] = f"/home/soffy/.local/bin:{env_pt.get('PATH', '')}"
    env_pt["WB_CONFIG_PATH"] = str(portrait_cfg_path)
    subprocess.run(["node", f"{runtime_root_str}/render.js", str(portrait_dir), "--portrait"], check=True, env=env_pt)
    subprocess.run(["node", f"{runtime_root_str}/mix-bgm.mjs", str(portrait_dir)], check=True, env=env_pt)

    pt_master = portrait_dir / "work" / "out" / "master.mp4"
    pt_final = portrait_dir / "outputs" / "final.mp4"
    pt_source = pt_final if pt_final.exists() else pt_master
    if not pt_source.exists():
        raise RuntimeError(f"Portrait video failed to produce: {pt_source}")

    portrait_dest = output_dir / "whiteboard_portrait.mp4"
    shutil.copy2(pt_source, portrait_dest)

    # Measure and quality gates
    ls_probe = probe_video(landscape_dest)
    pt_probe = probe_video(portrait_dest)

    ls_sha = sha256_file(landscape_dest)
    pt_sha = sha256_file(portrait_dest)

    # Generate Contact Sheets
    ls_sheet = output_dir / "contact_sheet_landscape.jpg"
    pt_sheet = output_dir / "contact_sheet_portrait.jpg"
    make_contact_sheet(
        video_path=landscape_dest,
        out_image=ls_sheet,
        total_s=ls_probe["duration_s"],
        orientation="landscape",
    )
    make_contact_sheet(
        video_path=portrait_dest,
        out_image=pt_sheet,
        total_s=pt_probe["duration_s"],
        orientation="portrait",
    )

    ls_gates = [
        WhiteboardGate("resolution", ls_probe["width"] == 1920 and ls_probe["height"] == 1080, f"{ls_probe['width']}x{ls_probe['height']}", "1920x1080"),
        WhiteboardGate("duration", ls_probe["duration_s"] >= 15.0, ls_probe["duration_s"], ">=15.0s"),
        WhiteboardGate("audio", ls_probe["audio_codec"] == "aac" and ls_probe["sample_rate"] == 48000, f"{ls_probe['audio_codec']}@{ls_probe['sample_rate']}Hz", "aac@48000Hz"),
    ]

    pt_gates = [
        WhiteboardGate("resolution", pt_probe["width"] == 1080 and pt_probe["height"] == 1920, f"{pt_probe['width']}x{pt_probe['height']}", "1080x1920"),
        WhiteboardGate("duration", pt_probe["duration_s"] >= 15.0, pt_probe["duration_s"], ">=15.0s"),
        WhiteboardGate("audio", pt_probe["audio_codec"] == "aac" and pt_probe["sample_rate"] == 48000, f"{pt_probe['audio_codec']}@{pt_probe['sample_rate']}Hz", "aac@48000Hz"),
    ]

    records = [
        {
            "video_path": str(landscape_dest),
            "orientation": "landscape",
            "width": ls_probe["width"],
            "height": ls_probe["height"],
            "duration_s": ls_probe["duration_s"],
            "sha256": ls_sha,
            "contact_sheet": str(ls_sheet),
            "passed": all(g.passed for g in ls_gates),
            "gates": [
                {"name": g.name, "passed": g.passed, "value": g.value, "threshold": g.threshold}
                for g in ls_gates
            ],
        },
        {
            "video_path": str(portrait_dest),
            "orientation": "portrait",
            "width": pt_probe["width"],
            "height": pt_probe["height"],
            "duration_s": pt_probe["duration_s"],
            "sha256": pt_sha,
            "contact_sheet": str(pt_sheet),
            "passed": all(g.passed for g in pt_gates),
            "gates": [
                {"name": g.name, "passed": g.passed, "value": g.value, "threshold": g.threshold}
                for g in pt_gates
            ],
        },
    ]

    all_passed = all(r["passed"] for r in records)

    return {
        "status": "succeeded" if all_passed else "failed",
        "line": "whiteboard",
        "wall_seconds": time.monotonic() - t_start,
        "landscape_path": str(landscape_dest),
        "portrait_path": str(portrait_dest),
        "records": records,
    }
