#!/usr/bin/env python3
"""Render a 9:16 1080x1920 stickman sample video (CPU-only, PIL).

Implements a 5-segment heartbeat short script (~20s = 2 clips),
drawing a black line stickman on a pure-white canvas with
WenQuanYi Zen Hei CJK subtitles inside the interface-safe band.

Output:
  - output/dirstyle_e2e/stickman_9x16.mp4  (video)
  - output/dirstyle_e2e/stickman_frame*.png (extract evidence)
  - output/dirstyle_e2e/record.json        (updated)
  - output/dirstyle_e2e/SHA256SUMS         (updated)
  - output/dirstyle_e2e/contact_sheet.png  (updated, one row added)
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path("/data/soffy/projects/hevi-dirstyle")
OUT_DIR = ROOT / "output" / "dirstyle_e2e"
VIDEO_PATH = OUT_DIR / "stickman_9x16.mp4"
FRAME_DIR = OUT_DIR

W, H = 1080, 1920
FPS = 30
DURATION_S = 20.0  # 2 clips x 10s

# WenQuanYi Zen Hei (CJK font — no tofu boxes)
CJK_FONT = "/home/soffy/.local/share/fonts/wqy-zenhei.ttc"
FONT_PATH = CJK_FONT

# Interface-safe margins (9:16).  Safe band = central 90% width,
# upper/lower 5% reserved for overlay text.
SAFE_LEFT = int(W * 0.05)
SAFE_RIGHT = int(W * 0.95)
SAFE_TOP = int(H * 0.05)
SAFE_BOTTOM = int(H * 0.95)

# Stickman geometry (black line art, uniform stroke)
STROKE = 8
HEAD_RADIUS = 70
TORSO_LEN = 240
LIMB_LEN = 180

# The 5-segment heartbeat short script (2 clips ~ 20s).
# Stage 1 (hook) + Stage 5 (elevation) — one heartbeat row each.
CLIP_NARRATION = [
    "猫为什么总爱把桌上的东西推下去？",
    "背后有三个原因：脚垫敏感、高处刺激、主人反应。",
]

# Stickman poses per clip (relative joint offsets).
POSES = [
    # Clip 0: hook — stickman reaching up to push a cup off a table
    {
        "head_dy": 0,
        "torso_dy": 0,
        "left_arm": (-120, -60),
        "right_arm": (120, -140),  # raised, pushing
        "left_leg": (-90, 200),
        "right_leg": (90, 200),
    },
    # Clip 1: elevation — stickman standing, arms wide, presenting
    {
        "head_dy": -20,
        "torso_dy": -20,
        "left_arm": (-160, -40),
        "right_arm": (160, -40),
        "left_leg": (-100, 200),
        "right_leg": (100, 200),
    },
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size)


def draw_stickman(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    pose: dict,
) -> None:
    """Draw a classic black line stickman with 5 connected body lines.

    Head is a hollow circle outline (empty interior).  Torso is a
    single line.  Two arms and two legs, all connected.  Uniform
    stroke thickness on every line.  No hands, feet, face marks.
    """
    # Head (hollow circle)
    head_cy = cy + pose["head_dy"]
    draw.ellipse(
        [cx - HEAD_RADIUS, head_cy - HEAD_RADIUS,
         cx + HEAD_RADIUS, head_cy + HEAD_RADIUS],
        outline="black",
        width=STROKE,
    )
    # Torso top (just below head)
    torso_top = head_cy + HEAD_RADIUS + 4
    torso_bottom = torso_top + TORSO_LEN + pose["torso_dy"]
    draw.line(
        [cx, torso_top, cx, torso_bottom],
        fill="black",
        width=STROKE,
    )
    # Arms (joined to upper torso)
    arm_top = torso_top + 40
    for side in ("left_arm", "right_arm"):
        dx, dy = pose[side]
        draw.line(
            [cx, arm_top, cx + dx, arm_top + dy],
            fill="black",
            width=STROKE,
        )
    # Legs (joined to bottom torso)
    for side in ("left_leg", "right_leg"):
        dx, dy = pose[side]
        draw.line(
            [cx, torso_bottom, cx + dx, torso_bottom + dy],
            fill="black",
            width=STROKE,
        )


def draw_subtitle(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
) -> None:
    """Draw subtitle text inside the interface-safe lower band."""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    # Place in lower safe band, centered horizontally
    x = (W - tw) // 2
    y = SAFE_BOTTOM - th - int(H * 0.06)
    # Safety clamp: never leave the safe band
    x = max(SAFE_LEFT, min(x, SAFE_RIGHT - tw))
    draw.text((x, y), text, font=font, fill="black")


def render_frame(
    clip_index: int,
    frame_in_clip: int,
) -> Image.Image:
    """Render one frame: white canvas + stickman + subtitle."""
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)
    # Stickman centered, upper-middle of frame
    cx = W // 2
    cy = int(H * 0.38)
    pose = POSES[clip_index % len(POSES)]
    draw_stickman(draw, cx, cy, pose)
    # Subtitle in safe band
    narration = CLIP_NARRATION[clip_index % len(CLIP_NARRATION)]
    font = load_font(56)
    draw_subtitle(draw, narration, font)
    return img


def render_video() -> Path:
    """Render all frames and encode to mp4 via ffmpeg."""
    total_frames = int(DURATION_S * FPS)
    frames_dir = FRAME_DIR / "stickman_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    print(f"Rendering {total_frames} frames...")
    for f in range(total_frames):
        clip_index = int(f // (FPS * 10))
        frame_in_clip = f % (FPS * 10)
        img = render_frame(clip_index, frame_in_clip)
        img.save(frames_dir / f"frame_{f:05d}.png")
        if f % 60 == 0:
            print(f"  frame {f}/{total_frames}")

    # Encode with ffmpeg
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-c:v", "libx264",
        "-crf", "18",
        "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(VIDEO_PATH),
    ]
    print("Encoding:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)
    print(f"Video written: {VIDEO_PATH}")
    return VIDEO_PATH


def probe_video(path: Path) -> dict:
    """Probe video metadata with ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", "-show_streams",
        str(path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_contact_sheet() -> Path:
    """Rebuild contact_sheet.png with the stickman row added."""
    sheet_path = OUT_DIR / "contact_sheet.png"
    # Load existing sheet if present
    existing = Image.open(sheet_path) if sheet_path.exists() else None
    # Build a new sheet with all styles + stickman
    styles = [
        ("wong_kar_wai", "output/dirstyle_e2e/wong_kar_wai_frame0.png"),
        ("wes_anderson", "output/dirstyle_e2e/wes_anderson_frame0.png"),
        ("fincher", "output/dirstyle_e2e/fincher_frame0.png"),
        ("zhang_yimou", "output/dirstyle_e2e/zhang_yimou_frame0.png"),
        ("stickman_9x16", str(VIDEO_PATH)),
    ]
    # Render each style's representative frame
    thumb_w, thumb_h = 270, 480
    cols = len(styles)
    rows = 1
    sheet = Image.new("RGB", (thumb_w * cols, thumb_h * rows + 40), "white")
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(sheet)
    font = load_font(24)
    for i, (label, path) in enumerate(styles):
        if path.endswith(".mp4"):
            # Extract a frame from the video
            frame_path = OUT_DIR / "stickman_frame0.png"
            if not frame_path.exists():
                subprocess.run([
                    "ffmpeg", "-y", "-i", str(path),
                    "-frames:v", "1", str(frame_path),
                ], check=True, capture_output=True, cwd=ROOT)
            img = Image.open(frame_path)
        else:
            img = Image.open(ROOT / path)
        img = img.resize((thumb_w, thumb_h))
        sheet.paste(img, (i * thumb_w, 0))
        draw.text((i * thumb_w + 8, thumb_h + 4), label, font=font, fill="black")
    sheet.save(sheet_path)
    print(f"Contact sheet written: {sheet_path}")
    return sheet_path


def update_record_and_sums(video_path: Path) -> None:
    """Update record.json and SHA256SUMS with the stickman entry."""
    record_path = OUT_DIR / "record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    probe = probe_video(video_path)
    duration = float(probe["format"]["duration"])
    width = int(probe["streams"][0]["width"])
    height = int(probe["streams"][0]["height"])
    codec = probe["streams"][0]["codec_name"]
    digest = sha256_file(video_path)
    entry = {
        "style_id": "stickman_9x16",
        "display_zh": "火柴人 9:16 样片",
        "display_en": "Stickman 9:16 Sample",
        "input_path": str(video_path),
        "output_path": str(video_path.relative_to(ROOT)),
        "ffmpeg_cmd": [],
        "filter_chain": "PIL-rendered stickman frames -> ffmpeg libx264",
        "duration_s": duration,
        "width": width,
        "height": height,
        "fps": f"{FPS}/1",
        "codec": codec,
        "prompt_zh": "白底黑线火柴人，5段心跳结构（黄金钩子+升华互动），竖屏纵深构图，CJK字幕在安全区内",
        "prompt_en": "black line stickman on white, heartbeat5 structure, vertical recompose, CJK subtitles in safe band",
        "negative": [
            "gray tint", "paper texture", "gradients", "shadows",
            "lighting", "bloom", "fog", "3D depth", "filled head",
            "facial marks", "body silhouette", "outlined limbs",
            "detached joints", "separate hand or foot shapes",
            "changed proportions", "broken line weight", "photorealism",
            "3D humanoid rendering", "detailed pupils or realistic eyes",
            "extra limbs", "malformed anatomy",
        ],
        "sha256": digest,
        "source": "PIL CPU render",
    }
    record["styles"].append(entry)
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Record updated: {record_path}")

    # SHA256SUMS
    sums_path = OUT_DIR / "SHA256SUMS"
    lines = []
    if sums_path.exists():
        lines = sums_path.read_text(encoding="utf-8").splitlines()
    # Remove any prior stickman entry
    lines = [l for l in lines if "stickman_9x16.mp4" not in l]
    lines.append(f"{digest}  stickman_9x16.mp4")
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"SHA256SUMS updated: {sums_path}")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    video_path = render_video()
    build_contact_sheet()
    update_record_and_sums(video_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
