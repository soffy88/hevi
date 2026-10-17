"""SPEC-007 批1 ②:跨段 RGB 增益色彩匹配。

独立于 `assembler.py::assemble_longvideo` 的 `color_normalize`(亮度专用,`eq=brightness=`,
往全片平均值方向做 ±0.15 有界修正)——这里做的是**跨 provider 系统性色偏**(整体偏黄/偏蓝
这类割裂感),不是同一批素材内部的亮度抖动,两者是正交问题,不要合并成一个开关。

用法:以某一段(通常是链式生成的首段,身份/画风最稳)为基准,量各段中间帧 RGB 均值,
算增益系数往基准靠,`eq=gamma_r/g/b` 补偿。**诚实边界**:这是均值级别的粗匹配,解决"一段
明显偏黄一段明显偏蓝"这种粗粒度割裂感,解决不了精细的光影质感差异——不是专业调色软件的
分区域/分层次匹配。产出已校色的 clip 文件,喂给 `assemble_longvideo(color_normalize=False,
...)`,避免跟它自己的亮度归一叠加校正。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from obase.ffmpeg import run as ffmpeg_run

_DEFAULT_GAIN_CLAMP = (0.7, 1.4)


def frame_rgb_mean(frame: Path) -> tuple[float, float, float]:
    import numpy as np
    from PIL import Image

    arr = np.array(Image.open(frame).convert("RGB")).reshape(-1, 3)
    m = arr.mean(axis=0)
    return float(m[0]), float(m[1]), float(m[2])


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


async def _extract_mid_frame(clip: Path, out: Path) -> None:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(clip),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    dur = float(stdout.decode().strip() or 0.0)
    await ffmpeg_run(
        args=["-y", "-ss", f"{dur / 2:.3f}", "-i", str(clip), "-vframes", "1", str(out)],
        expected_output=out,
    )


async def match_color_to_reference(
    clip: Path,
    ref_mean: tuple[float, float, float],
    out: Path,
    *,
    gain_clamp: tuple[float, float] = _DEFAULT_GAIN_CLAMP,
) -> dict:
    """把 `clip` 的整体色调往 `ref_mean`(基准段 RGB 均值)靠,产出校色后的 `out`。

    返回 `{"cur_mean": (r,g,b), "gain": (gr,gg,gb)}`——`cur_mean` 是校正前的均值,`gain`
    是实际用上的(已 clamp)增益系数,方便上层判断"这段是不是被 clamp 到边界了"(触边界
    说明原始色差太大,均值级校正没能完全拉平,是一个需要人工复核的信号,不是静默接受)。
    """
    lo, hi = gain_clamp
    mid_frame = out.with_name(f"_color_mid_{clip.stem}.png")
    await _extract_mid_frame(clip, mid_frame)
    cur_mean = frame_rgb_mean(mid_frame)
    gain = tuple(_clamp(ref_mean[i] / max(cur_mean[i], 1.0), lo, hi) for i in range(3))
    await ffmpeg_run(
        args=[
            "-y",
            "-i",
            str(clip),
            "-vf",
            f"eq=gamma_r={gain[0]:.3f}:gamma_g={gain[1]:.3f}:gamma_b={gain[2]:.3f}",
            "-c:a",
            "copy",
            str(out),
        ],
        expected_output=out,
    )
    return {"cur_mean": cur_mean, "gain": gain}
