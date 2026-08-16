"""freevideo:render —— 逐帧录屏 + 精确时长 + concat(html-video 渲染路线)。

每镜 = 一个独立自包含 HTML → Playwright 无头 Chromium 录屏(复用
oprim_playwright:字体冻结/动画时长探测已内化)→ webm→mp4 → 精确时长
(短了 tpad 补尾,长了 -t 裁剪,html-video explicit-duration 同款)→
concat filter 统一重编码拼接(杜绝跨段 -c copy 花屏,hevi assembler 经验)。

全程零云调用:只耗 CPU 与磁盘。
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

from hevi.assembly.freevideo.storyboard import FramePlan
from hevi.assembly.freevideo.templates import render_frame_html
from hevi.pipeline_lite.oprim.oprim_playwright import record_html_to_video

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str, float], None]


def _step(on_step: ProgressFn | None, stage: str, pct: float) -> None:
    if on_step is not None:
        on_step(stage, pct)


def _probe_duration(path: Path) -> float:
    """ffprobe 探测媒体时长(秒);失败 0。"""
    if not shutil.which("ffprobe"):
        return 0.0
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            return float(r.stdout.strip())
    except (ValueError, OSError):
        pass
    return 0.0


def _ffmpeg(args: list[str], *, timeout: int = 900) -> None:
    """跑 ffmpeg,失败抛 RuntimeError(带 stderr 尾部)。"""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg 不在 PATH,无法编码")
    proc = subprocess.run(
        ["ffmpeg", "-y", *args], capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {proc.stderr[-500:]}")


def _trim_to_exact(src: Path, dst: Path, duration_s: float, fps: int) -> Path:
    """把 mp4 精确到 duration_s:短了 tpad clone 补尾,长了 -t 裁剪。

    html-video explicit-duration 同款:录屏可能因动画探测更长,也可能因
    recorder 抖动略短 —— 统一 pad-then-trim 保证每帧时长精确可预期。
    """
    actual = _probe_duration(src)
    if actual <= 0:
        # 探测失败:直接用 -t 硬裁(不补尾,短了就短了)
        _ffmpeg(
            ["-i", str(src), "-t", f"{duration_s:.3f}", "-r", str(fps),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
             str(dst)]
        )
        return dst
    # 无论长短都走 tpad+trim:不满足时 clone 末帧补足,满足时 -t 收齐。
    _ffmpeg(
        ["-i", str(src),
         "-vf", f"tpad=stop_mode=clone:stop_duration={duration_s + 1.0:.3f}",
         "-t", f"{duration_s:.3f}",
         "-r", str(fps), "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-preset", "veryfast", "-movflags", "+faststart",
         str(dst)]
    )
    return dst


def _resolve_corpus_broll(slot: str) -> str | None:
    """从本地素材语料库(data/corpus)按槽描述选最佳片段,返回绝对路径。

    语料库未构建 → None(调用方跳过该帧背景,不阻断)。
    """
    try:
        import os

        from hevi.sourcing.corpus import Corpus

        root = Path(os.environ.get("HEVI_CORPUS_DIR", "data/corpus"))
        if not (root / "index.jsonl").exists():
            logger.info("语料库未构建(%s),跳过 corpus broll", root)
            return None
        corpus = Corpus.load(root)
        hit = corpus.best_for_slot(slot)
        return hit["local_abs_path"] if hit else None
    except Exception as exc:  # 检索失败不阻断渲染
        logger.warning("corpus broll 解析失败(slot=%r): %s", slot, exc)
        return None


async def _render_one_frame(
    plan: FramePlan,
    html_path: Path,
    mp4_out: Path,
    *,
    width: int,
    height: int,
    fps: int,
    palette: str,
) -> float:
    """渲染一镜:写 HTML(含可选背景视频)→ 录屏 → 精确时长。返回帧时长。"""
    broll_src: str | None = None
    if plan.broll:
        # 语料库检索 B-roll:"corpus:<槽描述>" → 从本地素材语料库选最佳片段。
        if isinstance(plan.broll, str) and plan.broll.startswith("corpus:"):
            slot = plan.broll[len("corpus:"):].strip()
            hit = _resolve_corpus_broll(slot)
            if hit is None:
                logger.warning("语料库无匹配片段(slot=%r),该帧无背景", slot)
            else:
                plan = FramePlan(
                    kind=plan.kind, title=plan.title, body=plan.body,
                    data=plan.data, broll=hit, duration=plan.duration,
                )
        # 把背景视频复制到帧目录同侧,HTML 用相对名(file:// 下最稳)。
        broll_path = plan.broll or ""
        broll_file = Path(broll_path)
        if broll_file.exists():
            target = html_path.parent / f"{html_path.stem}_broll{broll_file.suffix}"
            shutil.copy2(broll_file, target)
            broll_src = target.name
        else:
            logger.warning("broll 不存在,跳过: %s", plan.broll)

    html_doc = render_frame_html(
        plan, width=width, height=height, palette=palette,
        frame_duration=plan.duration, broll=broll_src,
    )
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(html_doc, encoding="utf-8")

    tmp_mp4 = mp4_out.with_suffix(".raw.mp4")
    await record_html_to_video(
        html_path,
        tmp_mp4,
        width=width,
        height=height,
        fps=fps,
        duration_s=plan.duration,
        scroll=False,  # 单屏动画帧,不滚动
    )
    _trim_to_exact(tmp_mp4, mp4_out, plan.duration, fps)
    tmp_mp4.unlink(missing_ok=True)
    return plan.duration


def _concat_frames(frame_mp4s: list[Path], output: Path, *, fps: int) -> Path:
    """concat filter 统一重编码拼接(混合/同源都安全)。"""
    inputs: list[str] = []
    for p in frame_mp4s:
        inputs += ["-i", str(p)]
    n = len(frame_mp4s)
    filter_expr = "".join(f"[{i}:v]" for i in range(n)) + f"concat=n={n}:v=1:a=0[v]"
    _ffmpeg(
        [*inputs, "-filter_complex", filter_expr, "-map", "[v]",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-r", str(fps), "-movflags", "+faststart",
         str(output)],
        timeout=1800,
    )
    return output


async def render_frames(
    plans: list[FramePlan],
    output_path: Path,
    *,
    width: int = 1280,
    height: int = 720,
    fps: int = 30,
    palette: str = "deep",
    on_step: ProgressFn | None = None,
) -> Path:
    """分镜计划 → 逐帧录屏 → concat 成片。返回最终 mp4 路径。

    逐帧串行录制(Playwright record_video_dir 同名目录会冲突,串行最稳)。
    """
    if not plans:
        raise ValueError("plans 为空,没有可渲染的镜头")
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames_dir = out.parent / "_freevideo_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    frame_mp4s: list[Path] = []
    total = len(plans)
    for i, plan in enumerate(plans):
        base = f"{i + 1:02d}_{plan.kind}"
        html_path = frames_dir / f"{base}.html"
        mp4_out = frames_dir / f"{base}.mp4"
        _step(on_step, f"record {i + 1}/{total} [{plan.kind}]", (i / total) * 90)
        await _render_one_frame(
            plan, html_path, mp4_out,
            width=width, height=height, fps=fps, palette=palette,
        )
        if not mp4_out.exists() or mp4_out.stat().st_size == 0:
            raise RuntimeError(f"帧 {i + 1} 渲染失败: {mp4_out}")
        frame_mp4s.append(mp4_out)

    _step(on_step, "concat", 95)
    _concat_frames(frame_mp4s, out, fps=fps)
    _step(on_step, "done", 100)
    return out


__all__ = ["_ffmpeg", "render_frames"]
