"""Bounded key-frame extraction; paths are projections, hashes are evidence."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from .models import VideoProbe


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_key_frames(
    video: str | Path,
    shots: list[tuple[str, int, int]],
    output_dir: str | Path,
    probe: VideoProbe,
) -> list[dict[str, object]]:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for shot_id, start_ms, end_ms in shots:
        for label, ratio in (("entry", 0.15), ("exit", 0.85)):
            timestamp_ms = round(start_ms + (end_ms - start_ms) * ratio)
            output = destination / f"{shot_id}-{label}.jpg"
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{timestamp_ms / 1000:.3f}",
                "-i", str(video), "-frames:v", "1", "-q:v", "3", str(output), "-y",
            ]
            completed = subprocess.run(command, capture_output=True, timeout=60, check=False)
            if completed.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
                raise RuntimeError(f"FRAME_EXTRACTION_FAILED:{shot_id}:{label}")
            rows.append({
                "frame_id": f"frame:{_hash(output)[:16]}",
                "path": str(output),
                "sha256": _hash(output),
                "timestamp_ms": timestamp_ms,
                "shot_id": shot_id,
                "source_video_sha256": None,
                "source_duration_ms": probe.duration_ms,
            })
    return rows
