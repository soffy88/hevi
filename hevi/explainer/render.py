"""E3 渲染编排 —— 把 storyboard 配音后的 manifest 交给 Remotion(Node 项目,hevi-remotion/)
子进程渲染出竖屏 + 横屏 MP4。

hevi 后端是 Python,动画/字幕渲染是 Remotion(TypeScript),两边只能靠文件交接:manifest
写进 hevi-remotion/src/data/run_manifest.json、配音 mp3 写进 hevi-remotion/public/audio/,
Remotion 每次渲染都会重新 bundle,天然读到最新文件。

P0 限制(同 tongjian"尽力而为"的既有惯例):hevi-remotion/ 的 src/data、public/audio 是
共享可变状态,不支持并发 run——同一时间只能跑一个 explainer 渲染。真要并发得给
hevi-remotion 项目目录做隔离(每 run 一份),现在不做,先用起来。
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from hevi.explainer.schemas import ManifestSegment, Storyboard
from hevi.explainer.voiceover import DEFAULT_RATE, DEFAULT_VOICE, synthesize_storyboard

logger = logging.getLogger(__name__)

_HEVI_REMOTION_DIR = Path(__file__).resolve().parent.parent.parent / "hevi-remotion"
_MANIFEST_PATH = _HEVI_REMOTION_DIR / "src" / "data" / "run_manifest.json"
_AUDIO_DIR = _HEVI_REMOTION_DIR / "public" / "audio"


class RenderError(Exception):
    """Remotion 子进程渲染失败(非 0 退出码)。"""


@dataclass
class RenderResult:
    manifest: list[ManifestSegment]
    portrait_path: Path
    landscape_path: Path


def _write_manifest(manifest: list[ManifestSegment]) -> None:
    import json

    _MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = [seg.model_dump(by_alias=True) for seg in manifest]
    _MANIFEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


async def _run_remotion_render(composition_id: str, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        "npx",
        "remotion",
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
    if _AUDIO_DIR.exists():
        shutil.rmtree(_AUDIO_DIR)
    manifest = await synthesize_storyboard(storyboard, _AUDIO_DIR, voice=voice, rate=rate)
    _write_manifest(manifest)

    output_dir.mkdir(parents=True, exist_ok=True)
    portrait_path = output_dir / "portrait.mp4"
    landscape_path = output_dir / "landscape.mp4"

    await _run_remotion_render("Explainer-Portrait", portrait_path)
    await _run_remotion_render("Explainer-Landscape", landscape_path)

    return RenderResult(
        manifest=manifest, portrait_path=portrait_path, landscape_path=landscape_path
    )
