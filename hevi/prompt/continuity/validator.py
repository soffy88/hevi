"""连续性校验器 —— 拦截一镜多运镜、post_only 技法进提示词、道具手部冲突、状态断层等穿帮。

覆盖 BRIEF_CONT1017 规范：
1. 一镜多运镜 (单一运镜原则)
2. post_only 技法进了生成提示词 (剪辑/眩晕变焦/甩镜等只能进剪辑单)
3. 道具手部冲突 (如双手推轮椅同时持手提包)
4. start_state ≠ 上一镜 end_state (跨镜状态断层)
5. 对白超时长预算 (4 秒放 1-2 句短句，字数超标)
6. 角色描述非逐字一致 (禁止短锚点，必须逐字复用母卡)
7. 缺语言锁 (防止场景文化带偏语言或冒出日文字幕)
8. 画内文字不在白名单 (招牌/道具字必须在白名单内)
"""

from __future__ import annotations

import re
from typing import Any

from hevi.prompt.continuity.schemas import (
    CharacterCard,
    FilmBible,
    PropItem,
    PropLedger,
    SceneCard,
    ShotContract,
)
from hevi.prompt.continuity.vocab import (
    POST_ONLY_NAMES_EN,
    POST_ONLY_NAMES_ZH,
    find_post_only_violations,
    list_vocab_by_category,
)


def _split_sentences(text: str) -> list[str]:
    """拆分中文/英文句子。"""
    raw = re.split(r"[。！？!?\n]+", text.strip())
    return [s.strip() for s in raw if s.strip()]


def _count_dialogue_chars(text: str) -> int:
    """统计有效汉字与单词数。"""
    return len(re.findall(r"[\u4e00-\u9fa5a-zA-Z0-9]", text))


def validate_film(
    bible: FilmBible,
    scenes: list[SceneCard] | dict[str, SceneCard],
    characters: list[CharacterCard] | dict[str, CharacterCard],
    props: list[PropItem] | dict[str, PropItem] | PropLedger | None,
    shots: list[ShotContract],
    prompts: list[Any] | None = None,
) -> list[str]:
    """全片连续性与导演纪律统一校验，返回错误列表(空列表表示完全合格)。

    Args:
        bible: 全片圣经
        scenes: 场景母卡表
        characters: 角色母卡表
        props: 道具账本
        shots: 镜头契约列表
        prompts: 可选的已编译提示词列表(用于检查提示词正文中的禁词或缺失项)
    """
    errors: list[str] = []

    # 1. 规范化映射
    char_map: dict[str, CharacterCard] = {}
    if isinstance(characters, (list, tuple)):
        for c in characters:
            char_map[c.name] = c
    elif isinstance(characters, dict):
        char_map = characters

    prop_map: dict[str, PropItem] = {}
    if isinstance(props, PropLedger):
        for p in props.items:
            prop_map[p.prop_name] = p
    elif isinstance(props, (list, tuple)):
        for p in props:
            prop_map[p.prop_name] = p
    elif isinstance(props, dict):
        prop_map = props

    # ── 检查项 7: 缺语言锁 ─────────────────────────────────────────────────
    if not bible.language_lock or not bible.language_lock.strip():
        errors.append("FilmBible 缺少语言锁 (language_lock 为空)。必须明确普通话及禁止外语。")
    else:
        lock_text = bible.language_lock
        if "普通话" not in lock_text:
            errors.append(
                f"FilmBible 语言锁缺少对普通话的指定: '{lock_text}'。"
            )
        if "禁止日语" not in lock_text and "禁止其他语言" not in lock_text:
            errors.append(
                f"FilmBible 语言锁缺少排他防污染条款 (必须显式声明禁止日语或其他语言): '{lock_text}'。"
            )

    # 缓存所有运镜词汇供冲突检测
    camera_move_items = list_vocab_by_category("camera_movement")
    camera_move_names = {it.name_en.lower(): it for it in camera_move_items}
    camera_move_names.update({it.name_zh: it for it in camera_move_items})

    # ── 逐镜检查 ───────────────────────────────────────────────────────────
    for idx, shot in enumerate(shots):
        sid = shot.shot_id or f"Shot-{idx+1}"

        # ── 检查项 1: 一镜多运镜 ─────────────────────────────────────────
        # 运镜字段中不得包含多种复合运镜
        cm_text = (shot.camera_move or "").strip()
        if cm_text:
            # 常见多运镜分隔符：逗号、加号、斜杠、顿号、and、兼
            delims = [",", "，", "+", "/", "、", " and ", "兼", "同时", "接着"]
            has_multiple_delims = any(d in cm_text.lower() for d in delims)

            # 按词长从长到短排序优先匹配，避免子词(如 zoom 误匹配 dolly zoom)
            sorted_move_items = sorted(camera_move_items, key=lambda x: len(x.name_en), reverse=True)
            matched_moves: list[str] = []
            remaining_text = cm_text.lower()
            for item in sorted_move_items:
                en_pattern = r"\b" + re.escape(item.name_en.lower()) + r"\b"
                zh_pattern = re.escape(item.name_zh)
                if re.search(en_pattern, remaining_text) or re.search(zh_pattern, remaining_text):
                    if item.name_zh not in matched_moves:
                        matched_moves.append(item.name_zh)
                    # 消除已匹配部分，防止子串重复匹配
                    remaining_text = re.sub(en_pattern, " ", remaining_text)
                    remaining_text = re.sub(zh_pattern, " ", remaining_text)

            if has_multiple_delims or len(matched_moves) > 1:
                errors.append(
                    f"[{sid}] 一镜多运镜违规: 运镜字段 '{cm_text}' 包含多个复合运动 (匹配项:{matched_moves})。"
                    f"AI 生成模型一镜只允许一种运镜。"
                )

        # ── 检查项 2: post_only 技法进了生成提示词 ─────────────────────
        # 检查 shot 字段里的各种技法
        fields_to_check = [
            shot.shot_type,
            shot.camera_move,
            shot.composition,
            shot.transition_in,
            shot.transition_out,
            shot.visual_prompt,
            shot.action,
            " ".join(shot.second_beats),
        ]
        violations = find_post_only_violations(fields_to_check)
        if violations:
            errors.append(
                f"[{sid}] post_only 技法违规进入生成提示词: {', '.join(violations)}。"
                f"此类剪辑/特效技法只能进剪辑单，严禁进入文本生成提示词。"
            )

        # ── 检查项 3: 道具手部冲突 (如双手推轮椅同时手提包) ─────────────
        # 统计每个角色的手部占用
        # 1) 从 shot.hands_occupation 读取
        for char_name, occ_desc in shot.hands_occupation.items():
            occ = occ_desc.strip()
            # 冲突模式 A: "双手推轮椅" 或 "双手..." 同时持有其他手持道具
            is_both_hands_busy = "双手" in occ or "两手" in occ
            if is_both_hands_busy:
                # 检查该角色是否还在拿其他物品
                held_props: list[str] = []
                for p_name in shot.prop_names:
                    p_obj = prop_map.get(p_name)
                    if p_obj and p_obj.holder == char_name:
                        # 检查道具放置位置
                        if any(hw in (p_obj.placement or "") for hw in ["手", "手持", "提", "端", "拿", "左手", "右手"]):
                            held_props.append(f"{p_name}({p_obj.placement})")
                    elif p_name in occ and p_name not in ["轮椅", "方向盘"]:
                        held_props.append(p_name)

                # 也检查描述文本中是否同时出现手部冲突字眼
                conflict_keywords = ["手提包", "包", "咖啡", "杯", "手机", "枪", "花束"]
                for kw in conflict_keywords:
                    if kw in occ and ("推轮椅" in occ or "推车" in occ or "方向盘" in occ):
                        if kw not in held_props:
                            held_props.append(kw)

                if held_props:
                    errors.append(
                        f"[{sid}] 道具手部冲突: 角色 '{char_name}' 处于'{occ}'状态，"
                        f"但同时被分配了手持道具: {', '.join(held_props)}。"
                        f"双手被完全占用时禁止手持其他道具(如双手推轮椅同时持手提包)。"
                    )

            # 冲突模式 B: 单手重复占用
            if "左手" in occ and ("双手" in occ or occ.count("左手") > 1):
                errors.append(f"[{sid}] 道具手部冲突: 角色 '{char_name}' 左手状态异常: '{occ}'。")
            if "右手" in occ and ("双手" in occ or occ.count("右手") > 1):
                errors.append(f"[{sid}] 道具手部冲突: 角色 '{char_name}' 右手状态异常: '{occ}'。")

        # 2) 从 props 账本交叉比对
        for cname in shot.character_names:
            c_props = [p for p in prop_map.values() if p.holder == cname and p.prop_name in shot.prop_names]
            has_two_hand_prop = any("双手" in (p.placement or "") for p in c_props)
            single_hand_props = [p for p in c_props if any(h in (p.placement or "") for h in ["左手", "右手", "手持", "手提"])]
            if has_two_hand_prop and single_hand_props:
                p_names = [p.prop_name for p in single_hand_props]
                errors.append(
                    f"[{sid}] 道具手部冲突: 角色 '{cname}' 道具账本中双手已被占用，"
                    f"却同时手持道具 {p_names}。"
                )

        # ── 检查项 4: start_state ≠ 上一镜 end_state ───────────────────
        if idx > 0:
            prev_shot = shots[idx - 1]
            prev_end = prev_shot.end_state
            curr_start = shot.start_state

            if prev_end and curr_start:
                # 均有显式声明时对比
                if isinstance(prev_end, dict) and isinstance(curr_start, dict):
                    # 检查重合 key 的值是否一致
                    for k in set(prev_end.keys()) & set(curr_start.keys()):
                        if prev_end[k] != curr_start[k]:
                            errors.append(
                                f"[{sid}] 状态衔接穿帮: 属性 '{k}' 的起始状态 ({curr_start[k]}) "
                                f"与上一镜 [{prev_shot.shot_id}] 的结束状态 ({prev_end[k]}) 不一致。"
                            )
                else:
                    if str(prev_end).strip() != str(curr_start).strip():
                        errors.append(
                            f"[{sid}] 状态衔接穿帮: 当前镜 start_state '{curr_start}' "
                            f"与上一镜 [{prev_shot.shot_id}] end_state '{prev_end}' 不一致。"
                        )

        # ── 检查项 5: 对白超时长预算 (约 4 秒 1–2 句短句) ──────────────
        all_dialogues: list[Any] = []
        if shot.dialogue and shot.dialogue.text:
            all_dialogues.append(shot.dialogue)
        if shot.dialogue_lines:
            for dl in shot.dialogue_lines:
                if dl and dl.text and dl not in all_dialogues:
                    all_dialogues.append(dl)

        for d in all_dialogues:
            d_text = d.text.strip()
            sents = _split_sentences(d_text)
            char_count = _count_dialogue_chars(d_text)
            duration = shot.duration_s or 4.0

            # 4 秒短镜头规则 (Sora cookbook / Veo best-practice)
            if duration <= 4.0:
                if len(sents) > 2:
                    errors.append(
                        f"[{sid}] 对白超时长预算: 片长仅 {duration} 秒，对白包含 {len(sents)} 句句子 "
                        f"('{d_text}')。4 秒短镜头最多容纳 1–2 句短句。"
                    )
                if char_count > 25:
                    errors.append(
                        f"[{sid}] 对白超时长预算: 片长仅 {duration} 秒，对白字数达到 {char_count} 字 "
                        f"('{d_text}')。按标准语速(约3.5字/秒)严重超标(上限25字)。"
                    )

            # 通用时长预算比对 (语速估算: 约 3.5 字/秒)
            est_seconds = char_count / 3.5
            budget_limit = d.max_duration_budget_s or duration
            if est_seconds > budget_limit * 1.15:  # 允许 15% 浮动容差
                errors.append(
                    f"[{sid}] 对白超时长预算: 对白字数 {char_count} 字预估需要 {est_seconds:.1f} 秒，"
                    f"超出本镜预算 {budget_limit:.1f} 秒。"
                )

        # ── 检查项 6: 角色描述非逐字一致 (禁止短锚点) ─────────────────
        for cname in shot.character_names:
            char_card = char_map.get(cname)
            if not char_card:
                continue

            fixed = char_card.appearance_fixed.strip()
            # 如果 shot 自身带有 character_anchor 或 character_desc
            anchor = getattr(shot, "character_anchor", "") or ""
            if anchor and anchor != fixed:
                # 判断是否只给了短锚点
                if len(anchor) < len(fixed) * 0.7:
                    errors.append(
                        f"[{sid}] 角色描述非逐字一致: 角色 '{cname}' 给出了短锚点 '{anchor}'，"
                        f"未逐字复用母卡完整描述(必须逐字复用 {len(fixed)} 字完整固定描述)。"
                    )

        # ── 检查项 8: 画内文字不在白名单 ───────────────────────────────
        whitelist = bible.text_whitelist or []
        for txt in shot.on_screen_text:
            t = txt.strip()
            if t and t not in whitelist:
                errors.append(
                    f"[{sid}] 画内文字未在白名单中: '{t}' 不在 FilmBible 白名单 {whitelist} 中。"
                )

    # ── 提示词正文复核 (如果传入了编译产物 prompts) ───────────────────────
    if prompts:
        for idx, p in enumerate(prompts):
            sid = shots[idx].shot_id if idx < len(shots) else f"Shot-{idx+1}"
            p_text = p.prompt if hasattr(p, "prompt") else str(p)

            # 语言锁是否存在于 prompt
            if "普通话" not in p_text:
                errors.append(f"[{sid}] 生成提示词正文中缺少普通话语言锁条款。")

            # post_only 是否泄漏进 prompt 正文
            post_in_prompt = find_post_only_violations(p_text)
            if post_in_prompt:
                errors.append(
                    f"[{sid}] post_only 词汇泄漏进生成提示词: {', '.join(post_in_prompt)}。"
                )

    return errors
