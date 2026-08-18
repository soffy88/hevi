"""把一镜视觉描述拆成首帧 / 末帧 / 运动。

组合: `classify_variation` + `needs_last_frame`。
3O 归属(待上游): `oskill.shot_decompose`。
"""

from __future__ import annotations

from hevi.script2video.oprim.variation import classify_variation, needs_last_frame
from hevi.script2video.schemas import KernelShot, ShotVisualPlan, VariationType


def decompose_shot_visual(shot: KernelShot) -> ShotVisualPlan:
    """确定性拆解:首帧=建立态,末帧=动作落地,运动=beats 或视觉描述。"""
    ff_desc = _first_frame_desc(shot)
    lf_desc = _last_frame_desc(shot, ff_desc)
    motion = _motion_desc(shot)
    variation, reason = classify_variation(
        shot.visual_desc,
        ff_desc=ff_desc,
        lf_desc=lf_desc,
        action_beats=shot.action_beats,
    )
    char_idxs = list(range(len(shot.visible_chars)))
    lf_chars = char_idxs
    if variation == "small":
        lf_desc = ff_desc
    return ShotVisualPlan(
        idx=shot.idx,
        visual_desc=shot.visual_desc,
        ff_desc=ff_desc,
        lf_desc=lf_desc,
        motion_desc=motion,
        variation_type=variation,
        variation_reason=reason,
        ff_vis_char_idxs=char_idxs,
        lf_vis_char_idxs=lf_chars,
        audio_desc=shot.audio_desc,
        cam_idx=shot.cam_idx,
    )


def decompose_all_shots(shots: list[KernelShot]) -> list[ShotVisualPlan]:
    return [decompose_shot_visual(shot) for shot in shots]


def last_frame_required(variation_type: VariationType) -> bool:
    return needs_last_frame(variation_type)


def _first_frame_desc(shot: KernelShot) -> str:
    if shot.action_beats:
        trigger = shot.action_beats[0]
        return f"{shot.visual_desc} Initial state: {trigger}."
    return shot.visual_desc


def _last_frame_desc(shot: KernelShot, ff_desc: str) -> str:
    if len(shot.action_beats) >= 2:
        aftermath = shot.action_beats[-1]
        return f"{shot.visual_desc} Final state: {aftermath}."
    return ff_desc


def _motion_desc(shot: KernelShot) -> str:
    if shot.action_beats:
        return " → ".join(shot.action_beats)
    return shot.visual_desc
