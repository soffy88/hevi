"""Explainer continuous-avatar: concat voiceover then Echo talking-face."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from hevi.digital_human.talking_face import generate_talking_face
from hevi.explainer.schemas import ManifestSegment, Storyboard

logger = logging.getLogger(__name__)

PRESENTER_IMAGE_KEY = "hevi_presenter_image"
PRESENTER_VIDEO_KEY = "hevi_presenter_video"


def concat_audio_files(paths: list[Path], dest: Path) -> Path:
    """Join segment audio in order. Single input is copied (no ffmpeg)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = [p for p in paths if p.exists() and p.stat().st_size > 0]
    if not existing:
        raise FileNotFoundError("没有可拼接的配音段")
    if len(existing) == 1:
        if existing[0].resolve() != dest.resolve():
            shutil.copyfile(existing[0], dest)
        return dest
    inputs: list[str] = []
    for path in existing:
        inputs.extend(["-i", str(path)])
    n = len(existing)
    labels = "".join(f"[{i}:a]" for i in range(n))
    cmd = [
        "ffmpeg",
        "-y",
        *inputs,
        "-filter_complex",
        f"{labels}concat=n={n}:v=0:a=1[a]",
        "-map",
        "[a]",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(f"配音拼接失败: {(proc.stderr or '')[-400:]}")
    return dest


async def materialize_image(src: str | Path, dest: Path) -> Path:
    text = str(src).strip()
    parsed = urlparse(text)
    if parsed.scheme in {"http", "https"}:
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            response = await client.get(text)
            response.raise_for_status()
            dest.write_bytes(response.content)
        return dest
    path = Path(text)
    if not path.exists() or path.stat().st_size == 0:
        raise FileNotFoundError(f"解说员照片不存在: {path}")
    return path


def _first_visual_config(storyboard: Storyboard) -> dict[str, Any]:
    if not storyboard.segments:
        return {}
    cfg = storyboard.segments[0].visual_config or {}
    return cfg if isinstance(cfg, dict) else {}


def _presenter_src(storyboard: Storyboard) -> str | None:
    value = _first_visual_config(storyboard).get(PRESENTER_IMAGE_KEY)
    return str(value) if value else None


def _presenter_video_src(storyboard: Storyboard) -> str | None:
    value = _first_visual_config(storyboard).get(PRESENTER_VIDEO_KEY)
    return str(value) if value else None


def _audio_paths(manifest: list[ManifestSegment], audio_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for seg in manifest:
        name = Path(seg.audio_file).name
        candidate = audio_dir / name
        if candidate.exists():
            paths.append(candidate)
    return paths


def enable_remotion_avatar(
    storyboard: Storyboard,
    manifest: list[ManifestSegment],
    image_src: str,
    *,
    avatar_src: str | None = None,
) -> None:
    """Remotion hasAvatarTrack() keys off packaging.presenter_image_url."""
    for target in (
        storyboard.segments[0].visual_config if storyboard.segments else None,
        manifest[0].visual_config if manifest else None,
    ):
        if not isinstance(target, dict):
            continue
        packaging = dict(target.get("packaging") or {})
        packaging["presenter_image_url"] = image_src
        if avatar_src:
            packaging["avatar_src"] = avatar_src
        target["packaging"] = packaging


async def attach_echo_avatar(
    *,
    storyboard: Storyboard,
    manifest: list[ManifestSegment],
    output_dir: Path,
    audio_dir: Path,
    remotion_public: Path,
    avatar_rel: str = "continuous_avatar",
    stamp_remotion: bool = True,
) -> Path | None:
    """Build master voiceover + talking-face mp4. None if no presenter still/video."""
    image_src = _presenter_src(storyboard)
    video_src = _presenter_video_src(storyboard)
    if not image_src and not video_src:
        return None
    audio_paths = _audio_paths(manifest, audio_dir)
    if not audio_paths:
        raise FileNotFoundError("解说员素材已提供但没有可拼的配音段,数字人无法生成")
    output_dir.mkdir(parents=True, exist_ok=True)
    master = concat_audio_files(audio_paths, output_dir / "master_voiceover.wav")
    local_image = None
    if image_src:
        local_image = await materialize_image(image_src, output_dir / "presenter.jpg")
    local_video = None
    if video_src:
        local_video = await materialize_image(video_src, output_dir / "presenter_ref.mp4")
        if local_image is None:
            from hevi.digital_human.duix_offline import extract_reference_still

            local_image = extract_reference_still(local_video, output_dir / "presenter.jpg")
    if local_image is None:
        raise FileNotFoundError("数字人缺少照片或参考视频")
    avatar_dir = remotion_public.joinpath(*Path(avatar_rel).parts)
    avatar_dir.mkdir(parents=True, exist_ok=True)
    portrait = avatar_dir / "continuous_avatar_p.mp4"
    await generate_talking_face(
        image_path=local_image,
        audio_path=master,
        output_path=portrait,
        reference_video=local_video,
    )
    if not portrait.exists() or portrait.stat().st_size == 0:
        raise RuntimeError(f"数字人产物为空: {portrait}")
    landscape = avatar_dir / "continuous_avatar_l.mp4"
    if landscape.resolve() != portrait.resolve():
        shutil.copyfile(portrait, landscape)
    avatar_src = f"{avatar_rel.rstrip('/')}/continuous_avatar_p.mp4"
    if stamp_remotion:
        enable_remotion_avatar(
            storyboard, manifest, image_src or str(local_image), avatar_src=avatar_src
        )
    logger.info("explainer avatar: %s", portrait)
    return portrait
