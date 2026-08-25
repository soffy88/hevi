"""人声 / 伴奏床电平和 ffmpeg 混音参数。

对齐 Voice-Pro Demucs 分轨后再把新配音盖回 inst 床。
3O 归属(待上游): `oprim.mix_levels`。
"""

from __future__ import annotations

from pathlib import Path

from hevi.voicepro.schemas import MixPlan, MixStrategyName

DEFAULT_BED_DB = -8.0
DEFAULT_VOCAL_DB = 0.0


def db_to_linear(gain_db: float) -> float:
    return float(10.0 ** (float(gain_db) / 20.0))


def choose_strategy(*, has_bed: bool) -> MixStrategyName:
    return "remix" if has_bed else "replace"


def remix_filter(
    *,
    vocal_gain_db: float = DEFAULT_VOCAL_DB,
    bed_gain_db: float = DEFAULT_BED_DB,
    bed_from_video: bool = False,
) -> str:
    """filter_complex:新配音 + 伴奏床 amix,时长跟配音。"""
    vocal = db_to_linear(vocal_gain_db)
    bed = db_to_linear(bed_gain_db)
    if bed_from_video:
        return (
            f"[0:a]volume={bed:.4f}[b];[1:a]volume={vocal:.4f}[v];"
            "[v][b]amix=inputs=2:duration=first:dropout_transition=2[a]"
        )
    return (
        f"[1:a]volume={vocal:.4f}[v];[2:a]volume={bed:.4f}[b];"
        "[v][b]amix=inputs=2:duration=first:dropout_transition=2[a]"
    )


def plan_mix(
    *,
    has_bed: bool,
    vocal_gain_db: float = DEFAULT_VOCAL_DB,
    bed_gain_db: float = DEFAULT_BED_DB,
    bed_from_video: bool = False,
) -> MixPlan:
    strategy = choose_strategy(has_bed=has_bed or bed_from_video)
    filt = ""
    if strategy == "remix":
        filt = remix_filter(
            vocal_gain_db=vocal_gain_db,
            bed_gain_db=bed_gain_db,
            bed_from_video=bed_from_video and not has_bed,
        )
    return MixPlan(
        strategy=strategy,
        vocal_gain_db=vocal_gain_db,
        bed_gain_db=bed_gain_db,
        filter_complex=filt,
    )


def ffmpeg_replace_args(*, video: Path | str, audio: Path | str, output: Path | str) -> list[str]:
    return [
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


def ffmpeg_remix_args(
    *,
    video: Path | str,
    audio: Path | str,
    output: Path | str,
    bed: Path | str | None = None,
    vocal_gain_db: float = DEFAULT_VOCAL_DB,
    bed_gain_db: float = DEFAULT_BED_DB,
) -> list[str]:
    if bed is None:
        filt = remix_filter(
            vocal_gain_db=vocal_gain_db,
            bed_gain_db=bed_gain_db,
            bed_from_video=True,
        )
        return [
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-filter_complex",
            filt,
            "-map",
            "0:v",
            "-map",
            "[a]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            str(output),
        ]
    filt = remix_filter(vocal_gain_db=vocal_gain_db, bed_gain_db=bed_gain_db, bed_from_video=False)
    return [
        "-y",
        "-i",
        str(video),
        "-i",
        str(audio),
        "-i",
        str(bed),
        "-filter_complex",
        filt,
        "-map",
        "0:v",
        "-map",
        "[a]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-shortest",
        str(output),
    ]


def demucs_separate_args(
    *,
    input_path: Path | str,
    output_dir: Path | str,
    model: str = "htdemucs",
) -> list[str]:
    """构造 `python -m demucs.separate` 参数(两茎 vocals)。不执行。"""
    return [
        "-m",
        "demucs.separate",
        "-n",
        model,
        "--two-stems=vocals",
        "--float32",
        "-o",
        str(output_dir),
        str(input_path),
    ]
