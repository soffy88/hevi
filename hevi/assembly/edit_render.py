"""EDL 渲染：per-segment extract → fade → concat → overlays → 字幕 LAST。

硬规则 1–5 在此落地。依赖 ffmpeg；无 GPU。
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path

from hevi.assembly.edit_craft import (
    AUDIO_FADE_S,
    EditCraftError,
    EditDecisionList,
    SubtitleCue,
    build_segment_afade_filter,
    compute_output_duration,
    format_srt,
    overlay_setpts_expr,
    remap_cues_to_output_timeline,
    require_strategy_confirmation,
    validate_edl,
)
from hevi.assembly.subtitle_burner import get_subtitle_filter

logger = logging.getLogger(__name__)


async def _ffmpeg(args: list[str], expected: Path | None = None) -> None:
    from obase.ffmpeg import run as ffmpeg_run

    await ffmpeg_run(args=args, expected_output=expected)


async def extract_segment(
    *,
    source: Path,
    start: float,
    end: float,
    output: Path,
    fade_s: float = AUDIO_FADE_S,
    grade_filter: str | None = None,
) -> Path:
    """从源片截取 [start,end)，加音频 fade，可选调色滤镜。"""
    if end <= start:
        raise EditCraftError(f"extract 非法区间 {start}-{end}")
    dur = end - start
    output.parent.mkdir(parents=True, exist_ok=True)
    af = build_segment_afade_filter(dur, fade_s)
    vf = grade_filter or "null"
    args = [
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(source),
        "-t",
        f"{dur:.3f}",
        "-vf",
        vf,
        "-af",
        af,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output),
    ]
    await _ffmpeg(args, expected=output)
    return output


def _grade_to_vf(grade: str) -> str | None:
    if not grade or grade in ("none", "null"):
        return None
    # 内置少量 preset；完整 LUT 走 enhancement.color_grade
    presets = {
        "warm_cinematic": (
            "eq=brightness=0.02:saturation=0.9,"
            "colorbalance=rs=0.08:gs=0.02:bs=-0.05"
        ),
        "neutral_punch": "eq=contrast=1.08:saturation=1.05",
    }
    return presets.get(grade, grade if "=" in grade else None)


async def concat_segments(segments: list[Path], output: Path) -> Path:
    """lossless-ish concat demuxer（同编码参数下 -c copy；失败则 re-encode）。"""
    if not segments:
        raise EditCraftError("concat 无片段")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as fh:
        list_path = Path(fh.name)
        for p in segments:
            # concat demuxer 需要 escaped path
            esc = str(p.resolve()).replace("'", r"'\''")
            fh.write(f"file '{esc}'\n")
    try:
        try:
            await _ffmpeg(
                [
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(list_path),
                    "-c",
                    "copy",
                    str(output),
                ],
                expected=output,
            )
        except Exception:
            logger.warning("concat -c copy 失败，回退 re-encode")
            await _ffmpeg(
                [
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(list_path),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "18",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    str(output),
                ],
                expected=output,
            )
    finally:
        list_path.unlink(missing_ok=True)
    return output


async def apply_overlays_and_subtitles(
    *,
    base: Path,
    output: Path,
    overlays: list[tuple[Path, float, float]],
    subtitle_path: Path | None = None,
    subtitle_style: str = "default",
) -> Path:
    """叠加 overlays（PTS 偏移），字幕 LAST（规则 1、4）。"""
    output.parent.mkdir(parents=True, exist_ok=True)
    if not overlays and not subtitle_path:
        shutil.copy2(base, output)
        return output

    # 构建 filter 步骤列表，强制字幕在最后
    steps: list[str] = []
    inputs = ["-y", "-i", str(base)]
    last_v = "[0:v]"
    for i, (ov_path, start, dur) in enumerate(overlays):
        inputs.extend(["-i", str(ov_path)])
        idx = i + 1
        pts = overlay_setpts_expr(start)
        steps.append(f"[{idx}:v]{pts},scale=iw:ih[ov{i}]")
        # enable 在输出时间窗内显示
        end = start + dur
        out_lab = f"[v{i}]"
        steps.append(
            f"{last_v}[ov{i}]overlay=0:0:enable='between(t,{start:.3f},{end:.3f})'{out_lab}"
        )
        last_v = out_lab

    filter_steps_named = list(steps)
    if subtitle_path and subtitle_path.exists():
        # 规则 1：字幕最后
        sub_f = get_subtitle_filter(subtitle_path, style=subtitle_style)
        # subtitles filter 需要接到视频标签
        if last_v == "[0:v]":
            filter_steps_named.append(f"[0:v]{sub_f}[vout]")
        else:
            # last_v like [v0]
            lab = last_v.strip("[]")
            filter_steps_named.append(f"[{lab}]{sub_f}[vout]")
        map_v = "[vout]"
    else:
        if last_v == "[0:v]":
            map_v = "0:v"
            filter_complex = None
        else:
            map_v = last_v
            filter_complex = ";".join(filter_steps_named)
            args = inputs + [
                "-filter_complex",
                filter_complex,
                "-map",
                map_v,
                "-map",
                "0:a?",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "copy",
                str(output),
            ]
            await _ffmpeg(args, expected=output)
            return output

    filter_complex = ";".join(filter_steps_named) if filter_steps_named else None
    args = list(inputs)
    if filter_complex:
        args.extend(["-filter_complex", filter_complex, "-map", map_v])
    else:
        args.extend(["-map", "0:v"])
    args.extend(
        [
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(output),
        ]
    )
    await _ffmpeg(args, expected=output)
    return output


async def render_edl(
    edl: EditDecisionList | dict,
    *,
    edit_dir: Path,
    output_name: str = "final.mp4",
    preview: bool = False,
    require_confirm: bool = True,
    source_cues: list[SubtitleCue] | None = None,
) -> Path:
    """完整渲染管线。输出到 edit_dir/output_name。"""
    if isinstance(edl, dict):
        edl = EditDecisionList.from_dict(edl)

    warnings = validate_edl(edl, require_confirm=require_confirm)
    for w in warnings:
        logger.warning("EDL warning: %s", w)

    edit_dir.mkdir(parents=True, exist_ok=True)
    (edit_dir / "edl.json").write_text(
        json.dumps(edl.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    clips_dir = edit_dir / "clips_graded"
    clips_dir.mkdir(exist_ok=True)
    grade_vf = _grade_to_vf(edl.grade)
    if preview and grade_vf:
        grade_vf = f"scale=1280:-2,{grade_vf}"
    elif preview:
        grade_vf = "scale=1280:-2"

    segments: list[Path] = []
    for i, r in enumerate(edl.ranges):
        src = Path(edl.sources[r.source])
        if not src.exists():
            raise EditCraftError(f"源文件不存在: {src}")
        out_seg = clips_dir / f"seg_{i:03d}.mp4"
        await extract_segment(
            source=src,
            start=r.start,
            end=r.end,
            output=out_seg,
            grade_filter=grade_vf,
        )
        segments.append(out_seg)

    concat_path = edit_dir / ("preview_base.mp4" if preview else "master_base.mp4")
    await concat_segments(segments, concat_path)

    # 字幕：源 cues 重映射，或使用 EDL 指定文件
    sub_path: Path | None = None
    if source_cues:
        remapped = remap_cues_to_output_timeline(source_cues, edl.ranges)
        sub_path = edit_dir / "master.srt"
        sub_path.write_text(format_srt(remapped), encoding="utf-8")
    elif edl.subtitles:
        p = Path(edl.subtitles)
        sub_path = p if p.is_absolute() else edit_dir / p
        if not sub_path.exists():
            logger.warning("字幕文件不存在: %s", sub_path)
            sub_path = None

    overlays: list[tuple[Path, float, float]] = []
    for o in edl.overlays:
        op = Path(o.file)
        if not op.is_absolute():
            op = edit_dir / op
        if not op.exists():
            raise EditCraftError(f"overlay 不存在: {op}")
        overlays.append((op, o.start_in_output, o.duration))

    final = edit_dir / output_name
    await apply_overlays_and_subtitles(
        base=concat_path,
        output=final,
        overlays=overlays,
        subtitle_path=sub_path,
    )

    # 回写合计时长
    edl.total_duration_s = compute_output_duration(edl.ranges)
    (edit_dir / "edl.json").write_text(
        json.dumps(edl.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("render_edl done: %s (%.2fs)", final, edl.total_duration_s or 0)
    return final
