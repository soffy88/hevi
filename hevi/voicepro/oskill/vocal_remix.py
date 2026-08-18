"""人声分离规划 + 配音盖回伴奏床。

组合: `choose_strategy` + `plan_mix` + `demucs_separate_args`。
3O 归属(待上游): `oskill.vocal_remix`。
"""

from __future__ import annotations

from pathlib import Path

from hevi.voicepro.oprim.mix_levels import (
    DEFAULT_BED_DB,
    DEFAULT_VOCAL_DB,
    demucs_separate_args,
    ffmpeg_remix_args,
    ffmpeg_replace_args,
    plan_mix,
)
from hevi.voicepro.schemas import MixPlan


def plan_vocal_remix(
    *,
    keep_bed: bool,
    bed_path: Path | str | None = None,
    bed_from_video: bool = False,
    vocal_gain_db: float = DEFAULT_VOCAL_DB,
    bed_gain_db: float = DEFAULT_BED_DB,
) -> MixPlan:
    has_bed = bool(bed_path) or (keep_bed and bed_from_video)
    return plan_mix(
        has_bed=has_bed,
        vocal_gain_db=vocal_gain_db,
        bed_gain_db=bed_gain_db,
        bed_from_video=keep_bed and not bed_path,
    )


def mux_args_for_plan(
    plan: MixPlan,
    *,
    video: Path | str,
    audio: Path | str,
    output: Path | str,
    bed: Path | str | None = None,
) -> list[str]:
    if plan.strategy == "replace":
        return ffmpeg_replace_args(video=video, audio=audio, output=output)
    return ffmpeg_remix_args(
        video=video,
        audio=audio,
        output=output,
        bed=bed,
        vocal_gain_db=plan.vocal_gain_db,
        bed_gain_db=plan.bed_gain_db,
    )


def stem_split_command(
    input_path: Path | str,
    output_dir: Path | str,
    *,
    model: str = "htdemucs",
) -> list[str]:
    return demucs_separate_args(input_path=input_path, output_dir=output_dir, model=model)
