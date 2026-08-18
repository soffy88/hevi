"""Avatar PiP geometry + post-compose overlay.

Digital human is a silent 300×300 circle in the bottom-left, composited
onto an already-approved base video. Base audio is kept; avatar audio is
never used. Captions must sit above this reserved band.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from hevi.digital_human.avatar_render import probe_duration

AVATAR_PIP_SIZE = 300
AVATAR_PIP_MARGIN = 24
AVATAR_PIP_POSITION: Literal["bottom_left"] = "bottom_left"
SUBTITLE_GAP = 40

Position = Literal["bottom_left", "bottom_right"]
Shape = Literal["circle", "rect"]


@dataclass(frozen=True)
class AvatarPipLayout:
    size: int = AVATAR_PIP_SIZE
    margin: int = AVATAR_PIP_MARGIN
    position: Position = "bottom_left"
    shape: Shape = "circle"

    def overlay_xy(self, width: int, height: int) -> tuple[int, int]:
        y = max(0, height - self.size - self.margin)
        if self.position == "bottom_right":
            return (max(0, width - self.size - self.margin), y)
        return (self.margin, y)

    def subtitle_padding_bottom(self) -> int:
        """Captions sit above the reserved circle, not beside it."""
        return self.size + self.margin + SUBTITLE_GAP

    def overlaps_subtitle_band(
        self, frame_height: int, caption_bottom: int, caption_height: int
    ) -> bool:
        """True if a bottom-centered caption band intersects the circle."""
        circle_top = frame_height - self.size - self.margin
        caption_top = frame_height - caption_bottom - caption_height
        caption_bottom_y = frame_height - caption_bottom
        return caption_bottom_y > circle_top and caption_top < frame_height - self.margin


def overlay_filter(layout: AvatarPipLayout | None = None) -> str:
    """ffmpeg filter_complex: scale/crop avatar, optional circle alpha, overlay."""
    pip = layout or AvatarPipLayout()
    size = int(pip.size)
    margin = int(pip.margin)
    radius = size // 2
    x = f"W-w-{margin}" if pip.position == "bottom_right" else str(margin)
    y = f"H-h-{margin}"
    circle = (
        f",geq=lum='p(X,Y)':cb='p(X,Y)':cr='p(X,Y)':"
        f"a='if(lte(pow(X-{radius},2)+pow(Y-{radius},2),{radius * radius}),255,0)'"
        if pip.shape == "circle"
        else ""
    )
    return (
        f"[1:v]scale={size}:{size}:force_original_aspect_ratio=increase,"
        f"crop={size}:{size},format=yuva420p{circle}[pip];"
        f"[0:v][pip]overlay=x={x}:y={y}:eof_action=repeat[v]"
    )


def strip_audio(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-an", "-c:v", "copy", str(dest)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(f"剥离数字人音轨失败: {(proc.stderr or '')[-300:]}")
    return dest


def compose_avatar_overlay(
    base_video: Path,
    silent_avatar: Path,
    dest: Path,
    *,
    layout: AvatarPipLayout | None = None,
) -> Path:
    """Stack silent avatar onto base video. Output audio is the base track only."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    filt = overlay_filter(layout)
    proc = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(base_video),
            "-i",
            str(silent_avatar),
            "-filter_complex",
            filt,
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(dest),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(f"数字人叠片失败: {(proc.stderr or '')[-400:]}")
    return dest


def assert_lipsync_duration(video: Path, audio: Path, *, tolerance: float = 0.10) -> None:
    video_s = probe_duration(video)
    audio_s = probe_duration(audio)
    if audio_s <= 0:
        raise RuntimeError(f"配音母带时长无效: {audio}")
    lo = audio_s * (1.0 - tolerance)
    hi = audio_s * (1.0 + tolerance)
    if video_s < lo or video_s > hi:
        raise RuntimeError(
            f"口型视频 {video_s:.2f}s 与母带 {audio_s:.2f}s 不一致(±{int(tolerance * 100)}%)"
        )
