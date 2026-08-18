"""Offline Duix lip-sync: reference still/video + master wav → silent MP4.

Exclusive with Echo (TALKING_FACE_ENGINE=duix). The container is started
for the call and stopped afterwards so it does not sit on the shared 3080.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from hevi.digital_human.avatar_render import extract_frame
from hevi.digital_human.duix_service import DuixUnavailable
from hevi.explainer.avatar_pip import assert_lipsync_duration, strip_audio

logger = logging.getLogger(__name__)

_VIDEO_SUFFIXES = {".mp4", ".webm", ".mov", ".mkv", ".avi"}
_DEFAULT_CONTAINER = "duix-avatar-gen-video"
_DEFAULT_HEALTH = "http://127.0.0.1:8383/easy/query?code=ping"


def _container_name() -> str:
    return (os.getenv("DUIX_CONTAINER") or _DEFAULT_CONTAINER).strip()


def _health_url() -> str:
    return (os.getenv("DUIX_OFFLINE_HEALTH_URL") or _DEFAULT_HEALTH).strip()


def _stop_after() -> bool:
    return (os.getenv("DUIX_STOP_AFTER") or "1").strip() not in {"0", "false", "no"}


def is_video_path(path: Path) -> bool:
    return path.suffix.lower() in _VIDEO_SUFFIXES


def extract_reference_still(reference: Path, dest: Path) -> Path:
    """Duix lite takes a face still. A reference video is reduced to one frame."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not is_video_path(reference):
        if reference.resolve() != dest.resolve():
            dest.write_bytes(reference.read_bytes())
        return dest
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", "1", "-i", str(reference), "-frames:v", "1", str(dest)],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError:
        extract_frame(reference, dest)
    if not dest.exists() or dest.stat().st_size == 0:
        raise DuixUnavailable(f"无法从参考视频抽帧: {reference}")
    return dest


def duix_health_ok(url: str | None = None, *, timeout: float = 5.0) -> bool:
    target = url or _health_url()
    try:
        with urlopen(target, timeout=timeout) as response:
            return 200 <= int(response.status) < 400
    except (URLError, OSError, TimeoutError, ValueError):
        return False


def start_duix_container() -> bool:
    """Start the Duix container if docker is available. True if we issued start."""
    name = _container_name()
    inspect = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True,
        text=True,
        check=False,
    )
    if inspect.returncode != 0:
        raise DuixUnavailable(f"找不到 Duix 容器 {name},先按 docs/E2E_SETUP.md 创建")
    if inspect.stdout.strip() == "true":
        return False
    started = subprocess.run(
        ["docker", "start", name],
        capture_output=True,
        text=True,
        check=False,
    )
    if started.returncode != 0:
        raise DuixUnavailable(f"无法启动 {name}: {(started.stderr or '')[-200:]}")
    return True


def stop_duix_container() -> None:
    name = _container_name()
    subprocess.run(["docker", "stop", name], capture_output=True, text=True, check=False)


def wait_duix_ready(*, timeout_s: float = 90.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if duix_health_ok():
            return
        time.sleep(2.0)
    raise DuixUnavailable(f"Duix 健康检查超时: {_health_url()}")


async def generate_silent_duix(
    *,
    reference: Path,
    audio_path: Path,
    output_path: Path,
) -> Path:
    """Reference still/video + master wav → silent lip-sync mp4 matching wav length."""
    from hevi.audio.avatar_service import generate_avatar_clip

    if not reference.exists() or reference.stat().st_size == 0:
        raise DuixUnavailable(f"参考素材不存在: {reference}")
    if not audio_path.exists() or audio_path.stat().st_size == 0:
        raise DuixUnavailable(f"配音母带不存在: {audio_path}")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    still = output_path.parent / "duix_reference.jpg"
    extract_reference_still(Path(reference), still)

    started = start_duix_container()
    try:
        wait_duix_ready()
        raw = output_path.parent / f"{output_path.stem}_raw.mp4"
        await generate_avatar_clip(
            config=None,
            portrait_image=still,
            audio_path=Path(audio_path),
            output_path=raw,
        )
        if not raw.exists() or raw.stat().st_size == 0:
            raise DuixUnavailable(f"Duix 未产出口型视频: {raw}")
        silent = strip_audio(raw, output_path)
        assert_lipsync_duration(silent, Path(audio_path))
        logger.info("duix silent lipsync: %s", silent)
        return silent
    finally:
        if started or _stop_after():
            stop_duix_container()
            logger.info("duix container stopped (%s)", _container_name())
