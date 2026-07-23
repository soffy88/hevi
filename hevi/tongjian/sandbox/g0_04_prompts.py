#!/usr/bin/env python3
"""G0 Task-4: 提示词 ×3 — 附录 B 模板手工实例化 S1/S2/S3（§15 参数表）

附录 B 模板（来自 HEVI-SPEC-02 §3/§4）：
  [风格锁] [场景] [主体] [动作/状态] [光线/氛围] [镜头语言] [负面提示]

§15 参数表（三家分晋 animated 分支）：
  - production_mode: cinematic / animated
  - render_style: animated（国风动画，G0 首战）
  - art_direction: 水墨质感历史插画，低饱和，烛光/暮色主导
  - denoising_strength: 0.35
  - identity_threshold: 0.60（G0 记录值，A3 标定后调）
  - ocr_check: strict（A2）

输出到 output/g0_sanjia_fenjin/prompts/prompts_s1s2s3.json
同时打印人可读版本供审阅。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

OUT = Path("output/g0_sanjia_fenjin/prompts")
OUT.mkdir(parents=True, exist_ok=True)

# ─── 附录 B 模板实例化规则（不写编译器，手工填参数） ──────────────────────
# 模板字段顺序:
#   [风格锁]  [场景底层]  [主体/角色]  [动作状态]  [光线氛围]  [镜头语言]
#   negative: [负面提示]

# §15 全局参数
GLOBAL_PARAMS = {
    "art_direction": "Chinese ink wash painting, water-ink texture, hand-painted historical illustration",
    "saturation": "low saturation, muted tones",
    "era": "Warring States period China, 453BC, zhanguoce aesthetic",
    "style_lock": "no modern elements, no anime tropes, no bright colors",
    "negative_global": (
        "modern objects, neon, anime style, bright colors, photorealistic human skin, "
        "watermark, text overlay, speech bubble, subtitles, contemporary architecture, "
        "firearms, electronics"
    ),
    "render_style": "animated",
    "production_mode": "cinematic",
    "denoising_strength": 0.35,
    "identity_threshold_g0": 0.60,
}

# 三镜头实例化
PROMPTS = [
    # ─── S1: 智伯宴席索地（权力顶点）─────────────────────────────────────
    {
        "shot_id": "S1",
        "scene_title": "智伯宴席索地 — 权力顶点",
        "event_ref": "E003（智伯向韩康子索地，段规劝韩康子予之以骄其志）",
        "visual_type": "scene",
        "motion_mode": "slow_push_in",
        "shot_size": "medium_close",
        "keyframe_mode": "keyframe_pair",

        # 附录 B 实例化
        "frame_a_prompt": (
            "Chinese ink wash painting, water-ink texture, low saturation, muted earth tones, "
            "Warring States period China 453BC, "
            "interior of a grand bronze-lamplit banquet hall, lacquered low tables, silk banners, "
            "a powerful nobleman [智伯/Zhi Bo] standing imperiously, dark robes with red borders, "
            "commanding gaze sweeping over seated guests, bronze wine vessel raised, "
            "candlelight casting dramatic shadows, deep amber glow, "
            "medium-close shot, slight push-in, 35mm equivalent, "
            "masterpiece ink painting style, no modern elements, no anime"
        ),
        "frame_b_prompt": (
            "Chinese ink wash painting, water-ink texture, low saturation, muted earth tones, "
            "Warring States period China 453BC, "
            "same banquet hall, close-up on a large silk map scroll of Jin territory [晋国版图], "
            "nobleman's hand gesturing over the map territory, ink strokes delineating mountains rivers, "
            "tension in the room, guests' shadows visible at edges, "
            "warm candlelight, deep shadows, "
            "close-up shot, static frame, "
            "masterpiece ink painting style, no modern elements, no anime"
        ),
        "keyframe_a_role": "首帧: 权力宣示，智伯全身强势亮相",
        "keyframe_b_role": "尾帧: 地图特写，晋国版图象征领土野心",
        "negative_prompt": GLOBAL_PARAMS["negative_global"],

        # 附录 B 参数表（§15）
        "params_15": {
            "constitution_thesis": "三家分晋：礼崩乐坏，始于名分之破",
            "tone": ["肃杀", "克制", "史诗感"],
            "art_direction": GLOBAL_PARAMS["art_direction"],
            "render_style": "animated",
            "shot_size": "medium_close",
            "camera_movement": "slow_push_in",
            "lighting": "bronze candlelight, low-key, deep amber",
            "emotion_curve": "压抑铺垫 → 傲慢显现",
            "denoising_strength": GLOBAL_PARAMS["denoising_strength"],
            "identity_threshold": GLOBAL_PARAMS["identity_threshold_g0"],
        },
    },

    # ─── S2: 三家秘密联盟（裂线隐现，过渡镜头）──────────────────────────
    {
        "shot_id": "S2",
        "scene_title": "三家秘密联盟 — 裂线隐现",
        "event_ref": "E005（韩赵魏三卿密谋，引晋水灌智伯营）",
        "visual_type": "map",  # 此镜头走地图通道
        "motion_mode": "ken_burns",
        "shot_size": "wide",
        "keyframe_mode": "keyframe_pair",

        "frame_a_prompt": (
            "Chinese ink wash painting, water-ink texture, low saturation, "
            "ancient Chinese historical map illustration, Warring States period 453BC, "
            "wide view of Jin [晋国] territory map in ink on aged paper, "
            "subtle hairline cracks visible beneath the unified red territory [预置裂线], "
            "three thin dashed fault lines barely visible, red ink territory dominant, "
            "moonlit night atmosphere, silver light, "
            "wide establishing shot, slight zoom-out, "
            "masterpiece ink map style, no text labels, no modern elements"
        ),
        "frame_b_prompt": (
            "Chinese ink wash painting, water-ink texture, low saturation, "
            "ancient Chinese historical map illustration, Warring States period 453BC, "
            "wide view of the same map territory, but the unified red is fragmenting, "
            "three distinct zones emerging: brick-red [韩/Han] in south, blue-grey [赵/Zhao] in north, "
            "forest-green [魏/Wei] in west, fault lines now boldly visible, "
            "dramatic moonlight, rivers catching silver gleam, "
            "wide shot, slow zoom-in on fracture lines, "
            "masterpiece ink map style, no text labels, no modern elements"
        ),
        "keyframe_a_role": "首帧: 晋国版图完整但裂纹若隐若现",
        "keyframe_b_role": "尾帧: 三色开始分离，裂线清晰化",
        "negative_prompt": (
            GLOBAL_PARAMS["negative_global"]
            + ", Chinese characters visible, text, labels, numbers"
        ),

        "params_15": {
            "constitution_thesis": "三家分晋：礼崩乐坏，始于名分之破",
            "tone": ["肃杀", "克制"],
            "art_direction": GLOBAL_PARAMS["art_direction"],
            "render_style": "animated",
            "shot_size": "wide",
            "camera_movement": "ken_burns_zoom_out_then_in",
            "lighting": "moonlight, silver-cool, river reflections",
            "emotion_curve": "tension mounting → fracture imminent",
            "denoising_strength": GLOBAL_PARAMS["denoising_strength"],
            "identity_threshold": None,  # 无人物角色，不做身份校验
            "special_note": "A2 严格模式：map 通道必须零文字",
        },
    },

    # ─── S3: 三家分晋落定（韩赵魏版图成形，史诗收尾）──────────────────
    {
        "shot_id": "S3",
        "scene_title": "三家分晋落定 — 礼之终结",
        "event_ref": "E007/E008（周威烈王正式册封韩赵魏为诸侯，晋名义消亡）",
        "visual_type": "map",
        "motion_mode": "slow_pull_out",
        "shot_size": "wide",
        "keyframe_mode": "keyframe_pair",

        "frame_a_prompt": (
            "Chinese ink wash painting, water-ink texture, low saturation, deep ink tones, "
            "ancient Chinese historical map, Warring States transition moment, "
            "the old Jin [晋国] territory map, deep crimson red, solid unified, "
            "final moment of unity — ink beginning to bleed at edges, "
            "dusk light, vermillion sky, heavy atmosphere, "
            "wide shot, static, "
            "epic ink painting style, no text, no modern elements"
        ),
        "frame_b_prompt": (
            "Chinese ink wash painting, water-ink texture, low saturation, "
            "ancient Chinese historical map, post-453BC, "
            "three clearly defined new kingdoms: "
            "Han [韩] in brick-red south, Zhao [赵] in deep blue-grey north, Wei [魏] in forest-green west, "
            "Jin [晋] name erased — only rivers and mountains remain unchanged, "
            "the Yellow River [黄河] flowing unchanged through the new borders, "
            "deep dusk sky, mournful atmosphere, ink bleeding at territory borders, "
            "wide shot, very slow pull-out to reveal full map, "
            "epic ink painting style, masterpiece, no text labels, no modern elements"
        ),
        "keyframe_a_role": "首帧: 晋国最后一刻，统一版图即将消散",
        "keyframe_b_role": "尾帧: 韩赵魏三色版图清晰，黄河长江穿越国界，礼崩乐坏的史诗定格",
        "negative_prompt": (
            GLOBAL_PARAMS["negative_global"]
            + ", Chinese characters, text labels, numbers, modern cartography style"
        ),

        "params_15": {
            "constitution_thesis": "三家分晋：礼崩乐坏，始于名分之破",
            "tone": ["肃杀", "史诗感", "余韵"],
            "art_direction": GLOBAL_PARAMS["art_direction"],
            "render_style": "animated",
            "shot_size": "wide",
            "camera_movement": "slow_pull_out",
            "lighting": "deep dusk, vermillion sky, mournful",
            "emotion_curve": "余韵与史评 — 历史必然的沉重感",
            "denoising_strength": GLOBAL_PARAMS["denoising_strength"],
            "identity_threshold": None,
            "special_note": (
                "B2 计数目标：尾帧应可识别 3 个独立色块（韩/赵/魏）；"
                "VLM 问法：'图中有几个颜色明显不同的主要区域？' 期望回答 3"
            ),
        },
    },
]


def main():
    t0 = time.perf_counter()

    output = {
        "run_id": "g0_prompts",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "spec_ref": "HEVI-SPEC-02 §3/§4, 附录B模板, §15参数表",
        "global_params": GLOBAL_PARAMS,
        "shots": PROMPTS,
        "note": (
            "G0 手工实例化 — 不经过编译器/模板引擎。"
            "提示词直接用于 keyframe_pair 模式生成。"
        ),
    }

    out_path = OUT / "prompts_s1s2s3.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    elapsed = time.perf_counter() - t0
    print(f"✓ 提示词文件: {out_path} ({elapsed:.3f}s)")

    # 人可读打印
    print("\n─── 提示词 ×3 概览 ─────────────────────────────────────────────")
    for shot in PROMPTS:
        print(f"\n【{shot['shot_id']}】{shot['scene_title']}")
        print(f"  事件引用: {shot['event_ref']}")
        print(f"  首帧: {shot['keyframe_a_role']}")
        print(f"    {shot['frame_a_prompt'][:100]}...")
        print(f"  尾帧: {shot['keyframe_b_role']}")
        print(f"    {shot['frame_b_prompt'][:100]}...")
        params = shot["params_15"]
        print(f"  §15: render_style={params['render_style']} "
              f"shot_size={params['shot_size']} "
              f"denoising={params['denoising_strength']} "
              f"id_thresh={params.get('identity_threshold', 'N/A')}")
    print("────────────────────────────────────────────────────────────────")


if __name__ == "__main__":
    main()
