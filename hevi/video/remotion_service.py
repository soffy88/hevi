"""Remotion 合成服务 —— 对接 hevi-remotion 子项目,程序化视频合成。

对标 OpenMontage 的 remotion-composer(12 种场景类型 + spring 动画)。
Hevi 已有 hevi-remotion/ 子项目(Remotion 4 + React 18 + TypeScript),
但后端从未接入。本模块是桥接层:把 Hevi 的装配指令(JSON manifest)转成
Remotion 可消费的 input props,调 `npx remotion render` 出成片。

用法:
    from hevi.video.remotion_service import render_remotion
    render_remotion(
        manifest={"scenes": [{"type": "text_card", "text": "..."}, ...]},
        output=Path("output/final.mp4"),
        composition="ExplainerVideo",
    )
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_REMOTION_DIR = Path(__file__).resolve().parent.parent.parent / "hevi-remotion"


def _ensure_remotion_ready() -> Path:
    """确保 hevi-remotion 的 node_modules 存在。返回项目根。"""
    if not _REMOTION_DIR.exists():
        raise RuntimeError(f"hevi-remotion not found at {_REMOTION_DIR}")

    node_modules = _REMOTION_DIR / "node_modules"
    if not node_modules.exists():
        logger.info("Installing hevi-remotion dependencies...")
        subprocess.run(
            ["npm", "install"],
            cwd=str(_REMOTION_DIR),
            check=True,
            timeout=180,
        )
    return _REMOTION_DIR


def render_remotion(
    manifest: dict[str, Any],
    output: Path,
    *,
    composition: str = "ExplainerVideo",
    props_file: Path | None = None,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    codec: str = "h264",
    image_format: str = "jpeg",
    quality: int = 80,
) -> Path:
    """通过 Remotion 渲染视频。

    Args:
        manifest: Remotion input props(JSON 对象,结构由 hevi-remotion 组件定义)
        output: 输出文件路径
        composition: Remotion composition 名称
        props_file: 可选的 props JSON 文件(不传则自动写入临时文件)
        width/height: 分辨率
        fps: 帧率
        codec: h264 / h265 / vp8 / vp9 / prores
        image_format: jpeg / png / webp
        quality: 质量 0-100

    Returns:
        输出路径
    """
    project_dir = _ensure_remotion_ready()
    output.parent.mkdir(parents=True, exist_ok=True)

    # 写入 props JSON
    pf = props_file or (output.parent / f"_remotion_props_{output.stem}.json")
    pf.parent.mkdir(parents=True, exist_ok=True)
    with open(pf, "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    cmd = [
        "npx", "remotion", "render",
        str(project_dir / "src" / "index.ts"),
        composition,
        str(output),
        "--props", str(pf),
        "--width", str(width),
        "--height", str(height),
        "--fps", str(fps),
        "--codec", codec,
        "--image-format", image_format,
        "--jpeg-quality", str(quality),
        "--concurrency", "50%",
        "--log", "error",
    ]

    logger.info("Remotion render: %s → %s", composition, output)
    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode != 0:
            logger.error("Remotion render failed:\n%s\n%s", result.stdout, result.stderr)
            msg = f"Remotion render failed (exit {result.returncode})"
            raise RuntimeError(msg) from None
    except FileNotFoundError as exc:
        raise RuntimeError(
            "npx not found. Install Node.js 18+ "
            "and run 'npm install' in hevi-remotion/"
        ) from exc

    if not output.exists():
        raise RuntimeError(f"Remotion render completed but output not found: {output}")

    logger.info("Remotion render complete: %s", output)
    return output


def render_scene_card(
    *,
    card_type: str,
    text: str = "",
    subtitle: str = "",
    data: dict[str, Any] | None = None,
    output: Path | None = None,
    duration_frames: int = 90,
) -> Path:
    """渲染单个场景卡片(text_card / stat_card / callout 等)。

    便捷封装:构造 manifest → 调 render_remotion → 返回输出。
    """
    scene = {"type": card_type, "text": text, "subtitle": subtitle}
    if data:
        scene["data"] = data

    manifest = {
        "scenes": [scene],
        "globalDurationFrames": duration_frames,
    }

    out = output or Path(f"output/remotion/{card_type}_{hash(text) % 10000}.mp4")
    return render_remotion(
        manifest, out,
        composition="ExplainerVideo",
        width=1920, height=1080, fps=30,
    )


def list_compositions() -> list[str]:
    """列出 hevi-remotion 中可用的 composition 名称。"""
    project_dir = _REMOTION_DIR
    root_tsx = project_dir / "src" / "Root.tsx"
    if not root_tsx.exists():
        return []

    compositions = []
    content = root_tsx.read_text()
    import re
    compositions = [
        m.group(1) for m in re.finditer(r'<Composition\s+[^>]*id="([^"]+)"', content)
    ]
    return compositions or ["ExplainerVideo", "Zhibo"]
