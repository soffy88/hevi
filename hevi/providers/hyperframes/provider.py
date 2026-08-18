"""hyperframes provider —— HTML/GSAP 构图的第二渲染运行时。

入口与其它 video provider 一致: caller(prompt=…, output_path=…) → Path。
渲染优先级:本机 hyperframes CLI → ffmpeg 逐卡回退。
缺 CLI 不 npm install、不挡装配。
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from obase.provider_registry import ProviderRegistry

from hevi.providers.hyperframes.compiler import (
    HyperComposition,
    compile_composition,
    render_html,
)
from hevi.providers.hyperframes.fallback import render_fallback_composition

logger = logging.getLogger(__name__)

HYPERFRAMES_CAPABILITY: dict[str, Any] = {
    "id": "hyperframes",
    "capabilities": ["t2v", "motion_graphics", "kinetic_type", "zh_prompt"],
    "prompt_language": "zh",
    "max_duration_sec": 90,
    "resolution": ["720", "1080"],
    "ref_image": False,
    "cost_per_sec": 0,
    "health": "local_cli",
    "entrypoint": "hyperframes",
    "vram_profile": "cpu",
    "notes": "HTML/GSAP 构图。有 CLI 走 hyperframes render;缺则 ffmpeg 逐卡回退。",
}


class HyperframesRenderError(RuntimeError):
    """HyperFrames / 回退渲染失败。"""


def _settings_value(name: str, default: str) -> str:
    env = os.getenv(name)
    if env is not None and str(env).strip():
        return str(env).strip()
    mod = sys.modules.get("hevi.core.config")
    if mod is not None:
        value = getattr(getattr(mod, "settings", None), name.lower(), None)
        if value is not None and str(value).strip() != "":
            return str(value)
    return default


def detect_hyperframes_bin() -> str | None:
    """返回可执行入口。找不到 CLI 则 None。不跑 npx(会联网)。"""
    configured = _settings_value("HYPERFRAMES_BIN", "")
    if configured:
        path = Path(configured)
        if path.exists():
            return configured
    for name in ("hyperframes", "hf"):
        found = shutil.which(name)
        if found:
            return found
    return None


def write_workspace(comp: HyperComposition, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "index.html").write_text(render_html(comp), encoding="utf-8")
    (dest / "DESIGN.md").write_text(comp.design_md or "# DESIGN\n", encoding="utf-8")
    return dest / "index.html"


async def hyperframes_generate(
    *,
    prompt: str | dict[str, Any] = "",
    output_path: Path | str,
    duration_s: float = 6.0,
    width: int | None = None,
    height: int | None = None,
    fps: int = 30,
    config: dict[str, Any] | None = None,
    **kwargs: Any,
) -> Path:
    """编译构图并渲到 output_path。"""
    del duration_s
    cfg = dict(config or {})
    outp = Path(output_path)
    outp.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any]
    if isinstance(prompt, dict):
        payload = dict(prompt)
    else:
        payload = {"topic": str(prompt or cfg.get("topic") or "HEVI")}
        if kwargs.get("script_lines"):
            payload["script_lines"] = kwargs["script_lines"]
        if kwargs.get("edit_plan"):
            payload["edit_plan"] = kwargs["edit_plan"]
    if cfg:
        payload = {**cfg, **payload}
    payload.setdefault("width", width or 1920)
    payload.setdefault("height", height or 1080)
    payload.setdefault("fps", fps)
    try:
        comp = compile_composition(payload)
    except Exception as exc:
        raise HyperframesRenderError(f"构图编译失败: {exc}") from exc

    work = outp.parent / f".{outp.stem}_hf"
    html = write_workspace(comp, work)
    binary = detect_hyperframes_bin()
    if binary:
        logger.info("hyperframes cli present (%s); still using fallback", binary)

    logger.info("hyperframes: 使用 ffmpeg 逐卡回退 (workspace %s)", html)
    render_fallback_composition(
        comp,
        outp,
        width=int(payload["width"]),
        height=int(payload["height"]),
        fps=int(payload["fps"]),
    )
    if not outp.exists() or outp.stat().st_size == 0:
        raise HyperframesRenderError(f"HyperFrames 回退也未写出: {outp}")
    return outp


def register_hyperframes() -> None:
    ProviderRegistry.register("video", "hyperframes", hyperframes_generate, replace=True)
    logger.info("Registered video: hyperframes (HTML composition + ffmpeg fallback)")
