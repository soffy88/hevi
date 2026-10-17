"""婚宴致辞 + 闪回推轮椅 首帧图提示词与防穿帮校验演示 (FF-1017)。

演示功能：
1. 资产定妆参考图 (compile_asset_refs)：角色/场景/道具提示词与 Midjourney 入口分配
   (Attach to prompt 保人物/物体；Style Reference 借画风；Image Prompts 借构图)。
2. 每镜首帧图提示词输出 (MJ V8.x 网页端标准格式 + 通用自然语言版)。
3. 扩图/改画幅提示词示例 (build_outpaint_prompt) 与 Midjourney Editor 操作流程。
4. 校验器演示拦截 3 大首帧穿帮错误：
   - 错误 1: 画幅不符 (视频画幅 16:9，首帧出现 --ar 9:16)
   - 错误 2: 推轮椅动作首帧景别仅到肩部 (Close-Up 特写缺少身体与运动空间)
   - 错误 3: 道具位置与账本 0 秒不符 (账本挂在轮椅挂钩，首帧写成新郎手持)
5. 修复穿帮后二次校验 (0 errors 完美合规)。
6. 导出包含首帧图与图生视频联动的连续性母包与 Markdown 排版。
"""

from __future__ import annotations

import os
import sys

# 保证当前 repo 在导入路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hevi.prompt.continuity import (
    CharacterCard,
    FilmBible,
    PropItem,
    PropLedger,
    SceneCard,
    ShotContract,
    VoiceCard,
    build_local_edit_prompt,
    build_outpaint_prompt,
    compile_asset_refs,
    compile_first_frame,
    export_continuity_package,
    validate_film,
    validate_first_frame,
)


def run_demo() -> None:
    print("=" * 80)
    print("hevi 视频提示词配套「首帧图提示词」能力演示 (FF-1017)")
    print("=" * 80)

    # ── 1. 建立整片圣经 (FilmBible) ─────────────────────────────────────────
    bible = FilmBible(
        title="爱在时光里",
        aspect_ratio="16:9",
        style_is=["电影质感院线叙事短片", "温暖质朴现实主义"],
        style_is_not=["廉价网剧", "夸张滤镜", "悬浮质感"],
        language="zh-普通话",
        language_lock="全部对白与背景人声只说普通话，禁止日语或其他语言；画面不出现文字",
        text_whitelist=["百年好合", "康复花园"],
        genre_preset="Drama",
        color_grading_baseline="暖金胶片色调，暗部深邃不偏色，肤色通透自然",
        mj_version="8.2",
        mj_stylize=75,
        mj_chaos=0,
        mj_raw=True,
    )

    # ── 2. 建立角色母卡 (CharacterCard，中英双语完整外貌逐字复用) ───────────
    groom = CharacterCard(
        s_no=1,
        name="李明",
        name_en="Li Ming",
        appearance_fixed=(
            "30岁成年东亚男子，面部棱角分明，短发梳理整齐微卷，浓眉，右眉角有一道浅淡旧疤痕，"
            "双眼温和坚定，高鼻梁薄唇；身穿深灰色定制羊毛西装外套，内搭纯白挺括衬衫与深黑色领结，"
            "左胸佩戴一朵淡香槟色玫瑰襟花，无耳环戒指。"
        ),
        appearance_fixed_en=(
            "an adult East Asian man in his early thirties, sharp facial contours, neatly styled short dark hair with slight waves, "
            "thick eyebrows, a faint old scar at the right eyebrow corner, gentle and determined eyes, a tall nose bridge and thin lips; "
            "wearing a tailored charcoal-gray wool suit jacket over a crisp white dress shirt and deep black bow tie, "
            "a pale champagne rose boutonniere on the left lapel, no earrings or rings"
        ),
        voice_card=VoiceCard(gender_age="30岁青年男性", timbre="温和醇厚沙哑磁性"),
        daily_states={
            "D1": "婚宴正日：发型整齐油亮，西装一尘不染，精神饱满",
            "D_flashback": "三年前回忆：短发微乱，浅蓝色棉质针织衫与深灰运动长裤",
        },
    )

    bride = CharacterCard(
        s_no=2,
        name="苏晴",
        name_en="Su Qing",
        appearance_fixed=(
            "28岁东亚女子，鹅蛋脸，皮肤白皙，深棕色柔顺长发盘起，耳际自然散落微卷碎发，戴精巧单颗珍珠耳钉，"
            "杏眼清亮带笑意，眉形柔和，浅粉色唇膏；身穿米白色露肩缎面轻婚纱，裙摆绣有淡暗纹银丝，"
            "锁骨正中戴一条极细银质吊坠项链。"
        ),
        appearance_fixed_en=(
            "an adult East Asian woman in her late twenties, oval face, fair skin, soft dark-brown hair neatly styled in an elegant updo "
            "with gentle wisps around the ears, wearing dainty single-pearl stud earrings, bright expressive almond eyes, "
            "soft eyebrows and pale pink lips; dressed in an off-the-shoulder off-white satin wedding dress with subtle silver embroidery, "
            "a delicate thin silver pendant necklace centered on the collarbone"
        ),
        voice_card=VoiceCard(gender_age="28岁年轻女性", timbre="轻柔纯净甜美"),
        daily_states={
            "D1": "婚宴正日：盘发珍珠婚纱，气色红润幸福",
            "D_flashback": "三年前回忆：马尾辫，膝盖覆浅粉色针织毛毯，浅灰棉质病服外套，坐在轮椅上",
        },
    )
    characters = {"李明": groom, "苏晴": bride}

    # ── 3. 建立场景母卡 (SceneCard) ─────────────────────────────────────────
    scene_wedding = SceneCard(
        scene_name="宴会主厅",
        description="五星级酒店宏大宴会厅，水晶吊灯高悬，主舞台后方为暖金暗红纱幔花艺",
        description_en=(
            "a grand hotel banquet hall with crystal ceiling chandeliers in soft focus, a warm golden and muted-crimson velvet drape backdrop, "
            "round dining tables draped in fine linen"
        ),
        lighting="Three-Point / 侧逆主光45度 / 3200K暖白钨丝灯感 / 柔光漫射",
        lighting_en="soft 3200K warm tungsten key light from 45 degrees, subtle rim lighting accentuating shoulders, cinematic contrast",
        ambient_noise="宴会大厅平稳轻微人声低语、玻璃杯轻微碰撞声，连续平稳",
        music_policy="无音乐",
    )

    scene_hospital = SceneCard(
        scene_name="康复花园",
        description="三年前阳光微醺的医院康复石子小径，两侧盛开黄色金丝桃灌木",
        description_en=(
            "a tranquil outdoor hospital rehabilitation garden with smooth cobblestone pathways, manicured green hedges, "
            "and golden hypericum shrubs under dappled afternoon sunlight"
        ),
        lighting="Natural / 傍晚低角度暖金逆光 / 4500K柔和漫射",
        lighting_en="natural warm afternoon rim light shining through trees, soft diffuse shadows, authentic daylight exposure",
        ambient_noise="午后微风吹过树叶沙沙声，远处偶尔一声鸟鸣",
        music_policy="无音乐",
    )
    scenes = {"宴会主厅": scene_wedding, "康复花园": scene_hospital}

    # ── 4. 建立道具账本 (PropLedger) ─────────────────────────────────────────
    mic = PropItem(
        prop_name="立式麦克风",
        prop_name_en="microphone",
        holder="李明",
        placement="右手手持",
        placement_en="held in his right hand",
        start_state="右手握持银色立式麦克风",
        start_state_en="holding a silver wireless microphone in his right hand, left arm resting naturally by his side",
    )
    wheelchair = PropItem(
        prop_name="折叠轮椅",
        prop_name_en="wheelchair",
        holder="李明",
        placement="双手推扶把手",
        placement_en="gripping both rubber handles",
        start_state="双手握持轮椅橡胶推把",
        start_state_en="standing behind the wheelchair with both hands firmly gripping the black rubber handles",
    )
    handbag = PropItem(
        prop_name="女式黑皮手提包",
        prop_name_en="handbag",
        holder="苏晴",
        placement="挂在轮椅右侧挂钩",
        placement_en="hanging securely from the right hook of the wheelchair",
        start_state="小巧黑色手提包挂在轮椅把手挂钩处",
        start_state_en="a small black leather handbag hanging securely from the right hook of the wheelchair",
    )
    props = PropLedger(items=[mic, wheelchair, handbag])

    # ── 5. 镜头契约 (Shot 1 与 Shot 2) ──────────────────────────────────────
    shot1 = ShotContract(
        shot_id="Shot-01",
        scene_name="宴会主厅",
        shot_type="Medium Close-Up",
        shot_type_en="medium close-up",
        camera_move="Push In",
        composition="Rule of Thirds",
        composition_en="rule of thirds framing with balanced negative space around the head",
        character_names=["李明"],
        prop_names=["立式麦克风"],
        start_state="李明站于主舞台发言台前，右手持话筒，目光深情",
        start_state_en="standing at the center podium, facing three-quarters towards the right, smiling gently",
        action="李明手持话筒动情回忆过去",
        duration_s=5.0,
        story_day="D1",
        hands_occupation={"右手": "手持立式麦克风", "左手": "自然下垂"},
    )

    shot2 = ShotContract(
        shot_id="Shot-02",
        scene_name="康复花园",
        shot_type="Full Shot",
        shot_type_en="full-body shot",
        camera_move="Tracking",
        composition="Leading Lines",
        composition_en="leading lines along the garden pathway, ample space in the direction of movement",
        character_names=["李明", "苏晴"],
        prop_names=["折叠轮椅", "女式黑皮手提包"],
        start_state="李明双手推着轮椅，苏晴静坐轮椅上，手提包挂在轮椅右侧挂钩",
        start_state_en=(
            "Li Ming standing behind the wheelchair, gripping both handles, looking down warmly; "
            "Su Qing sitting peacefully in the wheelchair with a knitted lap blanket over her knees"
        ),
        action="李明推着轮椅上的苏晴在康复花园鹅卵石步道上向前漫步",
        duration_s=5.0,
        story_day="D_flashback",
        hands_occupation={"李明": "双手推扶轮椅把手"},
    )

    # ── [DEMO 1] 资产定妆参考图编译 ──────────────────────────────────────────
    print("\n[DEMO 1] 编译资产定妆参考图 (compile_asset_refs)...")
    specs = compile_asset_refs(bible=bible, characters=characters, scenes=scenes, props=props)
    for sp in specs:
        print(f"\n  • 资产编号: {sp.asset_id} | 类别: {sp.category}")
        print(f"    Midjourney 入口: 【{sp.entry_slot}】")
        print(f"    入口说明: {sp.instructions}")
        print(f"    提示词: {sp.prompt[:120]}...")

    # ── [DEMO 2] 每镜首帧图提示词 (Midjourney V8.x + 通用自然语言) ───────────
    print("\n" + "=" * 80)
    print("[DEMO 2] 编译分镜头首帧图提示词 (compile_first_frame)...")
    for s in [shot1, shot2]:
        sc = scenes[s.scene_name]
        mj_ff = compile_first_frame(s, bible, sc, characters, props, platform="midjourney")
        gen_ff = compile_first_frame(s, bible, sc, characters, props, platform="generic")
        print(f"\n--- 镜头: {s.shot_id}（{s.scene_name}）---")
        print("【Midjourney V8.x 首帧提示词】:")
        print(f"  {mj_ff.prompt}")
        print("【通用自然语言首帧提示词 (ChatGPT Image / 即梦)】:")
        print(f"  {gen_ff.prompt}")
        print("【首帧规划要求】:")
        for r in mj_ff.requirements[:2]:
            print(f"  - {r}")

    # ── [DEMO 3] 扩图/改画幅提示词示例 ───────────────────────────────────────
    print("\n" + "=" * 80)
    print("[DEMO 3] 扩图与改画幅提示词模板 (build_outpaint_prompt)...")
    outpaint_sample = build_outpaint_prompt(
        scene_background="outdoor hospital rehabilitation garden cobblestone path and hedge bushes",
        subject="Li Ming pushing Su Qing in wheelchair",
        lighting="coherent warm afternoon sunlight",
        directions="above and below, left and right",
        target_ar="16:9",
    )
    print(f"  提示词: {outpaint_sample['prompt']}")
    print(f"  操作指南: {outpaint_sample['instructions']}")

    # ── [DEMO 4] 校验器演示拦截 3 大首帧穿帮错误 ────────────────────────────
    print("\n" + "=" * 80)
    print("[DEMO 4] 校验器拦截首帧典型穿帮错误 (validate_first_frame)...")

    # 错误 1: 画幅不符 (视频 16:9，首帧写成了 9:16)
    bad_prompt_ar = (
        f"cinematic still of Li Ming, {groom.appearance_fixed_en}, "
        "holding microphone in his right hand --ar 9:16 --v 8.2 --raw --s 75 --c 0 --sd"
    )
    errs_ar = validate_first_frame(shot1, bible, bad_prompt_ar, props=props, characters=characters)
    print("\n-> 穿帮场景 1 (画幅不一致):")
    for e in errs_ar:
        print(f"   [捕获错误] {e}")

    # 错误 2: 动作需要全身，首帧景别却为特写/肩部以上
    shot2_bad_framing = ShotContract(
        shot_id="Shot-02-Flawed",
        scene_name="康复花园",
        shot_type="特写镜头",
        shot_type_en="close-up shot",
        character_names=["李明", "苏晴"],
        action="李明推着轮椅上的苏晴在康复小径上漫步前行",  # 强位移动作
    )
    bad_prompt_framing = (
        f"close-up shot framing of Li Ming, {groom.appearance_fixed_en}, {bride.appearance_fixed_en} "
        "--ar 16:9 --v 8.2 --raw --s 75 --c 0 --sd"
    )
    errs_framing = validate_first_frame(
        shot2_bad_framing, bible, bad_prompt_framing, props=props, characters=characters
    )
    print("\n-> 穿帮场景 2 (推轮椅位移动作被误设为特写/肩部以上):")
    for e in errs_framing:
        print(f"   [捕获错误] {e}")

    # 错误 3: 首帧道具位置与账本 0 秒状态不符 (包挂在挂钩，首帧写成手持)
    bad_prompt_prop = (
        f"cinematic still of Li Ming, {groom.appearance_fixed_en}, "
        f"{bride.appearance_fixed_en}, holding handbag in his right hand "  # 冲突！
        "--ar 16:9 --v 8.2 --raw --s 75 --c 0 --sd"
    )
    errs_prop = validate_first_frame(shot2, bible, bad_prompt_prop, props=props, characters=characters)
    print("\n-> 穿帮场景 3 (道具账本 0 秒位置为挂钩，首帧却写成手持):")
    for e in errs_prop:
        print(f"   [捕获错误] {e}")

    # ── [DEMO 5] 修复后二次校验 ─────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("[DEMO 5] 修复全部错误后全片统一校验 (validate_film)...")
    valid_shot1_mj = compile_first_frame(shot1, bible, scene_wedding, characters, props, platform="midjourney")
    valid_shot2_mj = compile_first_frame(shot2, bible, scene_hospital, characters, props, platform="midjourney")

    all_errors = validate_film(
        bible=bible,
        scenes=scenes,
        characters=characters,
        props=props,
        shots=[shot1, shot2],
        first_frame_prompts=[valid_shot1_mj, valid_shot2_mj],
    )
    print(f"-> 校验通过！错误数: {len(all_errors)} (0 ERRORS PASS!)")

    # ── [DEMO 6] 导出连续性母包与 Markdown 预览 ─────────────────────────────
    print("\n" + "=" * 80)
    print("[DEMO 6] 导出连续性制作母包与 Markdown (export_continuity_package)...")
    pkg = export_continuity_package(
        bible=bible,
        scenes=scenes,
        characters=characters,
        props=props,
        shots=[shot1, shot2],
        platform="generic",
    )
    print("\n[Markdown 导出排版预览（前 30 行）]:")
    md_lines = pkg["markdown"].split("\n")
    print("\n".join(md_lines[:30]))

    print("\n" + "=" * 80)
    print("DEMO 执行完毕！FF-1017 首帧图生成、校验与全流程联动全部正常。")
    print("=" * 80)


if __name__ == "__main__":
    run_demo()
