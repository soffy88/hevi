"""E3 渲染编排 —— 把 storyboard 配音后的 manifest 交给 Remotion(Node 项目,hevi-remotion/)
子进程渲染出竖屏 + 横屏 MP4。

配音/数字人按 job 写到 public/runs/<job_id>/,避免并发互踩。Remotion 仍静态读
src/data/run_manifest.json,所以渲染段用锁把该 job 的 manifest 拷进规范路径。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from hevi.explainer.avatar_pip import compose_avatar_overlay, strip_audio
from hevi.explainer.echo_avatar import (
    _presenter_src,
    _presenter_video_src,
    attach_echo_avatar,
)
from hevi.explainer.props import normalise_visual_config
from hevi.explainer.schemas import ManifestSegment, Storyboard
from hevi.explainer.voiceover import DEFAULT_RATE, DEFAULT_VOICE, synthesize_storyboard
from hevi.production.delivery_gate import ComposeGateError, assert_explainer_compose

logger = logging.getLogger(__name__)

_HEVI_REMOTION_DIR = Path(__file__).resolve().parent.parent.parent / "hevi-remotion"
_MANIFEST_PATH = _HEVI_REMOTION_DIR / "src" / "data" / "run_manifest.json"
_PUBLIC_DIR = _HEVI_REMOTION_DIR / "public"
_REMOTION_BIN = _HEVI_REMOTION_DIR / "node_modules" / ".bin" / "remotion"
_TITLE_CARD_S = 3.0
_REMOTION_LOCK = asyncio.Lock()


class RenderError(Exception):
    """Remotion 子进程渲染失败(非 0 退出码)。"""


@dataclass
class RenderResult:
    manifest: list[ManifestSegment]
    portrait_path: Path
    landscape_path: Path


def _manifest_payload(manifest: list[ManifestSegment]) -> list[dict]:
    payload = []
    for seg in manifest:
        data = seg.model_dump(by_alias=True)
        data["visual_config"] = normalise_visual_config(data.get("visual_config"))
        payload.append(data)
    return payload


def _write_manifest(manifest: list[ManifestSegment], dest: Path | None = None) -> None:
    import json

    path = dest or _MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_manifest_payload(manifest), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _job_id_for(output_dir: Path) -> str:
    resolved = output_dir.resolve()
    name = resolved.parent.name if resolved.name == "preview" else resolved.name
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name) or "explainer"


def should_compose_avatar(output_dir: Path, storyboard: Storyboard) -> bool:
    """Preview skips digital-human overlay; full film composes after base QC."""
    if output_dir.name == "preview":
        return False
    return bool(_presenter_src(storyboard) or _presenter_video_src(storyboard))


async def _overlay_talking_face(
    *,
    storyboard: Storyboard,
    manifest: list[ManifestSegment],
    output_dir: Path,
    audio_dir: Path,
    portrait_path: Path,
    landscape_path: Path,
    expected_duration_s: float,
    remotion_public: Path,
    avatar_rel: str,
) -> None:
    avatar = await attach_echo_avatar(
        storyboard=storyboard,
        manifest=manifest,
        output_dir=output_dir,
        audio_dir=audio_dir,
        remotion_public=remotion_public,
        avatar_rel=avatar_rel,
        stamp_remotion=False,
    )
    if avatar is None:
        raise ComposeGateError("数字人素材已提供但未产出口型")
    silent = output_dir / "avatar_silent.mp4"
    strip_audio(avatar, silent)
    for video_path in (portrait_path, landscape_path):
        stacked = video_path.with_name(f"{video_path.stem}_avatar.mp4")
        compose_avatar_overlay(video_path, silent, stacked)
        shutil.move(str(stacked), str(video_path))
    assert_explainer_compose(portrait_path, expected_duration_s=expected_duration_s)
    assert_explainer_compose(landscape_path, expected_duration_s=expected_duration_s)


def _expected_duration_s(manifest: list[ManifestSegment]) -> float:
    return _TITLE_CARD_S + sum(float(seg.duration_sec or 0.0) for seg in manifest)


def _mix_bgm_duck(video_path: Path, bgm_path: Path, dest: Path) -> None:
    """把程序化 BGM 侧链闪避混进已有旁白轨(人声段压到约 -22dB)。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(bgm_path),
        "-filter_complex",
        "[0:a]asplit=2[narr][narrsc];"
        "[1:a]volume=-18dB[bgmv];"
        "[bgmv][narrsc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300[bgmduck];"
        "[narr][bgmduck]amix=inputs=2:duration=first:dropout_transition=0[aout]",
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        raise RuntimeError(f"BGM 混音失败: {(proc.stderr or '')[-400:]}")


def _attach_procedural_bgm(video_path: Path, duration_s: float, work_dir: Path) -> Path:
    from hevi.audio.procedural_bgm import BgmConfig, synthesize_bgm, write_wav

    bgm_wav = work_dir / "bgm.wav"
    samples, _grid = synthesize_bgm(BgmConfig(mood="calm", duration_s=max(duration_s, 4.0)))
    write_wav(samples, bgm_wav)
    mixed = work_dir / f"{video_path.stem}_bgm.mp4"
    _mix_bgm_duck(video_path, bgm_wav, mixed)
    shutil.move(str(mixed), str(video_path))
    return video_path


async def _run_remotion_render(composition_id: str, output_path: Path) -> None:
    if not _HEVI_REMOTION_DIR.is_dir():
        raise RenderError(
            f"Remotion 项目目录不存在: {_HEVI_REMOTION_DIR}；请重建 API 镜像"
        )
    if not _REMOTION_BIN.is_file():
        raise RenderError(
            f"Remotion CLI 不可用: {_REMOTION_BIN}；请重建 API 镜像并安装 hevi-remotion 依赖"
        )
    # Remotion runs with hevi-remotion/ as cwd. Resolve the output first, or a
    # relative ``output/explainer/...`` path would be written inside the
    # unmounted Remotion project instead of the shared /app/output volume.
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        str(_REMOTION_BIN),
        "render",
        composition_id,
        str(output_path),
        "--concurrency=4",
        cwd=str(_HEVI_REMOTION_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    log_tail = stdout.decode(errors="replace")[-4000:] if stdout else ""
    if proc.returncode != 0:
        raise RenderError(
            f"remotion render {composition_id} 失败 (exit={proc.returncode}): {log_tail}"
        )
    logger.info("explainer render: %s 完成 -> %s", composition_id, output_path)


async def render_storyboard(
    storyboard: Storyboard,
    output_dir: Path,
    *,
    voice: str = DEFAULT_VOICE,
    rate: str = DEFAULT_RATE,
) -> RenderResult:
    """storyboard(E0 产出,未配音)→ 配音 + 写 manifest/audio → 子进程渲染竖屏/横屏。"""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    job_id = _job_id_for(output_dir)
    job_public = _PUBLIC_DIR / "runs" / job_id
    audio_dir = job_public / "audio"
    audio_prefix = f"runs/{job_id}/audio"
    avatar_rel = f"runs/{job_id}/continuous_avatar"
    if audio_dir.exists():
        shutil.rmtree(audio_dir)
    manifest = await synthesize_storyboard(
        storyboard,
        audio_dir,
        voice=voice,
        rate=rate,
        audio_public_prefix=audio_prefix,
    )
    _write_manifest(manifest, output_dir / "run_manifest.json")

    portrait_path = output_dir / "portrait.mp4"
    landscape_path = output_dir / "landscape.mp4"
    async with _REMOTION_LOCK:
        _write_manifest(manifest)
        await _run_remotion_render("Explainer-Portrait", portrait_path)
        await _run_remotion_render("Explainer-Landscape", landscape_path)

    expected = _expected_duration_s(manifest)
    try:
        _attach_procedural_bgm(portrait_path, expected, output_dir)
        _attach_procedural_bgm(landscape_path, expected, output_dir)
    except Exception as exc:
        logger.warning("explainer BGM 跳过(成片本身保留): %s", exc)

    try:
        assert_explainer_compose(portrait_path, expected_duration_s=expected)
        assert_explainer_compose(landscape_path, expected_duration_s=expected)
    except ComposeGateError:
        raise
    except Exception as exc:
        raise ComposeGateError(f"成片校验失败: {exc}") from exc

    if should_compose_avatar(output_dir, storyboard):
        try:
            await _overlay_talking_face(
                storyboard=storyboard,
                manifest=manifest,
                output_dir=output_dir,
                audio_dir=audio_dir,
                portrait_path=portrait_path,
                landscape_path=landscape_path,
                expected_duration_s=expected,
                remotion_public=_PUBLIC_DIR,
                avatar_rel=avatar_rel,
            )
        except ComposeGateError:
            raise
        except Exception as exc:
            raise ComposeGateError(f"数字人叠片失败: {exc}") from exc

    return RenderResult(
        manifest=manifest, portrait_path=portrait_path, landscape_path=landscape_path
    )
