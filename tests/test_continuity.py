"""连续性与导演词表模块单测 (CONT-1017)。

真实调用，无 mock。覆盖：
1. 每平台输出差异 (h3, seedance/muse, veo, runway, generic)
2. 语言锁存在性与有效性校验
3. 角色母卡外貌描述逐字复用与防短锚点校验
4. 多角色各自独立完整描述(修掉老代码共享单 anchor 穿帮)
5. 道具与手部占用冲突校验(抓到“双手推轮椅同时手提包”)
6. 跨镜头起始/结束状态衔接校验(start_state != end_state)
7. post_only 技法(剪辑类、眩晕变焦、甩镜等)禁止进生成提示词
8. 一镜多运镜约束校验
9. 无配乐段输出“无音乐”，不再私加默认 BGM
10. 对白字数与时长预算校验
11. 画内文字白名单约束校验
12. 16 项审片清单生成
"""

from __future__ import annotations

import pytest

from hevi.prompt.continuity import (
    CharacterCard,
    FilmBible,
    PropItem,
    PropLedger,
    SceneCard,
    ShotContract,
    ShotDialogue,
    VoiceCard,
    compile_continuity_prompt,
    find_post_only_violations,
    is_post_only,
    review_checklist,
    validate_film,
)


@pytest.fixture
def sample_bible() -> FilmBible:
    return FilmBible(
        title="测试剧目",
        style_is=["电影感叙事", "自然写实"],
        style_is_not=["廉价网剧", "低俗短视频"],
        language="zh-普通话",
        language_lock="全部对白与背景人声只说普通话，禁止日语或其他语言；画面不出现文字",
        text_whitelist=["百年好合", "静音"],
        color_grading_baseline="暖金胶片色调",
    )


@pytest.fixture
def sample_characters() -> list[CharacterCard]:
    c1 = CharacterCard(
        s_no=1,
        name="李明",
        appearance_fixed="30岁青年男子，平头短发，面部轮廓分明，左眉微挑，身穿深灰毛呢西装内搭白衬衫系黑领结，左胸佩戴白玫瑰襟花",
        voice_card=VoiceCard(
            gender_age="30岁男性",
            pitch="中低音",
            speed="每秒3.5字",
            timbre="醇厚低沉",
            accent="标准普通话",
            reverb="室内微混响",
        ),
        daily_states={"D1": "西装笔挺，面带微笑"},
    )
    c2 = CharacterCard(
        s_no=2,
        name="苏晴",
        appearance_fixed="28岁年轻女子，黑亮长发盘起戴珍珠发夹，鹅蛋脸，明眸浅笑，身穿米白色缎面露肩婚纱，锁骨处佩戴单颗钻石细项链",
        voice_card=VoiceCard(
            gender_age="28岁女性",
            pitch="清亮温和",
            speed="每秒3.2字",
            timbre="柔和细腻",
            accent="标准普通话",
            reverb="室内微混响",
        ),
        daily_states={"D1": "婚纱圣洁，佩戴珍珠发饰"},
    )
    return [c1, c2]


@pytest.fixture
def sample_scene() -> SceneCard:
    return SceneCard(
        scene_name="婚礼主厅",
        description="华丽水晶吊灯，主舞台红地毯",
        top_down_blocking="新郎站画左(-1, 0)，新娘站画中(0, 0)",
        axis="新郎与新娘水平对视轴线",
        reverse_angle_background="反打方向为宴会主桌与落地窗",
        lighting="Three-Point / 侧光45度 / 3200K暖白",
        lens="50mm / f2.0 / 视平高度1.6米",
        ambient_noise="宴会厅平稳轻微人声低语与杯盏声",
        music_policy="无音乐",
    )


# ── 测试 1: 每平台输出差异 ──────────────────────────────────────────────────


def test_platform_output_differences(
    sample_bible: FilmBible,
    sample_characters: list[CharacterCard],
    sample_scene: SceneCard,
):
    shot = ShotContract(
        shot_id="S01",
        scene_name="婚礼主厅",
        shot_type="Medium Close-Up",
        camera_move="Push In",
        character_names=["李明"],
        second_beats=["0-2s: 步入发言台", "2-4s: 拿起麦克风", "4-5s: 望向新娘"],
        dialogue=ShotDialogue(speaker="李明", text="感谢大家光临。", quote_id="q101"),
    )

    # 1. h3: 三段式结构与 <d>[Chinese]
    r_h3 = compile_continuity_prompt(
        sample_bible, sample_scene, sample_characters, None, shot, platform="h3"
    )
    d_h3 = r_h3.to_dict()
    assert "integrated_multimodal_description" in d_h3
    assert "overall_soundscape" in d_h3
    assert "non_diegetic_music" in d_h3
    assert "<d>[Chinese] 感谢大家光临。</d>[q:q101]" in r_h3.prompt
    assert "（S1）李明说道：" in r_h3.prompt

    # 2. veo: 说话人冒号后严禁引号；独立 negative_prompt
    r_veo = compile_continuity_prompt(
        sample_bible, sample_scene, sample_characters, None, shot, platform="veo"
    )
    d_veo = r_veo.to_dict()
    assert "prompt" in d_veo
    assert "negative_prompt" in d_veo
    assert "李明：感谢大家光临。" in r_veo.prompt
    assert "“感谢大家光临”" not in r_veo.prompt
    assert "subtitles" in d_veo["negative_prompt"]

    # 3. seedance / muse: 顺序节拍改写“先…再…最后…”；提供 constraints
    r_seedance = compile_continuity_prompt(
        sample_bible, sample_scene, sample_characters, None, shot, platform="seedance"
    )
    d_seedance = r_seedance.to_dict()
    assert "constraints" in d_seedance
    assert "先步入发言台；再拿起麦克风；最后望向新娘。" in r_seedance.prompt
    assert "0-2s" not in r_seedance.prompt

    # 4. runway: 严禁用否定句，全部转换为肯定句表达
    r_runway = compile_continuity_prompt(
        sample_bible, sample_scene, sample_characters, None, shot, platform="runway"
    )
    assert "不是" not in r_runway.prompt
    assert "电影感叙事" in r_runway.prompt
    assert "全部对话与背景人声严格保持普通话清晰发声" in r_runway.prompt

    # 5. generic: 标准结构
    r_generic = compile_continuity_prompt(
        sample_bible, sample_scene, sample_characters, None, shot, platform="generic"
    )
    assert "李明说道：“感谢大家光临。”" in r_generic.prompt
    assert r_generic.negative_prompt != ""


# ── 测试 2: 语言锁存在性与有效性 ──────────────────────────────────────────


def test_language_lock_enforcement(
    sample_bible: FilmBible,
    sample_characters: list[CharacterCard],
    sample_scene: SceneCard,
):
    shot = ShotContract(shot_id="S02", character_names=["李明"])
    r = compile_continuity_prompt(
        sample_bible, sample_scene, sample_characters, None, shot, platform="h3"
    )
    # 确认提示词包含语言锁
    assert "全部对白与背景人声只说普通话，禁止日语或其他语言；画面不出现文字" in r.prompt

    # 校验器拦截缺少语言锁的圣经
    bad_bible = FilmBible(title="无锁剧目", language_lock="")
    errors = validate_film(bad_bible, [sample_scene], sample_characters, None, [shot])
    assert any("缺少语言锁" in e for e in errors)

    # 校验器拦截未指定普通话的语言锁
    bad_bible2 = FilmBible(title="偏语剧目", language_lock="禁止外语")
    errors2 = validate_film(bad_bible2, [sample_scene], sample_characters, None, [shot])
    assert any("普通话" in e for e in errors2)


# ── 测试 3: 角色母卡外貌描述逐字复用与防短锚点 ────────────────────────────


def test_verbatim_character_description(
    sample_bible: FilmBible,
    sample_characters: list[CharacterCard],
    sample_scene: SceneCard,
):
    c = sample_characters[0]
    shot = ShotContract(shot_id="S03", character_names=["李明"])
    r = compile_continuity_prompt(
        sample_bible, sample_scene, sample_characters, None, shot, platform="generic"
    )
    # 提示词中必须完整逐字包含母卡外貌描述
    assert c.appearance_fixed in r.prompt

    # 若镜头对象偷懒传入短锚点，校验器必须抓出
    shot_with_short_anchor = ShotContract(
        shot_id="S03B",
        character_names=["李明"],
        character_anchor="李明，黑西装",
    )
    errors = validate_film(
        sample_bible, [sample_scene], sample_characters, None, [shot_with_short_anchor]
    )
    assert any("短锚点" in e or "逐字复用" in e for e in errors)


# ── 测试 4: 多角色各自独立完整描述(修掉共享 anchor 穿帮) ───────────────────


def test_multi_character_distinct_descriptions(
    sample_bible: FilmBible,
    sample_characters: list[CharacterCard],
    sample_scene: SceneCard,
):
    shot = ShotContract(
        shot_id="S04",
        character_names=["李明", "苏晴"],
        shot_type="Two-Shot",
    )
    r = compile_continuity_prompt(
        sample_bible, sample_scene, sample_characters, None, shot, platform="h3"
    )

    # 两个角色必须各自拥有独立的母卡描述段，而不是共用一个 anchor
    assert "S1 李明（完整外貌固定描述）：30岁青年男子" in r.prompt
    assert "S2 苏晴（完整外貌固定描述）：28岁年轻女子" in r.prompt
    assert "佩戴单颗钻石细项链" in r.prompt
    assert "佩戴白玫瑰襟花" in r.prompt

    # 两个角色必须各自输出专属音色卡
    assert "【音色卡】李明：" in r.prompt
    assert "【音色卡】苏晴：" in r.prompt
    assert "中低音" in r.prompt
    assert "清亮温和" in r.prompt


# ── 测试 5: 道具手部占用冲突校验(双手推轮椅同时手提包) ───────────────────


def test_prop_hand_conflict_detection(
    sample_bible: FilmBible,
    sample_characters: list[CharacterCard],
    sample_scene: SceneCard,
):
    # 冲突场景：李明双手推轮椅，却在左手提女式包
    p1 = PropItem(prop_name="折叠轮椅", holder="李明", placement="双手推轮椅")
    p2 = PropItem(prop_name="女式黑皮手提包", holder="李明", placement="左手提包")
    ledger = PropLedger(items=[p1, p2])

    shot_conflict = ShotContract(
        shot_id="S05",
        character_names=["李明"],
        prop_names=["折叠轮椅", "女式黑皮手提包"],
        hands_occupation={"李明": "双手推轮椅，左手提包"},
    )
    errors = validate_film(
        sample_bible, [sample_scene], sample_characters, ledger, [shot_conflict]
    )
    assert any("道具手部冲突" in e for e in errors)
    assert any("双手推轮椅同时持手提包" in e or "双手已被占用" in e for e in errors)

    # 合法场景：手提包挂在轮椅挂钩，双手只推轮椅
    p2_fixed = PropItem(prop_name="女式黑皮手提包", holder="折叠轮椅", placement="挂在轮椅挂钩")
    ledger_fixed = PropLedger(items=[p1, p2_fixed])
    shot_valid = ShotContract(
        shot_id="S05_OK",
        character_names=["李明"],
        prop_names=["折叠轮椅", "女式黑皮手提包"],
        hands_occupation={"李明": "双手平稳握住轮椅把手"},
    )
    errors_fixed = validate_film(
        sample_bible, [sample_scene], sample_characters, ledger_fixed, [shot_valid]
    )
    assert not any("道具手部冲突" in e for e in errors_fixed)


# ── 测试 6: 跨镜头起始/结束状态衔接校验(start_state != end_state) ──────────


def test_start_end_state_continuity_validation(
    sample_bible: FilmBible,
    sample_characters: list[CharacterCard],
    sample_scene: SceneCard,
):
    shot_a = ShotContract(
        shot_id="S06A",
        end_state={"杯中液位": "半杯红酒", "佩戴": "领结端正"},
    )
    # 状态不匹配
    shot_b_bad = ShotContract(
        shot_id="S06B",
        start_state={"杯中液位": "空杯", "佩戴": "领结歪斜"},
    )
    errors = validate_film(
        sample_bible, [sample_scene], sample_characters, None, [shot_a, shot_b_bad]
    )
    assert any("状态衔接穿帮" in e and "杯中液位" in e for e in errors)
    assert any("状态衔接穿帮" in e and "佩戴" in e for e in errors)

    # 状态匹配
    shot_b_good = ShotContract(
        shot_id="S06B_OK",
        start_state={"杯中液位": "半杯红酒", "佩戴": "领结端正"},
    )
    errors_ok = validate_film(
        sample_bible, [sample_scene], sample_characters, None, [shot_a, shot_b_good]
    )
    assert not any("状态衔接穿帮" in e for e in errors_ok)


# ── 测试 7: post_only 技法被拦 ──────────────────────────────────────────


def test_post_only_techniques_blocked(
    sample_bible: FilmBible,
    sample_characters: list[CharacterCard],
    sample_scene: SceneCard,
):
    # Dolly Zoom、Whip Pan、Roll、Split-Screen、Jump Cut 等只能进剪辑单
    assert is_post_only("Dolly Zoom")
    assert is_post_only("Whip Pan")
    assert is_post_only("Roll")
    assert is_post_only("Split-Screen")
    assert is_post_only("Jump Cut")
    assert is_post_only("Cross Dissolve")
    assert is_post_only("Freeze Frame")
    assert is_post_only("Montage")
    assert is_post_only("Slow Motion")

    # 正常运镜不应是 post_only
    assert not is_post_only("Dolly")
    assert not is_post_only("Pan")
    assert not is_post_only("Push In")
    assert not is_post_only("Steadicam")

    # 违规镜头 1: 运镜用了 Dolly Zoom
    shot_dz = ShotContract(shot_id="S07_DZ", camera_move="Dolly Zoom")
    err_dz = validate_film(sample_bible, [sample_scene], sample_characters, None, [shot_dz])
    assert any("post_only" in e for e in err_dz)

    # 违规镜头 2: 动作写了 Jump Cut
    shot_jc = ShotContract(shot_id="S07_JC", action="人物跳切位移到门口")
    err_jc = validate_film(sample_bible, [sample_scene], sample_characters, None, [shot_jc])
    assert any("post_only" in e for e in err_jc)

    # 违规镜头 3: 景别用了 Split-Screen
    shot_ss = ShotContract(shot_id="S07_SS", shot_type="Split-Screen")
    err_ss = validate_film(sample_bible, [sample_scene], sample_characters, None, [shot_ss])
    assert any("post_only" in e for e in err_ss)


# ── 测试 8: 一镜多运镜约束校验 ────────────────────────────────────────────


def test_single_camera_movement_per_shot(
    sample_bible: FilmBible,
    sample_characters: list[CharacterCard],
    sample_scene: SceneCard,
):
    # 违规：Dolly and Pan
    shot_multi = ShotContract(shot_id="S08_MULTI", camera_move="Dolly, Pan")
    errors = validate_film(sample_bible, [sample_scene], sample_characters, None, [shot_multi])
    assert any("一镜多运镜违规" in e for e in errors)

    # 合规：单一运镜 Steadicam
    shot_single = ShotContract(shot_id="S08_SINGLE", camera_move="Steadicam")
    errors_ok = validate_film(sample_bible, [sample_scene], sample_characters, None, [shot_single])
    assert not any("一镜多运镜违规" in e for e in errors_ok)


# ── 测试 9: 无配乐段输出“无音乐”，不私加默认配乐 ────────────────────────────


def test_no_music_policy_enforcement(
    sample_bible: FilmBible,
    sample_characters: list[CharacterCard],
):
    # 场景明确规定 music_policy="无音乐"
    scene_no_music = SceneCard(
        scene_name="严肃对白场景",
        music_policy="无音乐",
        ambient_noise="空旷房间低微风声",
    )
    shot = ShotContract(shot_id="S09")

    r = compile_continuity_prompt(
        sample_bible, scene_no_music, sample_characters, None, shot, platform="h3"
    )
    assert r.music == "无音乐"
    assert r.non_diegetic_music == "无音乐"
    assert "轻柔的氛围音乐" not in r.music

    # 场景有明确配乐时保留
    scene_with_music = SceneCard(
        scene_name="高潮场景",
        music_policy="小提琴慢板优美独奏",
    )
    r2 = compile_continuity_prompt(
        sample_bible, scene_with_music, sample_characters, None, shot, platform="h3"
    )
    assert r2.music == "小提琴慢板优美独奏"


# ── 测试 10: 对白字数与时长预算校验 ───────────────────────────────────────


def test_dialogue_duration_budget_check(
    sample_bible: FilmBible,
    sample_characters: list[CharacterCard],
    sample_scene: SceneCard,
):
    # 3 秒短镜头放了过长台词(45字)
    shot_overbudget = ShotContract(
        shot_id="S10_LONG",
        duration_s=3.0,
        dialogue=ShotDialogue(
            speaker="李明",
            text="今天是一个特别值得纪念的日子，我们经历了很多艰难险阻才走到今天，感谢现场所有来宾！",
        ),
    )
    errors = validate_film(
        sample_bible, [sample_scene], sample_characters, None, [shot_overbudget]
    )
    assert any("对白超时长预算" in e for e in errors)

    # 4 秒放短句(10字) -> 合规
    shot_ok = ShotContract(
        shot_id="S10_OK",
        duration_s=4.0,
        dialogue=ShotDialogue(speaker="李明", text="感谢各位的光临。"),
    )
    errors_ok = validate_film(sample_bible, [sample_scene], sample_characters, None, [shot_ok])
    assert not any("对白超时长预算" in e for e in errors_ok)


# ── 测试 11: 画内文字白名单约束校验 ───────────────────────────────────────


def test_on_screen_text_whitelist(
    sample_bible: FilmBible,
    sample_characters: list[CharacterCard],
    sample_scene: SceneCard,
):
    # 白名单内文字 "百年好合"
    shot_allowed = ShotContract(shot_id="S11_ALLOW", on_screen_text=["百年好合"])
    err_ok = validate_film(sample_bible, [sample_scene], sample_characters, None, [shot_allowed])
    assert not any("画内文字未在白名单中" in e for e in err_ok)

    # 白名单外文字 "欢迎光临全聚德"
    shot_forbidden = ShotContract(shot_id="S11_DENY", on_screen_text=["欢迎光临全聚德"])
    err_fail = validate_film(
        sample_bible, [sample_scene], sample_characters, None, [shot_forbidden]
    )
    assert any("画内文字未在白名单中" in e for e in err_fail)


# ── 测试 12: 16 项逐镜审片清单生成 ─────────────────────────────────────────


def test_16_item_review_checklist(sample_characters: list[CharacterCard]):
    shot = ShotContract(
        shot_id="S12_CK",
        scene_name="婚礼主厅",
        character_names=["李明", "苏晴"],
        prop_names=["麦克风"],
        dialogue=ShotDialogue(speaker="李明", text="誓言如初。"),
    )
    checklist = review_checklist(shot)
    assert len(checklist) == 16

    categories = [it.category for it in checklist]
    expected_categories = [
        "脸和身形",
        "服装",
        "道具和手",
        "视线和轴线",
        "出入画方向",
        "剪辑点动作匹配",
        "光线",
        "背景和布景",
        "语言",
        "音色",
        "口型",
        "画面文字",
        "物理",
        "表演情绪",
        "声音",
        "记录",
    ]
    assert categories == expected_categories

    # 验证 research.md 中标注适合 VLM 粗筛的项: 6/8/10/14
    vlm_screenable_indices = [
        it.item_no for it in checklist if it.vlm_screenable
    ]
    assert vlm_screenable_indices == [6, 8, 10, 14]


# ── 测试 13: 闪回镜头服装与不变身体特征解耦，不含婚礼服装词 ───────────────


def test_flashback_wardrobe_separation_no_wedding_clothes(sample_bible: FilmBible):
    groom = CharacterCard(
        s_no=1,
        name="李明",
        body_fixed="30岁成年东亚男子，面部轮廓分明，浓眉短发微卷，右眉角有浅淡旧疤痕",
        wardrobes={
            "D1": "身穿深灰色定制西装，内搭挺括白衬衫与深黑领结，左胸佩戴白玫瑰襟花",
            "D_flashback": "身穿浅蓝色薄针织衫与深灰运动长裤，脚穿白色平底布鞋",
        },
    )
    bride = CharacterCard(
        s_no=2,
        name="苏晴",
        body_fixed="28岁东亚女子，鹅蛋脸，皮肤白皙，深棕色柔顺长发，杏眼清亮带笑意",
        wardrobes={
            "D1": "长发盘起戴珍珠耳钉，身穿米白色露肩缎面轻婚纱配银细吊坠项链",
            "D_flashback": "扎简单低马尾，身穿棉质条纹病服外套，膝盖覆浅粉色针织小毛毯",
        },
    )
    scene_hospital = SceneCard(scene_name="康复花园")
    shot_flashback = ShotContract(
        shot_id="S13_FB",
        scene_name="康复花园",
        character_names=["李明", "苏晴"],
        story_day="D_flashback",
    )

    r = compile_continuity_prompt(
        sample_bible, scene_hospital, [groom, bride], None, shot_flashback, platform="generic"
    )

    # 1. 必须包含闪回故事日的服装
    assert "浅蓝色薄针织衫" in r.prompt
    assert "棉质条纹病服外套" in r.prompt

    # 2. 严禁出现婚宴故事日的服装配饰词（彻底杜绝同镜两套衣服穿帮）
    wedding_forbidden_words = ["西装", "领结", "襟花", "婚纱", "珍珠耳钉"]
    for word in wedding_forbidden_words:
        assert word not in r.prompt, f"Flashback prompt should not contain wedding clothing word: {word}"


# ── 测试 14: 音色卡空间混响由 SceneCard 动态覆盖，音色本体跨镜稳定 ───────────


def test_scene_reverb_overrides_voice_card(sample_bible: FilmBible):
    actor = CharacterCard(
        s_no=1,
        name="李明",
        appearance_fixed="30岁成年男子",
        voice_card=VoiceCard(
            gender_age="30岁青年男性",
            pitch="中低音沉稳",
            speed="每秒约3.2字",
            timbre="温和醇厚沙哑磁性",
            accent="标准普通话",
            reverb="默认微混响",
        ),
    )
    # 场景 1: 宴会厅
    scene_hall = SceneCard(scene_name="宴会厅", reverb="中等宴会厅大空间混响")
    shot1 = ShotContract(shot_id="S14_A", character_names=["李明"])
    r1 = compile_continuity_prompt(
        sample_bible, scene_hall, [actor], None, shot1, platform="h3"
    )
    assert "中等宴会厅大空间混响" in r1.prompt
    assert "温和醇厚沙哑磁性" in r1.prompt

    # 场景 2: 室外花园（室外自然声，无室内混响）
    scene_outdoor = SceneCard(scene_name="室外花园", reverb="室外开阔自然声自然衰减无室内混响")
    shot2 = ShotContract(shot_id="S14_B", character_names=["李明"])
    r2 = compile_continuity_prompt(
        sample_bible, scene_outdoor, [actor], None, shot2, platform="h3"
    )
    assert "室外开阔自然声自然衰减无室内混响" in r2.prompt
    assert "中等宴会厅大空间混响" not in r2.prompt
    # 音色本体跨镜完全一致
    assert "温和醇厚沙哑磁性" in r2.prompt
    assert "中低音沉稳" in r2.prompt


# ── 测试 15: Runway 输出严格全肯定句，不含任何否定词 ──────────────────────────


def test_runway_positive_phrasing_strictly_no_negatives(
    sample_bible: FilmBible,
    sample_characters: list[CharacterCard],
    sample_scene: SceneCard,
):
    shot = ShotContract(
        shot_id="S15_RUNWAY",
        scene_name="婚礼主厅",
        shot_type="Medium",
        camera_move="Push In",
        character_names=["李明"],
        second_beats=["0-2s: 步入发言台", "2-4s: 拿起麦克风"],
        dialogue=ShotDialogue(speaker="李明", text="感谢各位来宾。", is_in_frame=False),
    )
    r_runway = compile_continuity_prompt(
        sample_bible, sample_scene, sample_characters, None, shot, platform="runway"
    )

    # 验证 runway 输出的 prompt 中绝对不含任何常见否定词
    forbidden_negatives = ["无", "不要", "禁止", "严禁", "避免", "没有", "不得"]
    for neg in forbidden_negatives:
        assert neg not in r_runway.prompt, f"Runway prompt must not contain negative word '{neg}'"

    # 验证音乐字段改为了肯定或仅环境声表达
    assert r_runway.music == "仅环境声"


# ── 测试 16: post_only 中文常见别名/同义词全量拦截 ──────────────────────────


def test_post_only_chinese_synonyms_intercepted():
    synonyms = [
        "眩晕变焦",
        "希区柯克变焦",
        "甩镜头",
        "急摇",
        "叠化",
        "慢动作",
        "延时摄影",
        "定格",
        "蒙太奇",
        "平行剪辑",
    ]
    for syn in synonyms:
        violations = find_post_only_violations(syn)
        assert len(violations) > 0, f"Expected post_only violation for synonym: {syn}"


# ── 测试 17: Seedance 顺序节拍改写不出现双句号 ─────────────────────────────


def test_seedance_sequential_beats_no_double_periods(
    sample_bible: FilmBible,
    sample_characters: list[CharacterCard],
    sample_scene: SceneCard,
):
    shot = ShotContract(
        shot_id="S17_SEEK",
        scene_name="婚礼主厅",
        character_names=["李明"],
        second_beats=["0-2s: 缓步走上台", "2-4s: 拿起麦克风", "4-5s: 望向全场"],
    )
    r_seedance = compile_continuity_prompt(
        sample_bible, sample_scene, sample_characters, None, shot, platform="seedance"
    )
    # 动作行格式检查：绝不出现“。。”
    assert "。。" not in r_seedance.prompt
    assert "先缓步走上台；再拿起麦克风；最后望向全场。" in r_seedance.prompt
