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

from hevi.explainer.props import normalise_visual_config
from hevi.explainer.schemas import ManifestSegment, Storyboard
from hevi.explainer.voiceover import DEFAULT_RATE, DEFAULT_VOICE, synthesize_storyboard

logger = logging.getLogger(__name__)

_HEVI_REMOTION_DIR = Path(__file__).resolve().parent.parent.parent / "hevi-remotion"
_MANIFEST_PATH = _HEVI_REMOTION_DIR / "src" / "data" / "run_manifest.json"
_AUDIO_DIR = _HEVI_REMOTION_DIR / "public" / "audio"
_REMOTION_BIN = _HEVI_REMOTION_DIR / "node_modules" / ".bin" / "remotion"


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
    payload = []
    for seg in manifest:
        data = seg.model_dump(by_alias=True)
        # 最后一道防线:无论 visual_config 从哪条路径进来(LLM 直出 / 旧客户端 /
        # 注入 Provider),写进 manifest 前一律规整为 dict,绝不让字符串/脏类型
        # 漏到 Remotion 模板的链式访问里。
        data["visual_config"] = normalise_visual_config(data.get("visual_config"))
        payload.append(data)
    _MANIFEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
    if _AUDIO_DIR.exists():
        shutil.rmtree(_AUDIO_DIR)
    manifest = await synthesize_storyboard(storyboard, _AUDIO_DIR, voice=voice, rate=rate)
    _write_manifest(manifest)

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    portrait_path = output_dir / "portrait.mp4"
    landscape_path = output_dir / "landscape.mp4"

    await _run_remotion_render("Explainer-Portrait", portrait_path)
    await _run_remotion_render("Explainer-Landscape", landscape_path)

    return RenderResult(
        manifest=manifest, portrait_path=portrait_path, landscape_path=landscape_path
    )
