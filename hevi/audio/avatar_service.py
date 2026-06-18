"""hevi.audio.avatar_service — Duix lip-sync avatar generation.

Bypasses oprim._providers.duix which has 4 known bugs (report to oprim owner):
  1. Submit success check: `code not in (0, 200, ...)` — Duix returns 10000
  2. Status completion: `status in (..., "2")` — Duix returns int 2, not string "2"
  3. Result field: `qdata.get("video_url")` — actual field is `data["result"]`
  4. Result retrieval: tries HTTP GET on a container-local path, not an HTTP URL
"""
from __future__ import annotations

import asyncio
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from hevi.audio.audio_config import AudioProvider
from hevi.observability import track_provider_call

DUIX_BASE_URL = "http://127.0.0.1:8383"
DUIX_HOST_DIR = Path.home() / "duix_avatar_data/face2face"
DUIX_CONTAINER_PREFIX = "/code/data"
_POLL_INTERVAL = 3.0
_TIMEOUT_S = 300.0
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def _host_to_container(host_path: Path) -> str:
    return f"{DUIX_CONTAINER_PREFIX}/{host_path.relative_to(DUIX_HOST_DIR)}"


def _audio_duration(audio: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "csv=p=0",
         "-show_entries", "format=duration", str(audio)],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


def _make_portrait_video(portrait: Path, dur_s: float, out: Path) -> None:
    """Loop a still JPEG into a 512×512 MP4 long enough to cover dur_s."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-loop", "1", "-i", str(portrait),
            "-t", str(dur_s + 1.0),
            "-vf", "fps=25,scale=512:512",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(out),
        ],
        check=True, capture_output=True,
    )


async def _submit_and_poll(
    *,
    portrait_path: str,
    audio_path: str,
    job_code: str,
) -> Path:
    """Call Duix /easy/submit + /easy/query, return host path of result MP4."""
    import httpx

    async with httpx.AsyncClient(timeout=_TIMEOUT_S) as client:
        resp = await client.post(
            f"{DUIX_BASE_URL}/easy/submit",
            json={
                "code": job_code,
                "audio_url": audio_path,
                "video_url": portrait_path,
                "chaofen": 0,
                "watermark_switch": 0,
                "pn": 1,
            },
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("code") != 10000:
            raise RuntimeError(f"Duix submit rejected: {body}")

        elapsed = 0.0
        while elapsed < _TIMEOUT_S:
            await asyncio.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL
            q = await client.get(
                f"{DUIX_BASE_URL}/easy/query", params={"code": job_code}
            )
            q.raise_for_status()
            d = q.json().get("data", {})
            status = d.get("status")
            if status == 2:
                result_path = DUIX_HOST_DIR / "temp" / f"{job_code}-r.mp4"
                if not result_path.exists():
                    raise RuntimeError(
                        f"Duix result not found at {result_path}"
                    )
                return result_path
            if status in (3,) or str(status) in ("-1", "error", "failed"):
                raise RuntimeError(f"Duix job failed: {d}")

    raise RuntimeError(f"Duix job {job_code} timed out after {_TIMEOUT_S}s")


async def avatar_generate(
    *,
    config: Any,
    provider: str,  # "duix" — API compat
    portrait_image: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """Core avatar generation — provider param kept for API compat."""
    async with track_provider_call(AudioProvider.DUIX):
        DUIX_HOST_DIR.mkdir(parents=True, exist_ok=True)
        if not portrait_image.exists():
            raise FileNotFoundError(f"Portrait not found: {portrait_image}")
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio not found: {audio_path}")

        job_code = str(uuid.uuid4())
        audio_staged = DUIX_HOST_DIR / f"audio_{job_code}.wav"
        shutil.copy2(audio_path, audio_staged)

        portrait_staged: Path
        if portrait_image.suffix.lower() in _IMAGE_SUFFIXES:
            portrait_staged = DUIX_HOST_DIR / f"portrait_{job_code}.mp4"
            dur = _audio_duration(audio_staged)
            _make_portrait_video(portrait_image, dur, portrait_staged)
        else:
            portrait_staged = DUIX_HOST_DIR / f"portrait_{job_code}{portrait_image.suffix}"
            shutil.copy2(portrait_image, portrait_staged)

        try:
            result_host = await _submit_and_poll(
                portrait_path=_host_to_container(portrait_staged),
                audio_path=_host_to_container(audio_staged),
                job_code=job_code,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(result_host, output_path)
            return output_path
        finally:
            audio_staged.unlink(missing_ok=True)
            portrait_staged.unlink(missing_ok=True)


async def generate_avatar_clip(
    *,
    config: Any,
    portrait_image: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """Duix digital human avatar clip generation (lip-sync)."""
    return await avatar_generate(
        config=config,
        provider=str(AudioProvider.DUIX),
        portrait_image=portrait_image,
        audio_path=audio_path,
        output_path=output_path,
    )
