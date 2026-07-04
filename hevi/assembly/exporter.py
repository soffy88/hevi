"""成片导出格式转换 —— 装配器固定产出 mp4(h264/aac);这里按需转封装/转码。

mp4 是零成本直传(本就是那个格式);mov 只是换容器(remux,不重编码,快);
webm/gif 需要真转码(vp9/opus、或抽帧调色板),较慢但也是纯 ffmpeg 操作。
"""

from __future__ import annotations

from pathlib import Path

from obase.ffmpeg import run as ffmpeg_run

EXPORT_FORMATS: tuple[str, ...] = ("mp4", "mov", "webm", "gif")


async def export_video(input_path: Path, output_path: Path, fmt: str) -> Path:
    """把装配器产出的 mp4 转成目标格式,写到 output_path。fmt 需在 EXPORT_FORMATS 内。"""
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"unsupported export format: {fmt!r}. valid: {EXPORT_FORMATS}")

    if fmt == "mp4":
        import shutil

        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(input_path, output_path)
        return output_path

    if fmt == "mov":
        # h264/aac 容器兼容 mov,纯换封装,不重编码。
        args = ["-y", "-i", str(input_path), "-c", "copy", str(output_path)]
        await ffmpeg_run(args=args, expected_output=output_path)
        return output_path

    if fmt == "webm":
        args = [
            "-y",
            "-i",
            str(input_path),
            "-c:v",
            "libvpx-vp9",
            "-crf",
            "32",
            "-b:v",
            "0",
            "-c:a",
            "libopus",
            str(output_path),
        ]
        await ffmpeg_run(args=args, expected_output=output_path)
        return output_path

    # gif: 抽帧 + 调色板,常见"预览小动图"导出。
    args = [
        "-y",
        "-i",
        str(input_path),
        "-vf",
        "fps=10,scale=480:-1:flags=lanczos",
        str(output_path),
    ]
    await ffmpeg_run(args=args, expected_output=output_path)
    return output_path


def content_type_for(fmt: str) -> str:
    return {
        "mp4": "video/mp4",
        "mov": "video/quicktime",
        "webm": "video/webm",
        "gif": "image/gif",
    }[fmt]
