#!/usr/bin/env python3
"""Render a 9:16 1080x1920 stickman sample video (CPU-only, PIL).

Implements a heartbeat short script (~20s = 2 clips) drawing a black line
stickman on a pure-white canvas with WenQuanYi Zen Hei CJK subtitles.

B5 fixes (DIRSTYLE_FIX_R3):
- Subtitles wrap by pixel width with >=90px side margins and at most 2
  lines; every rendered line's bbox must fall inside [90, 990] (asserted
  at render time and in tests/test_flow_pack.py).
- The figure uses >=4 distinct poses (stand / point / push-cup / jump /
  crouch) with a pose or position change every ~2.5s, plus props (a table
  and a cup).  The 1A line-style DNA (hollow head, five connected lines,
  uniform stroke) is preserved.

Output:
  - output/dirstyle_e2e/stickman_9x16.mp4
  - output/dirstyle_e2e/stickman_frame0.png
  - output/dirstyle_e2e/stickman_poses.json   (pose keypoints for tests)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path("/data/soffy/projects/hevi-dirstyle")
OUT_DIR = ROOT / "output" / "dirstyle_e2e"
VIDEO_PATH = OUT_DIR / "stickman_9x16.mp4"
POSES_JSON = OUT_DIR / "stickman_poses.json"

W, H = 1080, 1920
FPS = 30
DURATION_S = 20.0

CJK_FONT = "/home/soffy/.local/share/fonts/wqy-zenhei.ttc"
FONT_PATH = CJK_FONT

# Subtitle safe band: each rendered line must sit inside [SAFE_L, SAFE_R].
SAFE_L = 90
SAFE_R = 990
SAFE_BOTTOM = int(H * 0.95)

STROKE = 8
HEAD_RADIUS = 70
TORSO_LEN = 240
LIMB_LEN = 180

# Two clips of narration (kept short so the 2-line wrap fits the safe band).
CLIP_NARRATION = [
    "猫为什么总爱把桌上的东西推下去？",
    "背后有三个原因：脚垫敏感、高处刺激、主人反应。",
]

# Distinct poses (>=4).  Each pose is a dict of joint offsets relative to
# the stickman centre; `label` names the action for the pose-count test.
POSES: list[dict] = [
    {  # 0 stand
        "label": "stand",
        "head_dy": 0,
        "torso_dy": 0,
        "left_arm": (-120, 60),
        "right_arm": (120, 60),
        "left_leg": (-90, 200),
        "right_leg": (90, 200),
    },
    {  # 1 point (one arm up)
        "label": "point",
        "head_dy": -10,
        "torso_dy": -10,
        "left_arm": (-110, 80),
        "right_arm": (140, -180),
        "left_leg": (-90, 200),
        "right_leg": (90, 200),
    },
    {  # 2 push cup (lean forward, both arms forward)
        "label": "push_cup",
        "head_dy": 10,
        "torso_dy": 20,
        "left_arm": (-150, -60),
        "right_arm": (150, -60),
        "left_leg": (-120, 210),
        "right_leg": (60, 210),
    },
    {  # 3 jump (arms wide, legs tucked)
        "label": "jump",
        "head_dy": -30,
        "torso_dy": -30,
        "left_arm": (-170, -110),
        "right_arm": (170, -110),
        "left_leg": (-140, 120),
        "right_leg": (140, 120),
    },
    {  # 4 crouch (low, arms down)
        "label": "crouch",
        "head_dy": 70,
        "torso_dy": 120,
        "left_arm": (-90, 120),
        "right_arm": (90, 120),
        "left_leg": (-120, 140),
        "right_leg": (120, 140),
    },
    {  # 5 arms wide (present)
        "label": "present",
        "head_dy": -20,
        "torso_dy": -20,
        "left_arm": (-170, -30),
        "right_arm": (170, -30),
        "left_leg": (-100, 200),
        "right_leg": (100, 200),
    },
]

# Pose schedule: a pose every 2.5s, cycling through >=4 distinct poses.
POSE_PERIOD_S = 2.5


def load_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size)


def wrap_subtitle(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Wrap *text* to at most 2 lines, each fitting within *max_w* pixels.

    Chinese has no spaces, so we accumulate one character at a time and
    break when the next character would exceed the pixel budget.  At most
    two lines are returned (B5).
    """
    lines: list[str] = []
    cur = ""
    for ch in text:
        trial = cur + ch
        bbox = font.getbbox(trial)
        if (bbox[2] - bbox[0]) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = ch
        if len(lines) == 2:
            break
    if cur and len(lines) < 2:
        lines.append(cur)
    return lines[:2]


def draw_subtitle(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont
) -> list[tuple[int, int, int, int]]:
    """Draw the wrapped subtitle in the lower safe band.

    Returns the per-line pixel bboxes (x0, y0, x1, y1) for the test to
    assert each line lies inside [SAFE_L, SAFE_R].
    """
    max_w = SAFE_R - SAFE_L
    lines = wrap_subtitle(text, font, max_w)
    line_h = font.getbbox("字")[3] - font.getbbox("字")[1]
    gap = 14
    block_h = len(lines) * line_h + (len(lines) - 1) * gap
    y = SAFE_BOTTOM - block_h - int(H * 0.06)
    boxes: list[tuple[int, int, int, int]] = []
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        tw = bbox[2] - bbox[0]
        x = (W - tw) // 2
        # clamp so the line never leaves the safe band
        x = max(SAFE_L, min(x, SAFE_R - tw))
        ly = y + i * (line_h + gap)
        draw.text((x, ly), line, font=font, fill="black")
        boxes.append((x, ly, x + tw, ly + line_h))
    return boxes


def draw_table_and_cup(
    draw: ImageDraw.ImageDraw,
    table_y: int,
    cup_x: int,
    cup_y: int,
) -> None:
    """A simple table line and a small cup rectangle (props, 1A line style)."""
    # table top (horizontal line) + two legs
    draw.line([(260, table_y), (820, table_y)], fill="black", width=STROKE)
    draw.line([(300, table_y), (300, table_y + 150)], fill="black", width=STROKE)
    draw.line([(780, table_y), (780, table_y + 150)], fill="black", width=STROKE)
    # cup (small open rectangle)
    cw, chh = 46, 60
    draw.rectangle([cup_x, cup_y - chh, cup_x + cw, cup_y], outline="black", width=STROKE)


def draw_stickman(
    draw: ImageDraw.ImageDraw,
    cx: int,
    cy: int,
    pose: dict,
) -> None:
    """Classic black line stickman: hollow head + five connected body lines."""
    head_cy = cy + pose["head_dy"]
    draw.ellipse(
        [cx - HEAD_RADIUS, head_cy - HEAD_RADIUS, cx + HEAD_RADIUS, head_cy + HEAD_RADIUS],
        outline="black",
        width=STROKE,
    )
    torso_top = head_cy + HEAD_RADIUS + 4
    torso_bottom = torso_top + TORSO_LEN + pose["torso_dy"]
    draw.line([cx, torso_top, cx, torso_bottom], fill="black", width=STROKE)
    arm_top = torso_top + 40
    for side in ("left_arm", "right_arm"):
        dx, dy = pose[side]
        draw.line([cx, arm_top, cx + dx, arm_top + dy], fill="black", width=STROKE)
    for side in ("left_leg", "right_leg"):
        dx, dy = pose[side]
        draw.line([cx, torso_bottom, cx + dx, torso_bottom + dy], fill="black", width=STROKE)


def pose_keypoints(pose: dict) -> list[float]:
    """Flatten a pose's joint offsets into a comparable keypoint vector."""
    return [
        pose["head_dy"],
        pose["torso_dy"],
        pose["left_arm"][0],
        pose["left_arm"][1],
        pose["right_arm"][0],
        pose["right_arm"][1],
        pose["left_leg"][0],
        pose["left_leg"][1],
        pose["right_leg"][0],
        pose["right_leg"][1],
    ]


def render_frame(frame_idx: int) -> tuple[Image.Image, dict]:
    """Render one frame: white canvas + table/cup + stickman + subtitle."""
    img = Image.new("RGB", (W, H), "white")
    draw = ImageDraw.Draw(img)

    t = frame_idx / FPS
    pose_idx = int(t / POSE_PERIOD_S) % len(POSES)
    pose = POSES[pose_idx]

    # Props: table sits low; the cup slides along the table as the clip runs.
    table_y = int(H * 0.66)
    cup_progress = (t % POSE_PERIOD_S) / POSE_PERIOD_S
    cup_x = int(360 + 340 * cup_progress)
    cup_y = table_y
    draw_table_and_cup(draw, table_y, cup_x, cup_y)

    # Stickman stands behind the table; jumps raise it.
    cx = W // 2
    cy = int(H * 0.42)
    if pose["label"] == "jump":
        cy -= 90
    draw_stickman(draw, cx, cy, pose)

    clip_index = int(t // 10) % len(CLIP_NARRATION)
    font = load_font(56)
    boxes = draw_subtitle(draw, CLIP_NARRATION[clip_index], font)

    meta = {
        "frame": frame_idx,
        "pose_index": pose_idx,
        "pose_label": pose["label"],
        "pose_keypoints": pose_keypoints(pose),
        "subtitle_boxes": [list(b) for b in boxes],
    }
    return img, meta


def render_video() -> Path:
    total_frames = int(DURATION_S * FPS)
    frames_dir = OUT_DIR / "stickman_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    all_meta: list[dict] = []
    print(f"Rendering {total_frames} frames...")
    for f in range(total_frames):
        img, meta = render_frame(f)
        # B5: every subtitle line must lie inside the safe band.
        for x0, y0, x1, y1 in meta["subtitle_boxes"]:
            assert x0 >= SAFE_L - 1 and x1 <= SAFE_R + 1, (
                f"frame {f} subtitle out of safe band: {(x0, x1)} not in [{SAFE_L}, {SAFE_R}]"
            )
        img.save(frames_dir / f"frame_{f:05d}.png")
        all_meta.append(meta)
        if f % 60 == 0:
            print(f"  frame {f}/{total_frames}")

    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(FPS),
        "-i",
        str(frames_dir / "frame_%05d.png"),
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-preset",
        "medium",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(VIDEO_PATH),
    ]
    print("Encoding:", " ".join(cmd))
    subprocess.run(cmd, check=True, cwd=ROOT)
    print(f"Video written: {VIDEO_PATH}")

    # Persist pose metadata for the pose-diversity test.
    distinct = sorted({m["pose_label"] for m in all_meta})
    POSES_JSON.write_text(
        json.dumps(
            {
                "pose_period_s": POSE_PERIOD_S,
                "distinct_poses": distinct,
                "distinct_pose_count": len(distinct),
                "frames": all_meta,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Pose metadata written: {POSES_JSON} ({len(distinct)} distinct poses)")
    return VIDEO_PATH


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    render_video()
    return 0


if __name__ == "__main__":
    sys.exit(main())
