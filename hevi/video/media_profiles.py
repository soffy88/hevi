"""多平台 Media Profile —— 每种平台预设含分辨率、编码、最大时长、字幕格式。

对标 OpenMontage 的 lib/media_profiles.py(7 种平台预设),Hevi 此前只有单一输出格式。
用法:`get_media_profile("youtube_landscape")` → `MediaProfile`,再 `ffmpeg_output_args(profile)`
生成 ffmpeg 输出参数。装配时按需选 profile,不硬编码分辨率。

新增 profile 只需在 `_PROFILES` 加一条,不改调用方。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MediaProfile:
    name: str
    width: int
    height: int
    aspect: str
    max_duration_s: int | None
    codec: str = "libx264"
    audio_codec: str = "aac"
    audio_bitrate: str = "128k"
    crf: int = 23
    pixel_format: str = "yuv420p"
    fps: int = 30
    max_file_size_mb: int | None = None
    caption_format: str = "srt"
    notes: str = ""


_PROFILES: dict[str, MediaProfile] = {
    "youtube_landscape": MediaProfile(
        name="youtube_landscape",
        width=1920, height=1080, aspect="16:9",
        max_duration_s=43200,  # 12h
        max_file_size_mb=256000,  # 256GB
        fps=30, crf=23,
        notes="标准 YouTube 横屏",
    ),
    "youtube_4k": MediaProfile(
        name="youtube_4k",
        width=3840, height=2160, aspect="16:9",
        max_duration_s=43200,
        max_file_size_mb=256000,
        fps=30, crf=20,
        notes="4K YouTube,低 CRF 保细节",
    ),
    "youtube_shorts": MediaProfile(
        name="youtube_shorts",
        width=1080, height=1920, aspect="9:16",
        max_duration_s=60,
        max_file_size_mb=256000,
        fps=30, crf=23,
        notes="YouTube Shorts 竖屏,60s 硬上限",
    ),
    "instagram_reels": MediaProfile(
        name="instagram_reels",
        width=1080, height=1920, aspect="9:16",
        max_duration_s=90,
        max_file_size_mb=4096,
        fps=30, crf=23,
        notes="Instagram Reels 竖屏,90s 上限",
    ),
    "instagram_feed": MediaProfile(
        name="instagram_feed",
        width=1080, height=1080, aspect="1:1",
        max_duration_s=60,
        max_file_size_mb=4096,
        fps=30, crf=23,
        notes="Instagram 信息流方形",
    ),
    "tiktok": MediaProfile(
        name="tiktok",
        width=1080, height=1920, aspect="9:16",
        max_duration_s=600,  # 10min
        max_file_size_mb=4096,
        fps=30, crf=23,
        notes="TikTok 竖屏",
    ),
    "linkedin": MediaProfile(
        name="linkedin",
        width=1920, height=1080, aspect="16:9",
        max_duration_s=600,
        max_file_size_mb=5120,
        fps=30, crf=23,
        notes="LinkedIn 横屏",
    ),
    "cinematic": MediaProfile(
        name="cinematic",
        width=2560, height=1080, aspect="21:9",
        max_duration_s=None,
        fps=24, crf=18,
        notes="超宽银幕 21:9,24fps 电影感",
    ),
    "bilibili": MediaProfile(
        name="bilibili",
        width=1920, height=1080, aspect="16:9",
        max_duration_s=None,
        max_file_size_mb=8192,
        fps=30, crf=21,
        notes="B 站横屏,低 CRF 保画质",
    ),
    "douyin": MediaProfile(
        name="douyin",
        width=1080, height=1920, aspect="9:16",
        max_duration_s=900,  # 15min
        max_file_size_mb=4096,
        fps=30, crf=23,
        notes="抖音竖屏",
    ),
    "wechat_channels": MediaProfile(
        name="wechat_channels",
        width=1080, height=1920, aspect="9:16",
        max_duration_s=1800,  # 30min
        max_file_size_mb=2048,
        fps=30, crf=23,
        notes="微信视频号竖屏",
    ),
    "x_twitter": MediaProfile(
        name="x_twitter",
        width=1920, height=1080, aspect="16:9",
        max_duration_s=140,
        max_file_size_mb=512,
        fps=30, crf=23,
        notes="X/Twitter 横屏,140s + 512MB 限制",
    ),
    "hevi_default": MediaProfile(
        name="hevi_default",
        width=720, height=1280, aspect="9:16",
        max_duration_s=None,
        fps=24, crf=20,
        notes="Hevi 内部默认(通鉴竖屏),24fps",
    ),
}


def get_media_profile(name: str) -> MediaProfile:
    """按名称获取 MediaProfile。未知名称返回 hevi_default。"""
    return _PROFILES.get(name, _PROFILES["hevi_default"])


def list_profiles() -> list[MediaProfile]:
    """列出所有可用 profile。"""
    return list(_PROFILES.values())


def ffmpeg_output_args(profile: MediaProfile) -> list[str]:
    """将 MediaProfile 转换为 ffmpeg 输出参数列表。

    用法:
        args = ffmpeg_output_args(get_media_profile("youtube_landscape"))
        subprocess.run(["ffmpeg", ...] + args + [output_path])
    """
    return [
        "-vf", (
            f"scale={profile.width}:{profile.height}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={profile.width}:{profile.height},"
            f"fps={profile.fps},format={profile.pixel_format}"
        ),
        "-c:v", profile.codec,
        "-preset", "medium",
        "-crf", str(profile.crf),
        "-r", str(profile.fps),
        "-vsync", "cfr",
        "-c:a", profile.audio_codec,
        "-ar", "44100",
        "-ac", "2",
        "-b:a", profile.audio_bitrate,
        "-movflags", "+faststart",
    ]


def ffmpeg_for_profile(profile: MediaProfile, *, src: str, dst: str) -> list[str]:
    """生成完整的 ffmpeg 命令:src → dst,按 profile 参数编码。"""
    return [
        "ffmpeg", "-y", "-v", "error",
        "-i", src,
        *ffmpeg_output_args(profile),
        dst,
    ]
