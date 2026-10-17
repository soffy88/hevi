"""timeline_view — 决策点 filmstrip + 可选波形（对标 video-use Layer 2）。

只在决策点调用，不是扫描工具。依赖 ffmpeg；失败返回结构化错误而非静默。
"""

from __future__ import annotations

import logging
import math
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class TimelineViewResult:
    path: Path
    start: float
    end: float
    tile_count: int
    mode: str  # filmstrip | waveform | composite


def _probe_duration(path: Path) -> float:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr}")
    return float(proc.stdout.strip() or 0)


def timeline_view(
    video: Path,
    start: float,
    end: float,
    output: Path,
    *,
    tiles: int = 8,
    tile_width: int = 160,
    tile_height: int = 90,
    include_waveform: bool = True,
) -> TimelineViewResult:
    """生成 [start,end) 时间窗的 filmstrip（可选底部波形）。

    实现：均匀抽 N 帧 → hstack；若 include_waveform 再 vstack 一条 showwaves 条带。
    """
    if end <= start:
        raise ValueError(f"invalid window start={start} end={end}")
    if not video.exists():
        raise FileNotFoundError(video)

    dur = end - start
    tiles = max(2, min(24, int(tiles)))
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="tlview_") as td:
        tdir = Path(td)
        # 抽帧
        frame_paths: list[Path] = []
        for i in range(tiles):
            t = start + (i + 0.5) * dur / tiles
            fp = tdir / f"f{i:02d}.jpg"
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{t:.3f}",
                    "-i",
                    str(video),
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale={tile_width}:{tile_height}:force_original_aspect_ratio=decrease,"
                    f"pad={tile_width}:{tile_height}:(ow-iw)/2:(oh-ih)/2",
                    "-q:v",
                    "3",
                    str(fp),
                ],
                capture_output=True,
                timeout=60,
            )
            if proc.returncode != 0 or not fp.exists():
                logger.warning("tile %d failed at t=%.3f", i, t)
                continue
            frame_paths.append(fp)

        if not frame_paths:
            raise RuntimeError("timeline_view: no frames extracted")

        strip = tdir / "strip.jpg"
        if len(frame_paths) == 1:
            strip.write_bytes(frame_paths[0].read_bytes())
        else:
            # hstack
            n = len(frame_paths)
            inputs: list[str] = []
            for fp in frame_paths:
                inputs.extend(["-i", str(fp)])
            filt = "".join(f"[{i}:v]" for i in range(n)) + f"hstack=inputs={n}[v]"
            proc = subprocess.run(
                ["ffmpeg", "-y", *inputs, "-filter_complex", filt, "-map", "[v]", str(strip)],
                capture_output=True,
                timeout=60,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"hstack failed: {proc.stderr[-500:]!r}")

        mode = "filmstrip"
        final_src = strip

        if include_waveform:
            wave = tdir / "wave.png"
            # 截取时间窗音频画波形
            w = tile_width * len(frame_paths)
            proc = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{start:.3f}",
                    "-t",
                    f"{dur:.3f}",
                    "-i",
                    str(video),
                    "-filter_complex",
                    f"[0:a]showwavespic=s={w}x64:colors=0x4ade80[w]",
                    "-map",
                    "[w]",
                    "-frames:v",
                    "1",
                    str(wave),
                ],
                capture_output=True,
                timeout=60,
            )
            if proc.returncode == 0 and wave.exists():
                comp = tdir / "comp.jpg"
                proc2 = subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-i",
                        str(strip),
                        "-i",
                        str(wave),
                        "-filter_complex",
                        "[0:v][1:v]vstack=inputs=2[v]",
                        "-map",
                        "[v]",
                        str(comp),
                    ],
                    capture_output=True,
                    timeout=60,
                )
                if proc2.returncode == 0 and comp.exists():
                    final_src = comp
                    mode = "composite"
                else:
                    mode = "filmstrip"
            else:
                logger.debug("waveform skipped: %s", proc.stderr[-200:] if proc.stderr else "")

        output.write_bytes(final_src.read_bytes())

    return TimelineViewResult(
        path=output,
        start=start,
        end=end,
        tile_count=len(frame_paths),
        mode=mode,
    )


def timeline_views_at_cuts(
    video: Path,
    cut_times: list[float],
    out_dir: Path,
    *,
    window_s: float = 1.5,
    tiles: int = 6,
) -> list[TimelineViewResult]:
    """在每个 cut 时间点 ±window 生成 timeline 视图。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        total = _probe_duration(video)
    except Exception:
        total = max(cut_times) + window_s if cut_times else 0.0

    results: list[TimelineViewResult] = []
    for i, t in enumerate(cut_times):
        s = max(0.0, t - window_s)
        e = min(total, t + window_s) if total > 0 else t + window_s
        if e <= s:
            continue
        out = out_dir / f"cut_{i:02d}_{t:.2f}s.jpg"
        try:
            results.append(
                timeline_view(video, s, e, out, tiles=tiles, include_waveform=True)
            )
        except Exception as ex:
            logger.warning("timeline at cut %.2f failed: %s", t, ex)
    return results


def cut_times_from_ranges(ranges: list[Any]) -> list[float]:
    """EDL ranges → 内部 cut 时间点（累计输出时间轴）。"""
    cuts: list[float] = []
    t = 0.0
    for r in ranges[:-1]:
        dur = float(r.end - r.start) if hasattr(r, "end") else float(r["end"] - r["start"])
        t += dur
        cuts.append(t)
    return cuts


# ── 增强：词级标注 + 说话人分段 ────────────────────────────────────


@dataclass
class WordLabelOverlay:
    """词级标注叠加层（在 filmstrip 上显示词文本 + 时间）。"""

    word: str
    start: float
    end: float
    speaker: str = ""
    x_ratio: float = 0.0  # 在 timeline 中的水平位置 0-1

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


def compute_word_labels(
    words: list[Any],
    window_start: float,
    window_end: float,
) -> list[WordLabelOverlay]:
    """计算时间窗内的词标注位置。

    Args:
        words: ScribeWord 或 Word 列表（需有 .word, .start, .end 属性）
        window_start: 时间窗起始
        window_end: 时间窗结束
    """
    dur = window_end - window_start
    if dur <= 0:
        return []

    labels: list[WordLabelOverlay] = []
    for w in words:
        word_text = getattr(w, "word", "")
        w_start = getattr(w, "start", 0.0)
        w_end = getattr(w, "end", 0.0)
        w_speaker = getattr(w, "speaker", "")

        if w_end < window_start or w_start > window_end:
            continue

        # 水平位置 = (word_start - window_start) / dur
        x_ratio = max(0.0, min(1.0, (w_start - window_start) / dur))
        labels.append(WordLabelOverlay(
            word=word_text,
            start=w_start,
            end=w_end,
            speaker=w_speaker,
            x_ratio=x_ratio,
        ))
    return labels


def build_word_label_image(
    labels: list[WordLabelOverlay],
    width: int,
    height: int,
    output: Path,
) -> Path | None:
    """将词标注渲染为 PNG 叠加层（需要 PIL）。

    返回生成的图片路径，失败返回 None。
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.debug("PIL not available, skipping word label image")
        return None

    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14
        )
    except (OSError, IOError):
        font = ImageFont.load_default()

    for label in labels:
        x = int(label.x_ratio * width)
        # 说话人颜色区分
        colors = [
            (74, 222, 128),   # green for SPEAKER_00
            (96, 165, 250),   # blue for SPEAKER_01
            (251, 191, 36),   # amber for others
        ]
        color_idx = 0
        if label.speaker:
            try:
                color_idx = int(label.speaker.split("_")[-1]) % len(colors)
            except (ValueError, IndexError):
                color_idx = 2
        color = colors[color_idx]

        # 绘制词文本
        text = label.word
        if label.speaker:
            text = f"[{label.speaker}] {text}"
        draw.text((x, 2), text, fill=(*color, 220), font=font)

        # 绘制时间线
        draw.line([(x, height - 4), (x, height)], fill=(*color, 150), width=1)

    output.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output))
    return output


def timeline_view_with_words(
    video: Path,
    start: float,
    end: float,
    output: Path,
    *,
    words: list[Any] | None = None,
    tiles: int = 8,
    tile_width: int = 160,
    tile_height: int = 90,
    include_waveform: bool = True,
    include_word_labels: bool = True,
) -> TimelineViewResult:
    """增强版 timeline_view：filmstrip + 波形 + 词级标注。"""
    # 先生成基础 filmstrip + waveform
    result = timeline_view(
        video, start, end, output,
        tiles=tiles,
        tile_width=tile_width,
        tile_height=tile_height,
        include_waveform=include_waveform,
    )

    # 叠加词标注
    if include_word_labels and words:
        labels = compute_word_labels(words, start, end)
        if labels:
            total_w = tile_width * min(len(labels), tiles)
            label_h = 30
            label_path = output.parent / f"{output.stem}_labels.png"
            built = build_word_label_image(labels, total_w, label_h, label_path)
            if built:
                # vstack: labels + filmstrip
                comp = output.parent / f"{output.stem}_full.jpg"
                proc = subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", str(label_path),
                        "-i", str(result.path),
                        "-filter_complex",
                        "[0:v][1:v]vstack=inputs=2[v]",
                        "-map", "[v]",
                        str(comp),
                    ],
                    capture_output=True,
                    timeout=60,
                )
                if proc.returncode == 0 and comp.exists():
                    import shutil
                    shutil.move(str(comp), str(output))
                    result.mode = "enhanced"

    return result


def timeline_summary_text(
    ranges: list[Any],
    *,
    words: list[Any] | None = None,
    grade: str = "none",
) -> str:
    """生成文本格式的 timeline 摘要（无需 ffmpeg，纯文本）。"""
    lines: list[str] = ["═══ Timeline Summary ═══"]
    total = 0.0

    for i, r in enumerate(ranges):
        if hasattr(r, "start"):
            s, e = r.start, r.end
            beat = getattr(r, "beat", "")
            quote = getattr(r, "quote", "")
        else:
            s, e = r["start"], r["end"]
            beat = r.get("beat", "")
            quote = r.get("quote", "")

        dur = e - s
        lines.append(f"  [{i:02d}] {total:.2f}s – {total + dur:.2f}s ({dur:.2f}s)")
        if beat:
            lines.append(f"        beat: {beat}")
        if quote:
            lines.append(f"        quote: \"{quote}\"")
        total += dur

    lines.append(f"  ─── Total: {total:.2f}s ({len(ranges)} segments, {max(0, len(ranges)-1)} cuts)")

    if grade and grade != "none":
        lines.append(f"  Grade: {grade}")

    if words:
        lines.append(f"  Words: {len(words)}")

    return "\n".join(lines)
