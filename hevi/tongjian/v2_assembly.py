"""通鉴 V2 跨栈装配(SPEC-005-V2 固化,2026-07-24)。

把讲解段(qwen-image 写实静帧 clip)和演绎段(produce_v2 写实视频)按叙事序拼成一集。

★ 音频归一是硬要求(2026-07-24 实证):produce_v2 的成片音轨是坏 AAC(band 超限),直接
`-c copy` 拼接会 PTS 断裂 → 成片时长虚长(报 109.5s 实为 64.5s)、进度条不可 seek,污染一切人眼审看。
所以**拼接前把每个 clip 都重编码归一**(h264 yuv420p w×h@fps CFR + aac 44100 立体声,容错解码修
坏音轨),再 `-c copy` 拼接(此时所有 clip 同参数,拼接结果可 seek)。
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _normalize(src: Path, dst: Path, w: int, h: int, fps: int) -> None:
    """归一到 h264 yuv420p w×h@fps CFR + aac 44100 立体声;`-err_detect ignore_err` 容错解坏音轨。"""
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-err_detect",
            "ignore_err",
            "-i",
            str(src),
            "-vf",
            f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-r",
            str(fps),
            "-vsync",
            "cfr",
            "-c:a",
            "aac",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-b:a",
            "128k",
            str(dst),
        ],
        check=True,
    )


def assemble_episode(
    *, clips: list[Path], output_path: Path, width: int = 720, height: int = 1280, fps: int = 24
) -> Path:
    """按 `clips` 顺序(叙事序:讲解/演绎交错)拼成一集成片。先逐 clip 归一(修坏音轨 + 统一参数),
    再 `-c copy` 拼接(可 seek)。返回成片路径。"""
    if not clips:
        raise ValueError("clips 为空,无法装配")
    norm_dir = output_path.parent / "_norm"
    norm_dir.mkdir(parents=True, exist_ok=True)
    normed: list[Path] = []
    for i, c in enumerate(clips):
        d = norm_dir / f"{i:03d}.mp4"
        _normalize(Path(c), d, width, height, fps)
        normed.append(d)

    concat = output_path.parent / f"{output_path.stem}_concat.txt"
    concat.write_text("".join(f"file '{c.resolve()}'\n" for c in normed))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-c",
            "copy",
            str(output_path),
        ],
        check=True,
    )
    return output_path
