"""默认 mux:把配音音轨替换进成片(纯 ffmpeg,复用 obase.ffmpeg)。"""

from __future__ import annotations

from pathlib import Path


async def mux_audio_into_video(*, video: Path, audio: Path, output: Path) -> Path:
    """video 的画面 + audio 的配音 → output(video copy,audio aac,-shortest)。"""
    from obase.ffmpeg import run as ffmpeg_run

    output.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        str(output),
    ]
    await ffmpeg_run(args=args, expected_output=output)
    return output
