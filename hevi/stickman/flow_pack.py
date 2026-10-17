"""stickman.flow_pack —— Flow 任务包导出器。

规格：
1. 按分镜切分导出 Flow 任务包（每条 ≤10 秒提示词）。
2. 带画风锁定段（Character DNA Anchor）、模型 Omni Flash、720P、顺序号、预估积分 15/条。
3. 导出 JSON（flow_task_pack.json）与 TXT（flow_prompts.txt）。
4. 记录积分台账消耗。
5. 必须处于 approved 状态，未批准直接拦截。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hevi.stickman.proposal import DirectorProposal, StoryboardScene
from hevi.stickman.credits_ledger import CreditsLedger, CREDITS_PER_CLIP


# 风格 1 与 风格 2 的上游画风锁定段 (Vendored from third_party/stickman_director)
STYLE_1_LIGHT_DNA = (
    "A minimalist 2D animated stick figure on a digitally pure-white background. "
    "Its head is a crisp black circular outline surrounding an entirely white, empty interior. "
    "Its torso is a single black line, with two black line arms and two black line legs. "
    "All five body lines remain firmly connected during movement with uniform stroke thickness. "
    "Preserve this exact minimalist line drawing throughout: no filled head, no facial marks, "
    "no body silhouette, no shaded limbs, no 3D depth."
)

STYLE_2_BEANIE_DNA = (
    "A minimalist 2D animated stick figure wearing a bright red beanie (smooth rounded knit, "
    "strictly no pom-pom) and a vibrant yellow t-shirt, with simple black stick limbs and shorts. "
    "Simple crisp black lines, vibrant solid colors, smooth 2D animation style. "
    "No realistic facial features, no detailed pupils or realistic contours."
)


def build_flow_prompt_for_scene(
    scene: StoryboardScene,
    proposal: DirectorProposal,
    total_clips: int,
) -> str:
    """构建单镜符合 Omni Flash 契约的完整提示词。"""
    aspect = proposal.aspect_ratio
    res_str = "1280x720 (16:9)" if aspect == "16:9" else "720x1280 (9:16)"
    
    # 1. 输出规格
    sec1 = (
        f"OUTPUT SPECIFICATION: 10 seconds duration, {res_str}, target 720p, 24 FPS, "
        f"synchronized narrative audio. Model target: Omni Flash."
    )

    # 2. 视觉环境与背景
    if proposal.art_style == "color_story":
        sec2 = (
            "ENVIRONMENT & BACKGROUND: Clean minimalist studio environment with subtle warm-light "
            "reflections, crisp uncluttered negative space, high-key lighting."
        )
        dna_lock = STYLE_2_BEANIE_DNA
    else:
        sec2 = (
            "ENVIRONMENT & BACKGROUND: Flat, digitally pure-white canvas. Strictly forbid gray tint, "
            "paper texture, gradients, shadows, lighting, bloom, fog, or 3D depth."
        )
        dna_lock = STYLE_1_LIGHT_DNA

    # 3. 角色锁
    sec3 = f"CHARACTER DNA LOCK: {dna_lock}"

    # 4. 色彩契约
    colors_str = ", ".join(f"{k}: {v}" for k, v in proposal.color_palette.items())
    sec4 = f"PALETTE CONTRACT: {colors_str}."

    # 5. 首帧与尾帧连续性
    first_frame = scene.first_frame_state or f"Inherit state from clip {scene.scene_index - 1}"
    last_frame = scene.last_frame_state or f"Lead transition smoothly into clip {scene.scene_index + 1}"
    sec5 = (
        f"CONTINUITY STATE: First frame inherits: {first_frame}. "
        f"Final frame settles into: {last_frame}."
    )

    # 6. 时间轴视觉节拍 (Timed visual sequence)
    beats_text = " -> ".join(scene.visual_beats)
    sec6 = f"TIMED ACTION SEQUENCE: {beats_text}"

    # 7. 旁白对白
    dialogue_zh = scene.narration_zh.replace('"', '\\"')
    dialogue_en = scene.narration_en.replace('"', '\\"') if scene.narration_en else ""
    sec7 = f'AUDIO SPOKEN DIALOGUE: "{dialogue_zh}" (English reference: "{dialogue_en}"). Audio-only VO, strictly NO speech bubbles or subtitle text boxes.'

    # 8. 声线与音频
    vo = proposal.voiceover
    sec8 = (
        f"VOICE PROFILE: {vo.get('profile', 'Analytical Explainer')}, "
        f"steady clear pace ~{vo.get('pace_wpm', 135)} WPM, neutral studio acoustics. "
        f"BGM: {proposal.bgm_style}, voice-first audio mix with subtle whoosh / ding SFX."
    )

    # 9. 负向提示词约束
    sec9 = (
        "NEGATIVE CONSTRAINTS: Avoid 3D CGI rendering, photorealism, erratic line jitters, "
        "pom-poms on head, detached limbs, morphing liquid objects, speech bubbles, blurry artifacts."
    )

    prompt_parts = [
        f"--- [Clip {scene.scene_index}/{total_clips}] ---",
        sec1,
        sec2,
        sec3,
        sec4,
        sec5,
        sec6,
        sec7,
        sec8,
        sec9,
    ]
    return "\n\n".join(prompt_parts)


def export_flow_pack(
    proposal: DirectorProposal,
    out_dir: str | Path,
    *,
    ledger: CreditsLedger | None = None,
) -> dict[str, Any]:
    """按分镜导出 Flow 任务包（JSON + TXT）。

    必须处于 approved 状态，否则拦截。
    """
    proposal.assert_can_generate_prompts()

    pack_dir = Path(out_dir)
    pack_dir.mkdir(parents=True, exist_ok=True)

    scenes = proposal.storyboard
    total_clips = len(scenes)

    clips_data = []
    prompts_text_list = []

    for scene in scenes:
        seq = scene.scene_index
        prompt_text = build_flow_prompt_for_scene(scene, proposal, total_clips)
        prompts_text_list.append(prompt_text)

        clip_item = {
            "sequence_index": seq,
            "scene_stage": scene.stage,
            "target_duration_s": scene.duration_s,
            "model": "Omni Flash",
            "resolution": "720P",
            "aspect_ratio": proposal.aspect_ratio,
            "art_style": proposal.art_style,
            "estimated_credits": CREDITS_PER_CLIP,
            "narration_zh": scene.narration_zh,
            "narration_en": scene.narration_en,
            "prompt": prompt_text,
        }
        clips_data.append(clip_item)

    # 导出 JSON 任务包
    pack_json = {
        "proposal_id": proposal.proposal_id,
        "title": proposal.title,
        "topic": proposal.topic,
        "total_clips": total_clips,
        "total_duration_s": proposal.total_duration,
        "total_estimated_credits": total_clips * CREDITS_PER_CLIP,
        "model_spec": {
            "model_name": "Omni Flash",
            "resolution": "720P",
            "aspect_ratio": proposal.aspect_ratio,
        },
        "art_style": proposal.art_style,
        "clips": clips_data,
        "google_policy": "NO_GOOGLE_AUTO_LOGIN_NO_REMOTE_FLOW_API",
    }

    json_path = pack_dir / "flow_task_pack.json"
    json_path.write_text(json.dumps(pack_json, indent=2, ensure_ascii=False), encoding="utf-8")

    # 导出 TXT 提示词包
    txt_path = pack_dir / "flow_prompts.txt"
    full_txt = f"# Flow Prompts Pack - {proposal.title}\n"
    full_txt += f"# Total Clips: {total_clips} | Estimated Credits: {total_clips * CREDITS_PER_CLIP}\n\n"
    full_txt += "\n\n" + ("=" * 60) + "\n\n".join(prompts_text_list) + "\n"
    txt_path.write_text(full_txt, encoding="utf-8")

    # 积分台账记录
    ledger_receipt = None
    if ledger is not None:
        ledger_receipt = ledger.record_consumption(
            proposal_id=proposal.proposal_id,
            clip_count=total_clips,
            note=f"Export Flow pack for '{proposal.title}'",
        )

    return {
        "pack_dir": str(pack_dir),
        "json_path": str(json_path),
        "txt_path": str(txt_path),
        "total_clips": total_clips,
        "total_estimated_credits": total_clips * CREDITS_PER_CLIP,
        "ledger_receipt": ledger_receipt,
    }
