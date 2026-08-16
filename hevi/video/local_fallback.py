"""本地动画兜底 —— freevideo 确定性动画帧作为视频生成的回退/低成本通道。

用途:
  1. GPU 不足/云 provider 失败时,把一镜头降级为 freevideo 程序化动画帧
     (quote 模板,画面有动效,不会黑屏/缺镜头);
  2. 免费生成 intro/outro 片段(orchestrate_longvideo 的 intro_clip/outro_clip
     参数接受文件路径 —— 直接喂本模块产物);
  3. 空镜/过渡镜头的零成本方案。

执行链路复用 hevi.assembly.freevideo(确定性分镜 → CSS 动画 HTML → 录屏 →
精确时长),全程零 API 费用。失败不 raise(3O 规范),返回 None 由调用方处理。
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from pathlib import Path

from hevi.assembly.freevideo.storyboard import FramePlan
from hevi.assembly.freevideo.workflow import FreeVideoConfig, FreeVideoInput, free_video_workflow

logger = logging.getLogger(__name__)

#: freevideo 全流程的最小可跑配置(默认竖屏 9:16 与主管道一致)。
_DEFAULT_WIDTH = 1080
_DEFAULT_HEIGHT = 1920
_DEFAULT_FPS = 24
_DEFAULT_DURATION = 4.0

#: 可用的动画模板(kind),兜底时按内容自动选。
_FALLBACK_KINDS = ("quote", "title", "typewriter", "scene", "cards")


def _pick_kind(prompt: str, reference_image: Path | None) -> str:
    """按镜头 prompt 粗选模板:有参考图→title(文字开场),数据感→cards,默认 quote。"""
    p = (prompt or "").lower()
    if any(k in p for k in ("对比", "数据", "比例", "percent", "stat", "chart")):
        return "cards"
    if reference_image is not None:
        return "title"
    if any(k in p for k in ("开场", "intro", "片头", "opening", "hero")):
        return "title"
    if any(k in p for k in ("收束", "结尾", "outro", "ending", "close")):
        return "quote"
    return "quote"


def render_animation_fallback(
    *,
    prompt: str,
    output_path: Path | str,
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
    fps: int = _DEFAULT_FPS,
    duration: float = _DEFAULT_DURATION,
    reference_image: Path | str | None = None,
    title: str = "HEVI",
) -> Path | None:
    """一镜头 → freevideo 程序化动画帧(同步入口,失败返回 None)。"""
    return asyncio.run(
        render_animation_fallback_async(
            prompt=prompt,
            output_path=output_path,
            width=width,
            height=height,
            fps=fps,
            duration=duration,
            reference_image=reference_image,
            title=title,
        )
    )


async def render_animation_fallback_async(
    *,
    prompt: str,
    output_path: Path | str,
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
    fps: int = _DEFAULT_FPS,
    duration: float = _DEFAULT_DURATION,
    reference_image: Path | str | None = None,
    title: str = "HEVI",
) -> Path | None:
    """异步版。workflow 失败 → None(不 raise,由调用方决定是否继续)。"""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    ref = Path(reference_image) if reference_image else None
    kind = _pick_kind(prompt, ref)
    plan = FramePlan(
        kind=kind,
        title=title,
        body=(prompt or title)[:180],
        duration=max(2.0, min(10.0, duration)),
    )
    config = FreeVideoConfig(
        width=width, height=height, fps=fps,
        frame_duration=plan.duration, palette="deep",
    )
    # 单镜 → 单帧直出(workflow 会把它 concat 成一个 mp4)。
    with tempfile.TemporaryDirectory(prefix="hevi_fallback_") as td:
        result = await free_video_workflow(
            config, FreeVideoInput(plans=[plan]), Path(td),
        )
        if result.get("status") != "completed":
            logger.warning("freevideo fallback failed: %s", result.get("error"))
            return None
        src = Path(result["output_path"])
        if not src.exists() or src.stat().st_size == 0:
            logger.warning("freevideo fallback produced empty output")
            return None
        # 复制到目标(workflow 产物在临时目录,不直接引用)。
        src.replace(out)
    logger.info("freevideo animation fallback → %s (kind=%s)", out, kind)
    return out


def render_intro_outro(
    *,
    text: str,
    output_path: Path | str,
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
    fps: int = _DEFAULT_FPS,
    duration: float = _DEFAULT_DURATION,
    title: str = "HEVI",
    is_intro: bool = True,
) -> Path | None:
    """免费片头/片尾:title 模板动画帧,直接喂 orchestrate_longvideo 的
    intro_clip/outro_clip 参数(该参数接受文件路径)。"""
    return asyncio.run(
        render_intro_outro_async(
            text=text, output_path=output_path, width=width, height=height,
            fps=fps, duration=duration, title=title, is_intro=is_intro,
        )
    )


async def render_intro_outro_async(
    *,
    text: str,
    output_path: Path | str,
    width: int = _DEFAULT_WIDTH,
    height: int = _DEFAULT_HEIGHT,
    fps: int = _DEFAULT_FPS,
    duration: float = _DEFAULT_DURATION,
    title: str = "HEVI",
    is_intro: bool = True,
) -> Path | None:
    """异步版(供 async 主管道内联调用,不嵌套 asyncio.run)。"""
    kind = "title" if is_intro else "quote"
    plan = FramePlan(kind=kind, title=title, body=text[:180], duration=duration)
    with tempfile.TemporaryDirectory(prefix="hevi_intro_") as td:
        result = await free_video_workflow(
            FreeVideoConfig(width=width, height=height, fps=fps, frame_duration=duration),
            FreeVideoInput(plans=[plan]),
            Path(td),
        )
        if result.get("status") != "completed":
            logger.warning("freevideo intro/outro failed: %s", result.get("error"))
            return None
        src = Path(result["output_path"])
        if src.exists() and src.stat().st_size > 0:
            src.replace(Path(output_path))
            return Path(output_path)
    return None


__all__ = [
    "render_animation_fallback",
    "render_animation_fallback_async",
    "render_intro_outro",
]
