"""Discover/download/verify workflow with no synthetic media results."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hevi.video_catcher.oprim.contracts import VideoCatchRequest, VideoDiscovery, is_url
from hevi.video_catcher.oskill.compiler import format_selector, select_source_mode


class VideoCatcherError(RuntimeError):
    """A media source could not be discovered or downloaded."""


def _probe(path: Path) -> dict[str, Any]:
    if shutil.which("ffprobe") is None:
        return {"verified": path.is_file() and path.stat().st_size > 0, "probe": "size_only"}
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        return {"verified": False, "error": proc.stderr[-500:] or "ffprobe failed"}
    try:
        return {"verified": True, "probe": json.loads(proc.stdout)}
    except json.JSONDecodeError:
        return {"verified": False, "error": "ffprobe returned invalid JSON"}


def verify_media(path: str | Path) -> dict[str, Any]:
    candidate = Path(path).expanduser()
    if not candidate.is_file() or candidate.stat().st_size <= 0:
        return {"verified": False, "path": str(candidate), "error": "media file missing or empty"}
    return {"path": str(candidate), **_probe(candidate)}


def _discovery_from_probe(source: str, path: Path) -> VideoDiscovery:
    result = verify_media(path)
    raw_probe = result.get("probe")
    data: dict[str, Any] = raw_probe if isinstance(raw_probe, dict) else {}
    raw_streams = data.get("streams")
    if not isinstance(raw_streams, list):
        raw_streams = []
    streams: list[dict[str, Any]] = [item for item in raw_streams if isinstance(item, dict)]
    video: dict[str, Any] = next((s for s in streams if s.get("codec_type") == "video"), {})
    raw_format = data.get("format")
    fmt: dict[str, Any] = raw_format if isinstance(raw_format, dict) else {}
    return VideoDiscovery(
        source=source,
        source_type="local",
        title=path.stem,
        duration_s=float(fmt["duration"]) if fmt.get("duration") else None,
        width=int(video["width"]) if video.get("width") else None,
        height=int(video["height"]) if video.get("height") else None,
        status="discovered" if result.get("verified") else "blocked",
        errors=() if result.get("verified") else (str(result.get("error") or "media verification failed"),),
        raw=result,
    )


def discover_video(request: VideoCatchRequest) -> VideoDiscovery:
    issues = request.validate()
    if issues:
        return VideoDiscovery(
            source=request.source,
            source_type="invalid",
            status="blocked",
            errors=tuple(issues),
        )
    mode = select_source_mode(request)
    if mode == "local_passthrough":
        return _discovery_from_probe(request.source, Path(request.source).expanduser())
    if shutil.which("yt-dlp") is None:
        return VideoDiscovery(
            source=request.source,
            source_type=mode,
            status="blocked",
            errors=("yt-dlp is required for URL discovery",),
        )
    proc = subprocess.run(
        ["yt-dlp", "--dump-single-json", "--skip-download", request.source],
        capture_output=True,
        text=True,
        timeout=request.timeout_s,
        check=False,
    )
    if proc.returncode != 0:
        return VideoDiscovery(
            source=request.source,
            source_type=mode,
            status="failed",
            errors=(proc.stderr[-800:] or "yt-dlp discovery failed",),
        )
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return VideoDiscovery(source=request.source, source_type=mode, status="failed", errors=(str(exc),))
    formats = tuple(
        {
            key: item.get(key)
            for key in ("format_id", "ext", "width", "height", "fps", "filesize", "vcodec", "acodec")
            if item.get(key) is not None
        }
        for item in raw.get("formats", [])
        if isinstance(item, dict)
    )
    return VideoDiscovery(
        source=request.source,
        source_type=mode,
        title=str(raw.get("title") or ""),
        duration_s=float(raw["duration"]) if raw.get("duration") else None,
        width=int(raw["width"]) if raw.get("width") else None,
        height=int(raw["height"]) if raw.get("height") else None,
        formats=formats,
        subtitle_languages=tuple(sorted((raw.get("subtitles") or {}).keys())),
        raw={"extractor": raw.get("extractor"), "webpage_url": raw.get("webpage_url")},
    )


def _latest_media(directory: Path, before: set[Path]) -> Path | None:
    candidates = [
        path
        for path in directory.iterdir()
        if path.is_file() and path not in before and path.stat().st_size > 0
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def download_video(request: VideoCatchRequest) -> dict[str, Any]:
    """Download a source and return a verified local path, or an explicit failure."""
    issues = request.validate()
    if issues:
        return {"status": "blocked", "errors": issues, "request": request.to_dict()}
    if not is_url(request.source):
        verification = verify_media(request.source)
        return {
            "status": "completed" if verification.get("verified") else "failed",
            "path": request.source,
            "verification": verification,
            "request": request.to_dict(),
        }
    if shutil.which("yt-dlp") is None:
        return {"status": "blocked", "errors": ["yt-dlp is required for URL download"]}
    destination = Path(request.output_dir).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    before = set(destination.iterdir())
    command = [
        "yt-dlp",
        "--no-playlist" if not request.playlist else "--yes-playlist",
        "--format",
        format_selector(request),
        "--max-filesize",
        str(request.max_bytes),
        "-o",
        str(destination / "%(title).120s.%(ext)s"),
        request.source,
    ]
    try:
        proc = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=request.timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status": "failed", "errors": [f"download timed out after {request.timeout_s}s"]}
    if proc.returncode != 0:
        return {"status": "failed", "errors": [proc.stderr[-800:] or "yt-dlp download failed"]}
    path = _latest_media(destination, before)
    if path is None:
        return {"status": "failed", "errors": ["download completed without a new local file"]}
    verification = verify_media(path)
    return {
        "status": "completed" if verification.get("verified") else "failed",
        "path": str(path),
        "verification": verification,
        "format_selector": format_selector(request),
    }


__all__ = ["VideoCatcherError", "discover_video", "download_video", "verify_media"]
