"""Deterministic download policy compiler."""

from __future__ import annotations

from hevi.video_catcher.oprim.contracts import QUALITY_LIMITS, VideoCatchRequest, is_url


def format_selector(request: VideoCatchRequest) -> str:
    limit = QUALITY_LIMITS[request.quality]
    if limit is None:
        return "bestvideo+bestaudio/best" if request.merge_audio else "best"
    base = f"bestvideo[height<={limit}]+bestaudio/best[height<={limit}]"
    return f"{base}/best[height<={limit}]/best"


def select_source_mode(request: VideoCatchRequest) -> str:
    if not is_url(request.source):
        return "local_passthrough"
    lowered = request.source.lower()
    if any(ext in lowered for ext in (".m3u8", ".mpd")):
        return "manifest"
    return "yt_dlp"


__all__ = ["format_selector", "select_source_mode"]
