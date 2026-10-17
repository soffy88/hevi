"""婚宴致辞 + 闪回推轮椅 连续性导演编排与防穿帮演示 (CONT-1017)。

演示场景：
1. Shot 1 (婚宴现场): 新郎李明在婚宴台上发表致辞，深情回忆过去。
2. Shot 2 (闪回记忆): 闪回三年前医院花园，新郎推着轮椅上的新娘苏晴。
   - 构造【穿帮冲突】：新郎双手推轮椅的同时，道具与手部被错误分配了持手提包(推轮椅掉包)。
3. 校验器运行：准确捕获“双手推轮椅同时持手提包”冲突与状态断层。
4. 修复与二次校验：将手提包挂在轮椅挂钩上，校验通过(0 errors)。
5. 多平台提示词编译输出(h3, seedance, veo, runway, generic)。
6. 16项审片清单生成。
"""

from __future__ import annotations

import os
import sys

# 确保本 repo 根目录在 python 搜索路径中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
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
    review_checklist,
    validate_film,
)


def run_demo() -> None:
    print("=" * 80)
    print("hevi 连续性编译器与导演词表防穿帮系统 DEMO (CONT-1017)")
    print("=" * 80)

    # ── 1. 建立整片圣经 (FilmBible) ─────────────────────────────────────────
    bible = FilmBible(
        title="爱在时光里",
        aspect_ratio="16:9",
        style_is=["电影质感院线叙事短片", "温暖质朴现实主义"],
        style_is_not=["廉价网剧", "夸张短视频滤镜", "悬浮都市剧"],
        language="zh-普通话",
        language_lock="全部对白与背景人声只说普通话，禁止日语或其他语言；画面不出现文字",
        text_whitelist=["百年好合", "康复花园"],
        genre_preset="Drama",
        color_grading_baseline="暖金胶片色调，暗部深邃不偏色，肤色通透自然",
        native_audio_strategy="原生音频仅作口型参考全部替换；全片铺连续环境底噪",
    )

    # ── 2. 建立角色母卡 (CharacterCard) ─────────────────────────────────────
    # 不变身体特征（body_fixed）与故事日服装（wardrobes）严格解耦，防止换装矛盾
    groom = CharacterCard(
        s_no=1,
        name="李明",
        body_fixed=(
            "30岁成年东亚男子，面部棱角分明，短发微卷梳理自然，浓眉，右眉角有一道浅淡旧疤痕，"
            "双眼温和坚定，高鼻梁薄唇，手指修长无饰品。"
        ),
        wardrobes={
            "D1": "身穿深灰色定制羊毛西装外套，内搭纯白挺括衬衫与深黑色领结，左胸佩戴一朵淡香槟色玫瑰襟花。",
            "D_flashback": "身穿浅蓝色薄针织衫与深灰运动长裤，脚穿白色平底休闲布鞋。",
        },
        voice_card=VoiceCard(
            gender_age="30岁青年男性",
            pitch="中低音沉稳",
            speed="每秒约3.2字，句间停顿自然",
            timbre="温和醇厚、略带沙哑磁性",
            accent="标准普通话，咬字清晰",
        ),
        daily_states={
            "D1": "婚宴正日：精神饱满，气色极佳",
            "D_flashback": "三年前回忆：眼神略显憔悴但温柔专注",
        },
    )

    bride = CharacterCard(
        s_no=2,
        name="苏晴",
        body_fixed=(
            "28岁东亚女子，鹅蛋脸，皮肤白皙，深棕色柔顺长发，杏眼清亮带笑意，眉形柔和，浅粉色唇膏。"
        ),
        wardrobes={
            "D1": "深棕长发高雅盘起，戴精巧单颗珍珠耳钉，身穿米白色露肩缎面轻婚纱，裙摆绣有淡暗纹银丝，锁骨戴细银吊坠项链。",
            "D_flashback": "扎简单低马尾，穿着棉质病服外套，膝盖覆着浅粉色针织保暖小毛毯。",
        },
        voice_card=VoiceCard(
            gender_age="28岁年轻女性",
            pitch="清亮中音",
            speed="轻柔舒缓",
            timbre="柔和纯净甜美",
            accent="标准普通话",
        ),
        daily_states={
            "D1": "婚宴正日：气色红润，容光焕发",
            "D_flashback": "三年前回忆：坐在轮椅上，身体虚弱康复中",
        },
    )

    characters = [groom, bride]

    # ── 3. 建立场景母卡 (SceneCard) ─────────────────────────────────────────
    # 空间混响由 SceneCard 决定（宴会厅有混响，室外花园无室内混响）
    scene_wedding = SceneCard(
        scene_name="宴会主厅",
        description="五星级酒店宏大宴会厅，水晶吊灯高悬，主舞台后方为暖金暗红纱幔",
        top_down_blocking="主发言台位于画中微偏左(-0.5, 0)，新郎站于立式麦克风后",
        axis="主轴线：新郎面向全场观众，视线水平看向台下宾客席",
        reverse_angle_background="反打背景为座无虚席的圆形宴会桌与深远暖光大门",
        lighting="Three-Point / 侧逆主光45度 / 3200K暖白钨丝灯感 / 柔光漫射",
        lens="85mm / f2.0 / 视平高度1.65米单人浅景深",
        ambient_noise="宴会大厅平稳轻微人声低语、玻璃杯轻微碰撞声，声音平稳连贯",
        reverb="中等宴会厅空间混响",
        music_policy="无音乐",  # 明确无音乐
    )

    scene_hospital = SceneCard(
        scene_name="康复花园",
        description="三年前阳光微醺的医院康复石子小径，两侧盛开黄色金丝桃灌木",
        top_down_blocking="小径自画右下向画左上延伸，轮椅位于小径中央，新郎站于轮椅后方双手把位",
        axis="运动轴线：自右向左前行，摄影机位于小径侧前方",
        reverse_angle_background="反打方向为老式红砖康复大楼与落叶林荫道",
        lighting="Natural / 傍晚低角度暖金逆光 / 4500K柔和漫射",
        lens="50mm / f2.8 / 移动推拉稳定器视角",
        ambient_noise="午后微风吹过树叶沙沙声，远处偶有一声鸟鸣",
        reverb="室外开阔花园自然声，自然衰减无室内混响",
        music_policy="无音乐",
    )

    # ── 4. 建立初始道具账本 (含穿帮冲突) ─────────────────────────────────
    wheelchair = PropItem(
        prop_name="折叠轮椅",
        holder="李明",
        placement="双手推轮椅",
        start_state="正常推行在石子路",
        end_state="停在长椅旁",
    )
    handbag_conflict = PropItem(
        prop_name="女式黑皮手提包",
        holder="李明",
        placement="左手提",  # 冲突！李明双手在推轮椅，又在左手提包
        start_state="手提包提在手里",
        end_state="手提包掉落",
    )
    props_with_conflict = PropLedger(items=[wheelchair, handbag_conflict])

    # ── 5. 构造镜头契约 (Shot 1 与包含冲突的 Shot 2) ────────────────────────
    shot1 = ShotContract(
        shot_id="Shot-01",
        scene_name="宴会主厅",
        shot_type="Medium Close-Up",
        camera_move="Push In",
        composition="Rule of Thirds",
        eyeline_angle="视线平视微偏左台下观众",
        second_beats=["0-2s: 望向全场深呼吸", "2-4s: 手握麦克风动情致辞", "4-5s: 眼神转向侧台回忆"],
        dialogue=ShotDialogue(
            speaker="李明",
            text="三年前在康复花园，我知道会走完一生。",
            is_in_frame=True,
            lip_sync_locked=True,
            quote_id="wedding_speech_01",
        ),
        hands_occupation={"李明": "右手握立式麦克风杆，左手自然垂于身侧"},
        character_names=["李明"],
        prop_names=[],
        duration_s=5.0,
        story_day="D1",
        start_state={"场景": "婚宴台", "闪回转场": "视线定格切入三年前康复小径", "回忆心境": "深情凝望"},
        end_state={"闪回转场": "视线定格切入三年前康复小径", "回忆心境": "深情凝望"},
    )

    # 镜头 2 (错误示范：推轮椅同时手持手提包 + 一镜多运镜 Dolly and Pan + 状态衔接穿帮)
    shot2_flawed = ShotContract(
        shot_id="Shot-02",
        scene_name="康复花园",
        shot_type="Tracking Shot Framing",
        camera_move="Dolly, Pan",  # 违规：一镜多运镜
        composition="Leading Lines",
        eyeline_angle="新郎视线俯视轮椅上新娘，新娘仰视前方",
        second_beats=["0-3s: 沿小径慢推轮椅", "3-5s: 停步整理毛毯"],
        dialogue=ShotDialogue(
            speaker="苏晴",
            text="累不累？要不坐下来歇会儿。",
            is_in_frame=True,
            lip_sync_locked=True,
        ),
        # 冲突：双手推轮椅 + 左手提包！
        hands_occupation={"李明": "双手推轮椅，左手提包"},
        character_names=["李明", "苏晴"],
        prop_names=["折叠轮椅", "女式黑皮手提包"],
        duration_s=5.0,
        story_day="D_flashback",
        start_state={"闪回转场": "错误切入室内病房", "回忆心境": "突发焦虑"},  # 状态断层
        end_state={"闪回转场": "停于长椅边", "回忆心境": "宁静"},
    )

    print("\n[STEP 1] 运行校验器检查带穿帮数据 (validate_film)...")
    errors = validate_film(
        bible=bible,
        scenes=[scene_wedding, scene_hospital],
        characters=characters,
        props=props_with_conflict,
        shots=[shot1, shot2_flawed],
    )

    print(f"-> 发现 {len(errors)} 个导演纪律与穿帮错误：")
    for i, err in enumerate(errors, 1):
        print(f"   {i}. {err}")

    assert len(errors) > 0, "Expected errors to be detected!"

    # ── 6. 修复错误：修正运镜为单一运镜，修正道具手部占用 ─────────────────
    print("\n[STEP 2] 修复穿帮错误：运镜改为单一 'Tracking'，手提包持有人为李明但放置于轮椅右把手挂钩...")
    handbag_fixed = PropItem(
        prop_name="女式黑皮手提包",
        holder="李明",
        placement="挂在轮椅右把手挂钩",
        start_state="稳固悬挂于轮椅右把手挂钩",
        end_state="稳固悬挂",
    )
    props_fixed = PropLedger(items=[wheelchair, handbag_fixed])

    shot2_fixed = ShotContract(
        shot_id="Shot-02",
        scene_name="康复花园",
        shot_type="Tracking Shot Framing",
        camera_move="Tracking",  # 修复为单一运镜
        composition="Leading Lines",
        eyeline_angle="新郎视线俯视轮椅上新娘，新娘仰视前方",
        second_beats=["0-3s: 沿小径慢推轮椅", "3-5s: 停步微俯身微笑"],
        dialogue=ShotDialogue(
            speaker="苏晴",
            text="累不累？要不歇会儿。",
            is_in_frame=True,
            lip_sync_locked=True,
        ),
        hands_occupation={"李明": "双手平稳握住轮椅推行把手"},  # 修复手部
        character_names=["李明", "苏晴"],
        prop_names=["折叠轮椅", "女式黑皮手提包"],
        duration_s=4.0,
        story_day="D_flashback",
        start_state={"闪回转场": "视线定格切入三年前康复小径", "回忆心境": "深情凝望"},  # 状态衔接一致
        end_state={"闪回转场": "停于长椅边", "回忆心境": "宁静"},
    )

    fixed_errors = validate_film(
        bible=bible,
        scenes=[scene_wedding, scene_hospital],
        characters=characters,
        props=props_fixed,
        shots=[shot1, shot2_fixed],
    )
    print(f"-> 修复后校验结果: {len(fixed_errors)} 个错误 (PASS!)")
    assert len(fixed_errors) == 0, f"Expected 0 errors after fix, got: {fixed_errors}"

    # ── 7. 多平台提示词编译输出 ─────────────────────────────────────────────
    print("\n[STEP 3] 编译 Shot-01 (婚礼现场) 与 Shot-02 (闪回推轮椅) 各平台完整提示词输出：")
    platforms = ["h3", "seedance", "veo", "runway", "generic"]

    for shot_item, scene_item in [(shot1, scene_wedding), (shot2_fixed, scene_hospital)]:
        print(f"\n{'#' * 40} {shot_item.shot_id} ({shot_item.scene_name}) {'#' * 40}")
        for plat in platforms:
            render = compile_continuity_prompt(
                bible=bible,
                scene=scene_item,
                characters=characters,
                props=props_fixed,
                shot=shot_item,
                platform=plat,
            )
            print(f"\n--- Platform: [{plat.upper()}] | {shot_item.shot_id} ---")
            out_dict = render.to_dict()
            print(f"Soundscape: {out_dict.get('overall_soundscape') or out_dict.get('soundscape')}")
            print(f"Music: {out_dict.get('non_diegetic_music') or out_dict.get('music')}")
            if "negative_prompt" in out_dict:
                print(f"Negative: {out_dict['negative_prompt']}")
            if "constraints" in out_dict:
                print(f"Constraints: {out_dict['constraints']}")
            p_text = out_dict.get("integrated_multimodal_description") or out_dict.get("prompt", "")
            print("Full Prompt:")
            print(p_text)

    # ── 8. 逐镜审片清单输出 ─────────────────────────────────────────────────
    print("\n[STEP 4] 生成 Shot-02 逐镜 16 项审片清单 (review_checklist)...")
    checklist = review_checklist(shot2_fixed)
    print(f"共生成 {len(checklist)} 项连续性防穿帮核对点：")
    for it in checklist[:5]:
        vlm_tag = "[VLM可粗筛]" if it.vlm_screenable else "[人工核实]"
        print(f"  #{it.item_no:02d} {vlm_tag} {it.category} -> {it.shot_focus}")
    print("  ... 其余 11 项核验点已就绪。")

    print("\n" + "=" * 80)
    print("DEMO 执行完毕！全部连续性与导演词表契约验证通过。")
    print("=" * 80)


if __name__ == "__main__":
    run_demo()
