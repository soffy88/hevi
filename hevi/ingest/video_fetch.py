"""视频抓取 —— yt-dlp 封装(3O 内化 Phase A)。

来源: bradautomates/claude-video 的下载层。yt-dlp 支持数百个平台
(YouTube/Loom/TikTok/X/Instagram/…),以及本地路径直通。

本环境 yt-dlp 为可选依赖:未安装时 URL 抓取给出明确错误,本地文件直通不受影响。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class FetchError(Exception):
    """视频抓取失败(缺依赖/下载失败/超时)。"""


def _ytdlp_available() -> bool:
    return shutil.which("yt-dlp") is not None


def is_url(value: str) -> bool:
    """粗判是否为 URL(而非本地路径)。"""
    return value.startswith(("http://", "https://", "ftp://"))


def fetch_video(
    source: str | Path,
    dest_dir: Path,
    *,
    max_bytes: int = 256 * 1024 * 1024,
    timeout_s: int = 600,
) -> Path:
    """把 URL 或本地路径落到 dest_dir,返回媒体文件路径。

    - 本地路径:不下载,直接返回(调用方负责存在性检查)。
    - URL:调用 yt-dlp 子进程下载;未安装 yt-dlp 抛 FetchError。

    Args:
        source: URL 或本地路径。
        dest_dir: 下载落地目录(不存在则创建)。
        max_bytes: 下载大小上限(避免一次抓取吃掉整个磁盘)。
        timeout_s: 子进程总超时。

    Returns:
        下载/直通后的媒体文件路径。
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    src = str(source)

    if not is_url(src):
        p = Path(source)
        if not p.exists():
            raise FetchError(f"local file not found: {p}")
        return p

    if not _ytdlp_available():
        raise FetchError(
            "yt-dlp 未安装: URL 抓取需要它。安装: pip install yt-dlp "
            "(或 apt install yt-dlp)。本地文件路径不受影响。"
        )

    try:
        proc = subprocess.run(
            [
                "yt-dlp",
                "--no-playlist",
                "--format",
                "best[filesize<={max_bytes}]/best",
                "-o",
                str(dest_dir / "%(title).120s.%(ext)s"),
                "--max-filesize",
                str(max_bytes),
                src,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise FetchError(f"yt-dlp timed out after {timeout_s}s: {src}") from e
    except OSError as e:
        raise FetchError(f"failed to run yt-dlp: {e}") from e

    if proc.returncode != 0:
        raise FetchError(f"yt-dlp failed ({proc.returncode}): {proc.stderr[-800:]}")

    candidates = sorted(
        (p for p in dest_dir.iterdir() if p.is_file() and p.stat().st_size > 0),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FetchError(f"yt-dlp finished but produced no file in {dest_dir}")
    return candidates[0]
