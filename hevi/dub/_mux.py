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


async def mux_remix_into_video(
    *,
    video: Path,
    audio: Path,
    output: Path,
    bed: Path | None = None,
    vocal_gain_db: float | None = None,
    bed_gain_db: float | None = None,
) -> Path:
    """新配音盖回原片音频或独立伴奏床(Voice-Pro Demucs mix-back)。"""
    from obase.ffmpeg import run as ffmpeg_run

    from hevi.voicepro.oskill.vocal_remix import mux_args_for_plan, plan_vocal_remix

    output.parent.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, float] = {}
    if vocal_gain_db is not None:
        kwargs["vocal_gain_db"] = vocal_gain_db
    if bed_gain_db is not None:
        kwargs["bed_gain_db"] = bed_gain_db
    plan = plan_vocal_remix(
        keep_bed=True,
        bed_path=bed,
        bed_from_video=bed is None,
        **kwargs,
    )
    args = mux_args_for_plan(plan, video=video, audio=audio, output=output, bed=bed)
    await ffmpeg_run(args=args, expected_output=output)
    return output
