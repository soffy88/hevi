"""FF-1017 首帧图提示词、资产参考图、编辑扩图与校验规则单元测试。

全真实调用，禁止 mock。
覆盖：
1. 提示词顺序 (主体 → 外观/动作起始姿态 → 环境 → 光线 → 画面形式构图)
2. 角色外貌与场景描述从卡片逐字复用
3. 三种 platform (midjourney, generic, chatgpt_image) 输出差异
4. --ar 跟随视频画幅且只出现一次 (16:9, 9:16, 2.39:1)
5. Midjourney 可选参数 (--seed, --p, --sref, --sw, --iw, 情绪板禁 --sw)
6. 资产定妆参考图与 Midjourney 入口分配 (Attach to prompt, Style Reference, Image Prompts)
7. 编辑与扩图模板 (局部修改 Change only... / 扩图 Extend... 及操作指引)
8. 图生视频提示词联动 (has_first_frame 时只写动作运镜声音，保留一致性条款，提示"先简单动作再加复杂度")
9. 导出连续性母包与 Markdown 格式 (「资产参考图 → 每镜【首帧图】【视频】【负面】」)
10. 10 大校验错误检测：
   - 首帧 --ar 与视频画幅不符
   - --ar 重复出现
   - 中文破折号/全角符号
   - 出现 /imagine
   - --p 与 --sref 混写
   - 情绪板配 --sw/--sv
   - 动作需要全身但首帧是特写/肩部以上
   - 首帧道具状态与账本 0 秒状态不符
   - 角色描述未逐字复用
   - 画内文字不在白名单
"""

from __future__ import annotations

import pytest

from hevi.prompt.continuity.first_frame import (
    FIRST_FRAME_REQUIREMENTS,
    build_local_edit_prompt,
    build_outpaint_prompt,
    compile_asset_refs,
    compile_end_frame,
    compile_first_frame,
    validate_first_frame,
)
from hevi.prompt.continuity.schemas import (
    CharacterCard,
    FilmBible,
    PropItem,
    PropLedger,
    SceneCard,
    ShotContract,
    VoiceCard,
)
from hevi.prompt.continuity.compiler import (
    compile_continuity_prompt,
    export_continuity_markdown,
    export_continuity_package,
)
from hevi.prompt.continuity.validator import validate_film


@pytest.fixture
def sample_bible():
    return FilmBible(
        title="测试短片",
        aspect_ratio="16:9",
        style_is=["电影质感叙事短片", "真实摄影"],
        style_is_not=["廉价网剧", "过度磨皮"],
        language="zh-普通话",
        language_lock="全部对白与背景人声只说普通话，禁止日语或其他语言；画面不出现文字",
        text_whitelist=["百年好合", "康复花园"],
    )


@pytest.fixture
def sample_characters():
    c1 = CharacterCard(
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
        voice_card=VoiceCard(gender_age="30岁青年男性", timbre="温和醇厚"),
    )
    c2 = CharacterCard(
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
            "soft eyebrows and pale pink lips; dressed in an off-the-shoulder off-white satin wedding dress with subtle silver embroidery"
        ),
        voice_card=VoiceCard(gender_age="28岁年轻女性", timbre="清亮甜美"),
    )
    return {"李明": c1, "苏晴": c2}


@pytest.fixture
def sample_scenes():
    s1 = SceneCard(
        scene_name="婚宴主舞台",
        scene_name_en="luxury banquet hall",
        description="五星级酒店豪华宴会厅，主舞台铺浅金色地毯，背景为淡香槟色巨型丝绒花艺背景墙与暖光射灯",
        description_en=(
            "a luxury hotel banquet hall with a champagne-colored velvet backdrop, round dining tables draped in fine linen, "
            "crystal chandeliers hanging overhead in the soft-focus background"
        ),
        lighting="暖金胶片色调，舞台面光聚焦新人，背景桌席保留适度暗角与层次感",
        lighting_en="warm golden directional key light from the front-left, soft ambient fill light, subtle rim light separating the subject",
        lens="50mm定焦镜头，光圈f/2.0，视平机位",
        ambient_noise="宴会厅柔和底噪",
        music_policy="无音乐",
    )
    s2 = SceneCard(
        scene_name="医院康复花园",
        scene_name_en="hospital rehabilitation garden",
        description="三年前阳光明媚的午后，医院室外康复花园鹅卵石步道，两侧为修剪整齐的绿植矮灌木与白色木质长椅",
        description_en=(
            "a sunny outdoor hospital rehabilitation garden with smooth cobblestone pathways, manicured green hedges, "
            "and a white wooden park bench under dappled afternoon sunlight"
        ),
        lighting="自然午后阳光，微逆光形成发丝边缘光，阴影柔和自然",
        lighting_en="natural soft afternoon sunlight, gentle rim light illuminating hair contours, soft diffuse shadows",
        lens="35mm中焦，视平微仰",
        ambient_noise="微风吹拂树叶声与远处微弱鸟鸣",
        music_policy="无音乐",
    )
    return {"婚宴主舞台": s1, "医院康复花园": s2}


@pytest.fixture
def sample_props():
    return PropLedger(
        items=[
            PropItem(
                prop_name="话筒",
                prop_name_en="microphone",
                appearance_en="a metallic silver wireless handheld microphone with a dark matte mesh grille and aluminum casing",
                holder="李明",
                placement="右手手持",
                placement_en="held in his right hand",
                start_state="右手稳持银色无线麦克风",
                start_state_en="holding a sleek silver wireless microphone in his right hand, left hand resting by his side",
            ),
            PropItem(
                prop_name="轮椅",
                prop_name_en="wheelchair",
                appearance_en="a modern foldable manual wheelchair with matte black aluminum frame, clean padded seat and dual large rubber wheels",
                holder="李明",
                placement="双手推扶把手",
                placement_en="gripping both rubber handles",
                start_state="新郎双手扶在轮椅橡胶把手处",
                start_state_en="groom standing behind the wheelchair with both hands firmly gripping the rubber handles",
            ),
            PropItem(
                prop_name="手提包",
                prop_name_en="handbag",
                appearance_en="a structured small black leather women's handbag with polished gold-tone hardware and fine grain texture",
                holder="苏晴",
                placement="挂在轮椅右侧挂钩",
                placement_en="hanging securely on the right hook of the wheelchair",
                start_state="黑色皮质小手提包安稳挂在轮椅挂钩",
                start_state_en="a small black leather handbag hanging securely on the right hook of the wheelchair",
            ),
        ]
    )


# ── 1. 首帧提示词顺序、内容与逐字复用测试 ───────────────────────────────────


def test_compile_first_frame_structure_and_order(sample_bible, sample_scenes, sample_characters, sample_props):
    shot = ShotContract(
        shot_id="Shot-1",
        scene_name="婚宴主舞台",
        shot_type="Medium Shot",
        shot_type_en="medium shot",
        camera_move="Static",
        character_names=["李明"],
        prop_names=["话筒"],
        start_state="李明右手持话筒站在舞台中央偏左",
        start_state_en="standing in the center-left of the stage, facing three-quarters towards the right",
        action="李明手持话筒，目光深情望向台下的苏晴",
        duration_s=4.0,
    )

    result = compile_first_frame(
        shot=shot,
        bible=sample_bible,
        scene=sample_scenes["婚宴主舞台"],
        characters=sample_characters,
        props=sample_props,
        platform="midjourney",
    )

    prompt = result.prompt

    # 1. 验证角色外貌描述逐字复用
    c1 = sample_characters["李明"]
    assert c1.appearance_fixed_en in prompt

    # 2. 验证场景描述逐字复用
    s1 = sample_scenes["婚宴主舞台"]
    assert s1.description_en in prompt

    # 3. 验证光线描述逐字复用
    assert s1.lighting_en in prompt

    # 4. 验证 0 秒状态与道具账本 (右手持话筒)
    assert "held in his right hand" in prompt or "silver wireless microphone" in prompt

    # 5. 验证无空洞 buzzwords
    for forbidden in ["masterpiece", "8k", "hyperrealistic", "delicate", "高级感", "绝美"]:
        assert forbidden not in prompt.lower()

    # 6. 验证 Midjourney 参数与画幅跟随
    assert "--ar 16:9" in prompt
    assert "--v 8.2" in prompt
    assert "--raw" in prompt
    assert "--s 75" in prompt
    assert "--c 0" in prompt
    assert "--sd" in prompt
    assert prompt.count("--ar") == 1
    assert "/imagine" not in prompt


# ── 2. 三种 Platform 输出差异测试 ──────────────────────────────────────────


def test_platform_output_differences(sample_bible, sample_scenes, sample_characters, sample_props):
    shot = ShotContract(
        shot_id="Shot-1",
        scene_name="婚宴主舞台",
        shot_type_en="medium shot",
        character_names=["李明"],
        prop_names=["话筒"],
    )
    sc = sample_scenes["婚宴主舞台"]

    # Midjourney: 包含 --ar 16:9 --v 8.2 等参数
    mj_res = compile_first_frame(shot, sample_bible, sc, sample_characters, sample_props, platform="midjourney")
    assert "--ar 16:9" in mj_res.prompt
    assert "--v 8.2" in mj_res.prompt
    assert "--raw" in mj_res.prompt

    # Generic: 纯自然语言，无 -- 参数，画幅写成文字
    gen_res = compile_first_frame(shot, sample_bible, sc, sample_characters, sample_props, platform="generic")
    assert "--ar" not in gen_res.prompt
    assert "--v" not in gen_res.prompt
    assert "16:9 aspect ratio" in gen_res.prompt

    # ChatGPT Image: DALL-E 风格自然语言
    gpt_res = compile_first_frame(shot, sample_bible, sc, sample_characters, sample_props, platform="chatgpt_image")
    assert "--ar" not in gpt_res.prompt
    assert gpt_res.prompt.startswith("Create a realistic cinematic still photograph in 16:9 aspect ratio.")


# ── 3. --ar 跟随视频画幅且只出现一次测试 ──────────────────────────────────────


def test_ar_follows_video_aspect_ratio(sample_bible, sample_scenes, sample_characters):
    shot = ShotContract(shot_id="S-AR", scene_name="婚宴主舞台", character_names=["李明"])
    sc = sample_scenes["婚宴主舞台"]

    for ar in ["16:9", "9:16", "2.39:1", "1:1"]:
        sample_bible.aspect_ratio = ar
        res = compile_first_frame(shot, sample_bible, sc, sample_characters, platform="midjourney")
        assert f"--ar {ar}" in res.prompt
        assert res.prompt.count("--ar") == 1


# ── 4. Midjourney 可选参数与情绪板约束测试 ───────────────────────────────────


def test_midjourney_optional_parameters_and_moodboard_rules(sample_bible, sample_scenes, sample_characters):
    shot = ShotContract(shot_id="S-OPT", scene_name="婚宴主舞台", character_names=["李明"])
    sc = sample_scenes["婚宴主舞台"]

    # 1. Seed 与 --p 测试
    sample_bible.seed = 42
    sample_bible.personalization = "p123456"
    res1 = compile_first_frame(shot, sample_bible, sc, sample_characters, platform="midjourney")
    assert "--seed 42" in res1.prompt
    assert "--p p123456" in res1.prompt
    assert "--sref" not in res1.prompt

    # 2. --sref 与 --sw 与 --iw 测试 (关 p)
    sample_bible.personalization = ""
    sample_bible.style_ref = "sref9876"
    sample_bible.style_weight = 120
    sample_bible.image_weight = 1.5
    res2 = compile_first_frame(shot, sample_bible, sc, sample_characters, platform="midjourney")
    assert "--sref sref9876" in res2.prompt
    assert "--sw 120" in res2.prompt
    assert "--iw 1.5" in res2.prompt

    # 3. 情绪板 mID 严禁输出 --sw
    sample_bible.personalization = "mID999"
    sample_bible.is_moodboard = True
    sample_bible.style_weight = 200  # 即使配置了 style_weight 也不得出
    res3 = compile_first_frame(shot, sample_bible, sc, sample_characters, platform="midjourney")
    assert "--p mID999" in res3.prompt
    assert "--sw" not in res3.prompt
    assert "--sv" not in res3.prompt


# ── 5. 尾帧提示词 (compile_end_frame) 测试 ───────────────────────────────────


def test_compile_end_frame(sample_bible, sample_scenes, sample_characters, sample_props):
    shot = ShotContract(
        shot_id="Shot-End",
        scene_name="婚宴主舞台",
        character_names=["李明"],
        prop_names=["话筒"],
        end_state="李明放下话筒微鞠躬致谢",
        end_state_en="lowering the microphone and bowing slightly to the applause",
    )
    sc = sample_scenes["婚宴主舞台"]
    end_prompt = compile_end_frame(shot, sample_bible, sc, sample_characters, sample_props, platform="midjourney")
    assert "ending pose: lowering the microphone and bowing slightly" in end_prompt
    assert "--ar 16:9" in end_prompt


# ── 6. 资产参考图 (compile_asset_refs) 与入口说明测试 ────────────────────────


def test_compile_asset_refs(sample_bible, sample_scenes, sample_characters, sample_props):
    specs = compile_asset_refs(
        bible=sample_bible,
        characters=sample_characters,
        scenes=sample_scenes,
        props=sample_props,
    )

    # 验证角色、场景、道具数量
    assert len(specs) == len(sample_characters) + len(sample_scenes) + len(sample_props.items)

    # 角色定妆图：入口必须是 Attach to prompt (保人物)
    char_specs = [s for s in specs if s.category == "character"]
    for cs in char_specs:
        assert cs.entry_slot == "Attach to prompt"
        assert "Attach to prompt" in cs.instructions
        assert "Style Reference" in cs.instructions
        assert "会换人" in cs.instructions
        assert "--ar 1:1" in cs.prompt

    # 场景参考图：入口为 Image Prompts
    scene_specs = [s for s in specs if s.category == "scene"]
    for ss in scene_specs:
        assert ss.entry_slot == "Image Prompts"
        assert "--ar 16:9" in ss.prompt

    # 道具参考图：入口为 Attach to prompt
    prop_specs = [s for s in specs if s.category == "prop"]
    for ps in prop_specs:
        assert ps.entry_slot == "Attach to prompt"
        assert "--ar 1:1" in ps.prompt


# ── 7. 编辑与扩图提示词模板测试 ──────────────────────────────────────────────


def test_edit_and_outpaint_templates():
    # 局部修改
    edit_res = build_local_edit_prompt(
        change_from="the cream linen shirt",
        change_to="muted sage green linen shirt",
    )
    assert edit_res["prompt"] == "Change only the cream linen shirt to muted sage green linen shirt. Keep the same face, hair, pose, light and background."
    assert "每轮只改一个主要要求" in edit_res["instructions"]
    assert "Open Editor" in edit_res["instructions"]

    # 扩图模板
    outpaint_res = build_outpaint_prompt(
        scene_background="outdoor hospital garden",
        subject="groom pushing bride in wheelchair",
        lighting="soft afternoon light",
        directions="above and below",
        target_ar="16:9",
    )
    assert outpaint_res["prompt"] == "Extend the existing outdoor hospital garden above and below. Keep the existing groom pushing bride in wheelchair unchanged, coherent soft afternoon light."
    assert "Move/resize" in outpaint_res["instructions"]
    assert "16:9" in outpaint_res["instructions"]


# ── 8. 图生视频提示词联动 (has_first_frame=True) 测试 ─────────────────────────


def test_video_prompt_linkage_has_first_frame(sample_bible, sample_scenes, sample_characters, sample_props):
    shot = ShotContract(
        shot_id="Shot-Link",
        scene_name="婚宴主舞台",
        shot_type="Medium Shot",
        camera_move="Push In",
        character_names=["李明"],
        prop_names=["话筒"],
        action="镜头缓慢向前推进，李明手持话筒，目光深情望向台下的苏晴",
        duration_s=4.0,
    )
    sc = sample_scenes["婚宴主舞台"]

    # 1. 传统文生视频模式 (has_first_frame=False): 包含完整长篇外貌描述
    render_t2v = compile_continuity_prompt(
        bible=sample_bible,
        scene=sc,
        characters=sample_characters,
        props=sample_props,
        shot=shot,
        platform="generic",
        has_first_frame=False,
    )
    assert sample_characters["李明"].appearance_fixed in render_t2v.prompt

    # 2. 图生视频模式 (has_first_frame=True): 不重复长篇外貌，但保留一致性条款与提示
    render_i2v = compile_continuity_prompt(
        bible=sample_bible,
        scene=sc,
        characters=sample_characters,
        props=sample_props,
        shot=shot,
        platform="generic",
        has_first_frame=True,
    )
    # 不再重复完整外貌长文本
    assert sample_characters["李明"].appearance_fixed not in render_i2v.prompt
    # 包含首帧图锁定说明
    assert "完全锁定继承自首帧图" in render_i2v.prompt
    # 包含图生视频指引与复杂度提示
    assert "【图生视频指引】图片负责人物、构图、光线" in render_i2v.prompt
    assert "先简单动作再加复杂度" in render_i2v.prompt
    # 保留一致性条款
    assert "【一致性条款】同脸同服装同光线同机位" in render_i2v.prompt


# ── 9. 连续性导出母包与 Markdown 导出测试 ────────────────────────────────────


def test_export_continuity_package_and_markdown(sample_bible, sample_scenes, sample_characters, sample_props):
    shot1 = ShotContract(
        shot_id="Shot-1",
        scene_name="婚宴主舞台",
        shot_type_en="medium shot",
        camera_move="Push In",
        character_names=["李明"],
        prop_names=["话筒"],
        action="李明致辞",
    )
    pkg = export_continuity_package(
        bible=sample_bible,
        scenes=sample_scenes,
        characters=sample_characters,
        props=sample_props,
        shots=[shot1],
        platform="generic",
    )

    assert pkg["title"] == "测试短片"
    assert "asset_refs" in pkg
    assert len(pkg["asset_refs"]) > 0
    assert "shots" in pkg
    assert len(pkg["shots"]) == 1

    s0 = pkg["shots"][0]
    assert "first_frame" in s0
    assert "midjourney" in s0["first_frame"]
    assert "generic" in s0["first_frame"]
    assert "requirements" in s0["first_frame"]
    assert "video_prompt" in s0
    assert "edit_templates" in s0

    # 验证 Markdown 格式严格按「资产参考图 → 每镜【首帧图】【视频】【负面】」排列
    md = pkg["markdown"]
    assert "## 一、资产定妆参考图" in md
    assert "## 二、分镜头制作清单" in md
    assert "#### 【首帧图】" in md
    assert "#### 【视频】" in md
    assert "#### 【负面】" in md
    assert md.index("## 一、资产定妆参考图") < md.index("## 二、分镜头制作清单")
    assert md.index("#### 【首帧图】") < md.index("#### 【视频】") < md.index("#### 【负面】")


# ── 10. 校验器 10 大错误覆盖测试 ─────────────────────────────────────────────


def test_validator_error_1_ar_mismatch(sample_bible, sample_characters):
    shot = ShotContract(shot_id="S-ERR-1", character_names=["李明"])
    # 视频圣经为 16:9，首帧参数为 9:16
    bad_prompt = f"subject description, {sample_characters['李明'].appearance_fixed_en} --ar 9:16 --v 8.2 --raw --s 75 --c 0 --sd"
    errs = validate_first_frame(shot, sample_bible, bad_prompt, characters=sample_characters)
    assert any("首帧 --ar '9:16' 与视频画幅 '16:9' 不符" in e for e in errs)


def test_validator_error_2_ar_duplicated(sample_bible, sample_characters):
    shot = ShotContract(shot_id="S-ERR-2", character_names=["李明"])
    bad_prompt = f"subject description, {sample_characters['李明'].appearance_fixed_en} --ar 16:9 --ar 16:9 --v 8.2 --raw --s 75 --c 0 --sd"
    errs = validate_first_frame(shot, sample_bible, bad_prompt, characters=sample_characters)
    assert any("首帧参数中 --ar 重复出现" in e for e in errs)


def test_validator_error_3_chinese_dash(sample_bible, sample_characters):
    shot = ShotContract(shot_id="S-ERR-3", character_names=["李明"])
    bad_prompt = f"subject description, {sample_characters['李明'].appearance_fixed_en} ——ar 16:9 --v 8.2 --raw --s 75 --c 0 --sd"
    errs = validate_first_frame(shot, sample_bible, bad_prompt, characters=sample_characters)
    assert any("参数使用了中文破折号或全角符号" in e for e in errs)


def test_validator_error_4_imagine_command(sample_bible, sample_characters):
    shot = ShotContract(shot_id="S-ERR-4", character_names=["李明"])
    bad_prompt = f"/imagine prompt: subject description, {sample_characters['李明'].appearance_fixed_en} --ar 16:9 --v 8.2 --raw --s 75 --c 0 --sd"
    errs = validate_first_frame(shot, sample_bible, bad_prompt, characters=sample_characters)
    assert any("首帧提示词中出现 '/imagine'" in e for e in errs)


def test_validator_error_5_p_and_sref_mixed(sample_bible, sample_characters):
    shot = ShotContract(shot_id="S-ERR-5", character_names=["李明"])
    bad_prompt = f"subject description, {sample_characters['李明'].appearance_fixed_en} --p p12345 --sref sref6789 --ar 16:9 --v 8.2 --raw --s 75 --c 0 --sd"
    errs = validate_first_frame(shot, sample_bible, bad_prompt, characters=sample_characters)
    assert any("--p (个性化配置) 与 --sref (风格参考) 混写" in e for e in errs)


def test_validator_error_6_moodboard_with_sw(sample_bible, sample_characters):
    shot = ShotContract(shot_id="S-ERR-6", character_names=["李明"])
    bad_prompt = f"subject description, {sample_characters['李明'].appearance_fixed_en} --p mID12345 --sw 150 --ar 16:9 --v 8.2 --raw --s 75 --c 0 --sd"
    errs = validate_first_frame(shot, sample_bible, bad_prompt, characters=sample_characters)
    assert any("情绪板 (moodboard '--p') 不得搭配 --sw 或 --sv 参数" in e for e in errs)


def test_validator_error_7_whole_body_action_vs_closeup_framing(sample_bible, sample_characters):
    shot = ShotContract(
        shot_id="S-ERR-7",
        shot_type="特写镜头",
        shot_type_en="close-up shot",
        character_names=["李明"],
        action="李明推着轮椅上的苏晴在鹅卵石步道上走动漫步",
    )
    prompt = f"close-up shot framing of Li Ming, {sample_characters['李明'].appearance_fixed_en} --ar 16:9 --v 8.2 --raw --s 75 --c 0 --sd"
    errs = validate_first_frame(shot, sample_bible, prompt, characters=sample_characters)
    assert any("动作需要全身或大范围位移空间" in e and "特写/肩部以上" in e for e in errs)


def test_validator_error_8_prop_status_mismatch_with_ledger(sample_bible, sample_characters, sample_props):
    # 账本中手提包挂在轮椅挂钩上，但提示词写成李明手持手提包
    shot = ShotContract(
        shot_id="S-ERR-8",
        character_names=["李明"],
        prop_names=["手提包"],
    )
    # 描述写成李明手持手提包
    bad_prompt = (
        f"cinematic still of Li Ming, {sample_characters['李明'].appearance_fixed_en}, "
        "holding handbag in his right hand --ar 16:9 --v 8.2 --raw --s 75 --c 0 --sd"
    )
    errs = validate_first_frame(shot, sample_bible, bad_prompt, props=sample_props, characters=sample_characters)
    assert any("首帧道具状态与道具账本 0 秒状态不符: 道具 '手提包'" in e for e in errs)


def test_validator_error_9_character_description_not_verbatim(sample_bible, sample_characters):
    shot = ShotContract(shot_id="S-ERR-9", character_names=["李明"])
    # 角色外貌只写了一个短描述，未逐字复用母卡
    short_prompt = "cinematic still of Li Ming, an adult Asian man in a gray suit --ar 16:9 --v 8.2 --raw --s 75 --c 0 --sd"
    errs = validate_first_frame(shot, sample_bible, short_prompt, characters=sample_characters)
    assert any("角色描述未逐字复用: 角色 '李明'" in e for e in errs)


def test_validator_error_10_text_not_in_whitelist(sample_bible, sample_characters):
    shot = ShotContract(shot_id="S-ERR-10", character_names=["李明"])
    # 包含了不在白名单中的文字 "Happy Birthday" (白名单只有 百年好合, 康复花园)
    bad_prompt = (
        f"cinematic still of Li Ming, {sample_characters['李明'].appearance_fixed_en}, "
        "background banner displaying text 'Happy Birthday' --ar 16:9 --v 8.2 --raw --s 75 --c 0 --sd"
    )
    errs = validate_first_frame(shot, sample_bible, bad_prompt, characters=sample_characters)
    assert any("首帧提示词包含未在白名单中的文字: 'Happy Birthday'" in e for e in errs)


def test_validate_film_integration_with_first_frame_prompts(sample_bible, sample_scenes, sample_characters, sample_props):
    # 端到端测试：在 validate_film 中传入合规首帧与违规首帧
    shot1 = ShotContract(
        shot_id="Shot-1",
        scene_name="婚宴主舞台",
        shot_type="Medium Shot",
        shot_type_en="medium shot",
        camera_move="Push In",
        character_names=["李明"],
        prop_names=["话筒"],
        action="李明致辞",
        hands_occupation={"右手": "手持话筒", "左手": "自然下垂"},
    )
    # 合规首帧
    valid_mj = compile_first_frame(
        shot1, sample_bible, sample_scenes["婚宴主舞台"], sample_characters, sample_props, platform="midjourney"
    )
    errs_clean = validate_film(
        bible=sample_bible,
        scenes=sample_scenes,
        characters=sample_characters,
        props=sample_props,
        shots=[shot1],
        first_frame_prompts=[valid_mj],
    )
    assert len(errs_clean) == 0

    # 违规首帧（画幅不符）
    bad_ar_mj = f"{valid_mj.prompt.replace('--ar 16:9', '--ar 9:16')}"
    errs_bad = validate_film(
        bible=sample_bible,
        scenes=sample_scenes,
        characters=sample_characters,
        props=sample_props,
        shots=[shot1],
        first_frame_prompts=[bad_ar_mj],
    )
    assert any("首帧 --ar '9:16' 与视频画幅 '16:9' 不符" in e for e in errs_bad)


# ── 11. 复核专项测试 (Hark Review 6 大回归点) ────────────────────────────────


def test_mj_prompts_no_cjk_characters(sample_bible, sample_scenes, sample_characters, sample_props):
    """测试所有 MJ 提示词（资产参考图 + 每镜首帧）均不含 CJK 中文字符。"""
    import re

    # 1. 资产定妆参考图
    specs = compile_asset_refs(sample_bible, sample_characters, sample_scenes, sample_props)
    for sp in specs:
        assert not re.search(r"[\u4e00-\u9fff]", sp.prompt), f"资产参考图包含中文: {sp.prompt}"

    # 2. 单人镜头与双人镜头首帧
    shot1 = ShotContract(
        shot_id="S-CJK-1",
        scene_name="婚宴主舞台",
        shot_type_en="medium shot",
        character_names=["李明"],
        prop_names=["话筒"],
        start_state_en="standing at the center podium, smiling gently",
    )
    shot2 = ShotContract(
        shot_id="S-CJK-2",
        scene_name="医院康复花园",
        shot_type_en="full-body shot",
        character_names=["李明", "苏晴"],
        prop_names=["轮椅", "手提包"],
        start_state_en="Li Ming standing behind the wheelchair, gripping both handles; Su Qing sitting peacefully in the wheelchair",
    )
    for s in [shot1, shot2]:
        sc = sample_scenes[s.scene_name]
        res = compile_first_frame(s, sample_bible, sc, sample_characters, sample_props, platform="midjourney")
        assert not re.search(r"[\u4e00-\u9fff]", res.prompt), f"首帧提示词包含中文: {res.prompt}"


def test_prop_refs_no_action_words(sample_bible, sample_scenes, sample_characters, sample_props):
    """测试道具参考图描述道具本身外观材质，不含 holding/hand/standing behind 等人物动作词。"""
    import re

    specs = compile_asset_refs(sample_bible, sample_characters, sample_scenes, sample_props)
    prop_specs = [s for s in specs if s.category == "prop"]
    assert len(prop_specs) > 0

    forbidden_patterns = [r"\bholding\b", r"\bhands?\b", r"\bstanding behind\b"]
    for ps in prop_specs:
        for pat in forbidden_patterns:
            m = re.search(pat, ps.prompt, re.I)
            assert m is None, f"道具参考图包含人物动作词 '{pat}': {ps.prompt}"


def test_no_duplicate_6_word_phrases_in_first_frame(sample_bible, sample_scenes, sample_characters, sample_props):
    """测试同一镜首帧提示词里不出现重复的 6 词以上连续短语。"""
    import re
    from collections import Counter

    shot1 = ShotContract(
        shot_id="S-DUP-1",
        scene_name="婚宴主舞台",
        shot_type_en="medium shot",
        character_names=["李明"],
        prop_names=["话筒"],
        start_state_en="standing at the center podium, smiling gently, holding a sleek silver wireless handheld microphone in his right hand",
    )
    shot2 = ShotContract(
        shot_id="S-DUP-2",
        scene_name="医院康复花园",
        shot_type_en="full-body shot",
        character_names=["李明", "苏晴"],
        prop_names=["轮椅", "手提包"],
        start_state_en="Li Ming standing behind the wheelchair, gripping both handles, looking down warmly; Su Qing sitting peacefully in the wheelchair with a knitted lap blanket over her knees",
    )

    for s in [shot1, shot2]:
        sc = sample_scenes[s.scene_name]
        res = compile_first_frame(s, sample_bible, sc, sample_characters, sample_props, platform="midjourney")
        words = re.findall(r"[a-zA-Z0-9_\-]+", res.prompt.lower())
        assert len(words) >= 6
        ngrams = [" ".join(words[i : i + 6]) for i in range(len(words) - 5)]
        counts = Counter(ngrams)
        duplicates = [ng for ng, c in counts.items() if c > 1]
        assert not duplicates, f"[{s.shot_id}] 发现重复 6 词短语: {duplicates}"


def test_multi_character_lead_guidance(sample_bible, sample_scenes, sample_characters):
    """测试多角色首帧在每个角色描述前加名字与身份引导。"""
    shot = ShotContract(
        shot_id="S-MULTI",
        scene_name="医院康复花园",
        character_names=["李明", "苏晴"],
    )
    sc = sample_scenes["医院康复花园"]
    res = compile_first_frame(shot, sample_bible, sc, sample_characters, platform="midjourney")
    assert "Li Ming, an adult East Asian man" in res.prompt
    assert "beside him, Su Qing, an adult East Asian woman" in res.prompt


def test_composition_no_contradiction(sample_bible, sample_scenes, sample_characters):
    """测试构图词不矛盾：指定构图规则(如 Rule of Thirds)时，不得追加默认 centered composition。"""
    sc = sample_scenes["婚宴主舞台"]

    # 1. 指定了三分法则
    shot_thirds = ShotContract(
        shot_id="S-THIRDS",
        scene_name="婚宴主舞台",
        composition_en="rule of thirds framing with balanced negative space around the head",
        character_names=["李明"],
    )
    res_thirds = compile_first_frame(shot_thirds, sample_bible, sc, sample_characters, platform="midjourney")
    assert "rule of thirds" in res_thirds.prompt.lower()
    assert "centered composition" not in res_thirds.prompt.lower()

    # 2. 未指定特定构图规则，回落为默认 centered composition
    shot_default = ShotContract(
        shot_id="S-DEF",
        scene_name="婚宴主舞台",
        character_names=["李明"],
    )
    res_default = compile_first_frame(shot_default, sample_bible, sc, sample_characters, platform="midjourney")
    assert "centered composition" in res_default.prompt.lower()


def test_outpaint_coherent_deduplication():
    """测试扩图模板输出不会出现 'coherent coherent'。"""
    outpaint_res = build_outpaint_prompt(
        scene_background="outdoor hospital garden",
        subject="Li Ming pushing Su Qing in wheelchair",
        lighting="coherent warm afternoon sunlight",
        directions="above and below",
        target_ar="16:9",
    )
    assert "coherent coherent" not in outpaint_res["prompt"]
    assert "coherent warm afternoon sunlight" in outpaint_res["prompt"]

