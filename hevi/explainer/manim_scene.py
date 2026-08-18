"""Explainer manim_scene —— 装配期把「代码即画面」渲成可进 Remotion 的素材。"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from hevi.explainer.contracts import ExplainerCue
from hevi.prompt.manim_compiler import resolve_scene_ir
from hevi.providers.manim.provider import manim_generate

logger = logging.getLogger(__name__)

def _job_id_for(output_dir: Path) -> str:
    resolved = output_dir.resolve()
    name = resolved.parent.name if resolved.name == "preview" else resolved.name
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name) or "explainer"


def _stage_asset(
    src: Path,
    output_dir: Path,
    index: int,
    remotion_public: Path | None = None,
) -> str:
    """复制到 output/manim;有 remotion public 时再拷一份,返回 staticFile 相对路径。"""
    job_id = _job_id_for(output_dir)
    rel = f"runs/{job_id}/manim/cue-{index}.mp4"
    local = output_dir / "manim" / f"cue-{index}.mp4"
    local.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() != local.resolve():
        shutil.copy2(src, local)
    if remotion_public is not None:
        public = Path(remotion_public) / rel
        public.parent.mkdir(parents=True, exist_ok=True)
        if public.resolve() != local.resolve():
            shutil.copy2(local, public)
        return rel
    return str(local)


async def attach_manim_scenes(
    cues: list[ExplainerCue],
    output_dir: Path,
    *,
    enabled: bool = True,
    renderer: Any = None,
    remotion_public: Path | None = None,
    width: int = 1920,
    height: int = 1080,
) -> list[ExplainerCue]:
    """给 manim_scene cue 渲 mp4 并写入 visual_config.assetUrl。

    失败不挡装配:降级为 voiceover,和 browser_broll 缺 URL 同一哲学。
    """
    if not enabled:
        for cue in cues:
            if cue.visual_type == "manim_scene":
                logger.info("manim_scene 已关闭,cue 降级为 voiceover")
                cue.visual_type = "voiceover"
        return cues
    generate = renderer or manim_generate
    for index, cue in enumerate(cues, start=1):
        if cue.visual_type != "manim_scene":
            continue
        if str((cue.visual_config or {}).get("assetUrl") or "").strip():
            continue
        ir = resolve_scene_ir(cue)
        dest = output_dir / "manim" / f"cue-{index}.raw.mp4"
        raw_code = str((cue.visual_config or {}).get("code") or cue.code_text or "").strip()
        code = raw_code if raw_code.startswith(("from ", "import ", "class ")) else None
        try:
            produced = await generate(
                prompt=ir.to_dict(),
                output_path=dest,
                duration_s=ir.duration_s,
                width=width,
                height=height,
                code=code,
            )
        except Exception as exc:
            logger.warning("manim_scene cue %s 渲染失败,降级 voiceover: %s", index, exc)
            cue.visual_type = "voiceover"
            continue
        path = Path(produced)
        if not path.exists() or path.stat().st_size == 0:
            logger.warning("manim_scene cue %s 产物为空,降级 voiceover", index)
            cue.visual_type = "voiceover"
            continue
        rel = _stage_asset(path, output_dir, index, remotion_public=remotion_public)
        cue.visual_config = dict(cue.visual_config or {})
        cue.visual_config["assetUrl"] = rel
        cue.visual_config["scene"] = ir.to_dict()
        cue.visual_config["manim_engine"] = "manim"
        logger.info("manim_scene cue %s -> %s", index, rel)
    return cues
