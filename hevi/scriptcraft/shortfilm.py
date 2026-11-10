"""Short-film mode (5–8 minutes): one closed story, not a drama episode 1.

The document carries the development sentence, the three-layer protagonist,
a dramatic game with a clock, seven structure steps, two or three reversals
that say what they change, a motif that appears three times, and an ending
that actually ends.
"""

from __future__ import annotations

from typing import Any

from .characters import check_characters
from .names import pick_names
from .premise import evaluate_premise
from .review import review_document
from .shortdrama import select_blueprint
from .text import estimate_seconds

SUPPORT_FUNCTIONS = ("见证者", "误导者", "在乎的人", "加压者")

TEMPLATES: dict[str, dict[str, Any]] = {
    "family": {
        "genre": "家庭剧情短片",
        "opponent_reason": "床位和演出审批都有硬规定，他不是坏人，只是不敢担责任",
        "want": "在今晚演出结束前录下老人最后一次唱戏",
        "need": "接受老人已经留不住，学会好好告别",
        "belief": "只要录下来，人就还在",
        "deadline": "今晚七点演出开始前",
        "place": "养老院活动室",
        "public": "家属开放日，台下坐着十几位家属",
        "choice": "让老人上台唱完，还是听院长的话取消",
        "rule_object": "一把旧戏票，凭票才能上台",
        "motif": "空椅子",
        "opening": "{lead}把一把空椅子搬到活动室中央，椅背上搭着戏服。",
        "goal": "{lead}把手机架在椅子对面，按下录像键。",
        "obstacle": "{opponent}把演出单抽走，指着老人体检单上的红字。",
        "reversal1": "{lead}发现老人一直对着空椅子练，因为他的眼睛已经看不清台下。",
        "choice_scene": "{opponent}要把老人推回房间，{lead}把旧戏票放到他手里。",
        "climax": "{lead}把空椅子推到台中央，老人对着椅子起唱。",
        "echo": "{lead}关掉录像，坐在空椅子旁边，跟着哼了最后一句。",
        "witness_action": "{witness}把一叠旧戏票放到桌上，最上面一张用红笔圈了今晚。",
        "prop_sizes": {"旧戏票": 12, "手机": 15, "空椅子": 45, "戏服": 40},
        "dialogue": [
            [("lead", "今晚就一次，我想录下来。"), ("elder", "录下来，人就还在吗？")],
            [("lead", "七点之前，我一定架好。"), ("elder", "你上次也这么说。")],
            [("opponent", "体检单在这儿，今天不能上台。"), ("lead", "他自己签的字呢？")],
            [("lead", "他看不见台下，是不是？"), ("opponent", "他不想让你们知道。")],
            [("opponent", "你现在带走他，出了事谁负责？"), ("lead", "我负责。")],
            [("lead", "椅子放中间，他就看得见。"), ("elder", "你扶我一把。")],
            [("witness", "他唱完了，台下没人走。"), ("lead", "把录像关了吧。")],
            [("lead", "最后一句，我替他唱。")],
        ],
        "events": [
            "空椅子被搬到活动室中央，戏服搭在椅背",
            "孙女架好手机，要在演出前录下最后一次",
            "院长以体检单为由取消老人上台",
            "孙女发现老人看不清台下，一直对着空椅子练",
            "演出开始，院长要把老人推回房间",
            "孙女把旧戏票塞给老人，推着空椅子上台",
            "老人对着空椅子唱完，台下家属安静",
            "孙女关掉录像，坐在空椅子边跟着唱",
        ],
        "supporting": [
            ("elder", "在乎的人", "老人，唱了一辈子戏，眼睛已经看不清"),
            ("witness", "见证者", "同屋的老人，记得每一场演出的日期"),
            ("pressure", "加压者", "家属代表，要求院方保证安全"),
        ],
    },
    "suspense": {
        "genre": "悬疑短片",
        "opponent_reason": "他在等一个再也不会回来的人，重复值班是他唯一能做的补救",
        "want": "在天亮前离开这间自习室",
        "need": "承认自己也在逃避一件旧事",
        "belief": "只要不回头，那天就没有发生",
        "deadline": "天亮前的最后一次报时",
        "place": "深夜自习室",
        "public": "整栋楼只剩这一间还亮着",
        "choice": "留下把名字写回值班表，还是推门离开",
        "rule_object": "一本每天都会少一个名字的值班表",
        "motif": "墙上停住的钟",
        "opening": "{lead}把值班表翻到昨天那一页，日期和今天完全相同。",
        "goal": "{lead}把手机时间举到管理员面前，管理员没有抬头。",
        "obstacle": "{opponent}把门从外面锁上，说今天谁也不能提前走。",
        "reversal1": "{lead}翻开抽屉，里面是七本一模一样的值班表。",
        "choice_scene": "{opponent}把笔推过来，让{lead}把最后一个名字划掉。",
        "climax": "{lead}把七本值班表全部摊开，找到每天少掉的那个名字。",
        "echo": "{lead}把名字写回最后一页，墙上的钟第一次走动。",
        "witness_action": "{witness}把一串钥匙放到桌上，钥匙上挂着值班室的牌子。",
        "prop_sizes": {"值班表": 21, "手机": 15, "钟": 30, "钥匙": 8},
        "dialogue": [
            [("lead", "第几遍了？"), ("classmate", "你说什么第几遍？")],
            [("lead", "天亮前我一定走。"), ("classmate", "你昨晚也这么说。")],
            [("opponent", "今天谁也不能提前走。"), ("lead", "门是你锁的？")],
            [("lead", "七本值班表，为什么少的是同一个人？"), ("opponent", "你别管。")],
            [("opponent", "把名字划掉，你就能走。"), ("lead", "划掉谁？")],
            [("lead", "这个名字，我写回去。"), ("classmate", "你想清楚了？")],
            [("witness", "钟走了。"), ("lead", "天亮了。")],
            [("lead", "这次我不回头。")],
        ],
        "events": [
            "值班表上的日期和昨天一模一样",
            "管理员记得所有人，唯独不记得昨天",
            "门从外面被锁上，手机时间停在 23:59",
            "抽屉里出现七本一模一样的值班表",
            "管理员让主角划掉最后一个名字",
            "主角把七本值班表摊开，发现少掉的是同一个人",
            "管理员承认自己在等那个人回来",
            "主角把名字写回去，钟开始走，天亮",
        ],
        "supporting": [
            ("classmate", "误导者", "同学，坚信只是主角记错了"),
            ("witness", "见证者", "打扫卫生的阿姨，记得每晚的报时"),
            ("pressure", "加压者", "值班老师，要求所有人立刻离开"),
        ],
    },
    "injustice": {
        "genre": "现实短片",
        "opponent_reason": "他要保住整个站点的考核，承认错误就全组扣钱",
        "want": "在天亮前把完整监控交到孩子母亲手里",
        "need": "承认自己当时也害怕，所以先跑了",
        "belief": "只要证明自己没推人，就还是好人",
        "deadline": "天亮前最后一班巡逻",
        "place": "小区门岗",
        "public": "业主群正在直播，门口围了十几个人",
        "choice": "把证据交出去，还是删掉视频保住工作",
        "rule_object": "一块只能读一次的监控硬盘",
        "motif": "外卖箱上的反光条",
        "opening": "{lead}把湿透的外卖箱放在门岗地上，手机里播放着指认自己的视频。",
        "goal": "{lead}把当晚配送路线截图递给{opponent}，手指停在 21:47。",
        "obstacle": "{opponent}把站点考核表拍在桌上，要求{lead}当场删视频。",
        "reversal1": "{lead}从外卖箱夹层取出硬盘，插进读卡器，画面里出现第三个人。",
        "choice_scene": "{opponent}给出选择：交硬盘，或明天不用来上班。",
        "climax": "{lead}把硬盘交给孩子母亲，业主群同时收到完整视频。",
        "echo": "{lead}把外卖箱重新绑好，反光条在晨光里亮了一下。",
        "witness_action": "{witness}把门岗登记本放到桌上，翻到 21:47 那一行。",
        "prop_sizes": {"监控硬盘": 8, "手机": 15, "外卖箱": 35, "登记本": 30},
        "dialogue": [
            [("lead", "我只想还自己一个清白。"), ("mother", "视频都传遍了。")],
            [("lead", "天亮前，我把完整监控找出来。"), ("mother", "你找得到吗？")],
            [("opponent", "把视频删了，明天照常上班。"), ("lead", "删了我就真成推人的了。")],
            [("lead", "这七秒里还有一个人。"), ("opponent", "你看错了。")],
            [("opponent", "硬盘交出来，或者走人。"), ("lead", "我交。")],
            [("lead", "大姐，你看完再决定。"), ("mother", "你为什么不早拿出来？")],
            [("witness", "群里都看见了。"), ("lead", "那就好。")],
            [("lead", "天亮了，出车。")],
        ],
        "events": [
            "骑手把湿透的外卖箱放在门岗",
            "他要在天亮前证明自己没推人",
            "站长用考核表逼他删视频",
            "硬盘恢复出被剪掉的七秒，画面里有第三个人",
            "站长给出选择：交硬盘或丢工作",
            "骑手把硬盘交给孩子母亲",
            "完整视频进业主群，真正的人被认出来",
            "骑手重新绑好外卖箱，天亮出车",
        ],
        "supporting": [
            ("mother", "在乎的人", "孩子母亲，最早指认主角的人"),
            ("witness", "见证者", "门岗保安，看见第三个人进出"),
            ("pressure", "加压者", "平台法务，要求尽快平息"),
        ],
    },
    "generic": {
        "genre": "都市短片",
        "opponent_reason": "他也有自己的难处，只是选择牺牲主角来保住自己",
        "want": "在店关门前把话说清楚",
        "need": "承认自己一直用沉默换体面",
        "belief": "只要不开口，关系就还能维持",
        "deadline": "今晚十点关店前",
        "place": "街角小店",
        "public": "店里还有最后一桌客人",
        "choice": "把旧手机里的语音放出来，还是继续装作没听见",
        "rule_object": "一部只能放一次语音的旧手机",
        "motif": "柜台上的旧手机",
        "opening": "{lead}把旧手机放在柜台上，屏幕停在三年前的一条短信。",
        "goal": "{lead}把零钱一枚一枚码好，等{opponent}进门。",
        "obstacle": "{opponent}把一张欠条压在手机旁边，说今天必须结清。",
        "reversal1": "{lead}点开旧手机，语音里出现第三个人的声音。",
        "choice_scene": "{opponent}让{lead}选：认账，还是让{ally}背。",
        "climax": "{lead}把语音放到最大声，街坊都听见了。",
        "echo": "{lead}把旧手机收回抽屉，店门在身后关上。",
        "witness_action": "{witness}把一张写着日期的收据放到桌上。",
        "prop_sizes": {"旧手机": 15, "欠条": 15, "收据": 15},
        "dialogue": [
            [("lead", "三年前这条短信，是你发的吗？"), ("ally", "你还在看这个。")],
            [("lead", "关店前，你把话说清楚。"), ("ally", "说不清的。")],
            [("opponent", "欠条在这儿，今天结清。"), ("lead", "背面这个名字是谁？")],
            [("lead", "语音里有第三个人。"), ("opponent", "你听错了。")],
            [("opponent", "认账，或者让朋友背。"), ("lead", "我认。")],
            [("lead", "大家都听听。"), ("ally", "你疯了？")],
            [("witness", "欠条撕了。"), ("lead", "名字还我。")],
            [("lead", "店关了，我也该走了。")],
        ],
        "events": [
            "旧手机被放在柜台上",
            "主角要在关店前把三年前的事说清",
            "对方拿欠条逼他当天结清",
            "旧手机里的语音出现第三个人",
            "对方让主角在认账和让朋友背之间选",
            "主角把语音放给所有人听",
            "欠条被撕掉，主角拿回自己的名字",
            "店门关上，旧手机留在抽屉里",
        ],
        "supporting": [
            ("ally", "在乎的人", "朋友，当年替主角签过字"),
            ("witness", "见证者", "常客，记得三年前的每个晚上"),
            ("pressure", "加压者", "房东，要求今晚给答复"),
        ],
    },
}


def _fill(template: str, slots: dict[str, str]) -> str:
    out = template
    for key, value in slots.items():
        out = out.replace("{" + key + "}", value)
    return out


def _line(speaker: str, text: str, kind: str = "said", **extra: Any) -> dict[str, Any]:
    return {
        "speaker": speaker,
        "kind": kind,
        "text": text,
        "duration_s": round(estimate_seconds(text, cps=4.5), 1),
        **extra,
    }


def build_short_film(
    *,
    topic: str,
    duration_s: int = 360,
    genre: str = "",
    confirm: bool = False,
) -> dict[str, Any]:
    key, _ = select_blueprint(topic, genre)
    if key not in TEMPLATES:
        key = "generic"
    template = TEMPLATES[key]
    names = pick_names(topic, 4)
    lead_name, opponent_name, support1_name, support2_name = names
    elder_function, elder_desc = template["supporting"][0][1:]
    witness_function, witness_desc = template["supporting"][1][1:]
    characters = [
        {
            "id": "c1", "name": lead_name, "role": "主角",
            "bio": f"{template['place']}里的普通人，嘴上说要一件小事，心里压着一件旧事。",
            "relations": [{"target": opponent_name, "type": "互相欠着的人"}],
            "defect": "用沉默换体面，越在乎越不肯先开口",
            "arc": "从躲着不说，到当众做出一个不可逆的选择",
            "visual_markers": ["左手腕旧红绳", "深色帆布包", "磨白的鞋边"],
            "outfit": {"top": "深色针织衫", "bottom": "长裤", "shoes": "旧帆布鞋"},
            "personality": "克制、敏感、嘴硬",
            "voice": {"description": "偏低、句子短", "piper_voice": "zh_CN-huayan-medium.onnx"},
            "state": {"pose": "站", "location": "", "prop": "", "outfit": "深色针织衫"},
        },
        {
            "id": "c2", "name": opponent_name, "role": "反派",
            "bio": f"{elder_desc}；他有自己的难处：{template['opponent_reason']}。",
            "relations": [{"target": lead_name, "type": "挡住主角的人"}],
            "defect": "怕担责任，习惯把选择推给别人",
            "arc": "从按规定办事，到被迫面对自己也在逃避",
            "visual_markers": ["胸前工牌", "左手无名指戒痕", "黑色布鞋"],
            "outfit": {"top": "深色制服", "bottom": "深色长裤", "shoes": "黑色布鞋"},
            "personality": "谨慎、强硬、心虚",
            "voice": {"description": "中低音、语速慢", "piper_voice": "zh_CN-huayan-medium.onnx"},
            "state": {"pose": "站", "location": "", "prop": "", "outfit": "深色制服"},
        },
        {
            "id": "c3", "name": support1_name, "role": "重要配角",
            "bio": support1_name + "，" + elder_function + "。",
            "relations": [{"target": lead_name, "type": elder_function}],
            "defect": "太想留住过去，反而不敢看现在",
            "arc": "从被照顾，到反过来给主角一个答案",
            "visual_markers": ["旧手表", "洗到发白的袖口", "随身收音机"],
            "outfit": {"top": "浅色开衫", "bottom": "深色长裤", "shoes": "软底鞋"},
            "personality": "温和、固执",
            "voice": {"description": "轻、慢", "piper_voice": "zh_CN-huayan-medium.onnx"},
            "state": {"pose": "站", "location": "", "prop": "", "outfit": "浅色开衫"},
        },
        {
            "id": "c4", "name": support2_name, "role": "配角",
            "bio": support2_name + "，" + witness_function + "。",
            "relations": [{"target": lead_name, "type": witness_function}],
            "defect": "只说一半，怕惹麻烦",
            "arc": "从旁观，到把看见的说出来",
            "visual_markers": ["红色围巾", "手里一串钥匙", "鞋跟磨偏"],
            "outfit": {"top": "工作马甲", "bottom": "深色长裤", "shoes": "防滑鞋"},
            "personality": "寡言、观察细",
            "voice": {"description": "轻、带口音", "piper_voice": "zh_CN-huayan-medium.onnx"},
            "state": {"pose": "站", "location": "", "prop": "", "outfit": "工作马甲"},
        },
    ]
    slots = {
        "lead": lead_name, "opponent": opponent_name, "ally": support1_name,
        "witness": support2_name, "elder": support1_name, "pressure": support2_name,
    }
    dramatic_game = {
        "deadline": template["deadline"],
        "place": template["place"],
        "public": template["public"],
        "choice": template["choice"],
        "rule_object": template["rule_object"],
    }
    lead = {
        "name": lead_name,
        "want": _fill(template["want"], slots),
        "need": _fill(template["need"], slots),
        "belief": _fill(template["belief"], slots),
        "defect": "用沉默换体面",
        "arc": "从躲着不说，到当众做出不可逆的选择",
    }
    opponent = {
        "name": opponent_name,
        "why_reasonable": template["opponent_reason"],
        "plan": "按规矩把事情压下去，保住自己的位置",
    }
    supporting = [
        {"name": support1_name, "function": elder_function, "description": elder_desc},
        {"name": support2_name, "function": witness_function, "description": witness_desc},
    ]
    reversals = [
        {
            "index": 1,
            "scene": 4,
            "changes": "fact",
            "summary": _fill(template["reversal1"], slots),
        },
        {
            "index": 2,
            "scene": 6,
            "changes": "relation",
            "summary": f"{opponent_name}不是单纯的坏人：{template['opponent_reason']}",
        },
    ]
    eight_scenes = [
        (1, "开场图像", f"{template['place']}·开场", _fill(template["opening"], slots), [lead_name, support1_name], ["empty"]),
        (2, "目标确立", f"{template['place']}·目标", _fill(template["goal"], slots), [lead_name, support1_name], ["goal"]),
        (3, "第一阻碍", f"{template['place']}·阻碍", _fill(template["obstacle"], slots), [lead_name, opponent_name], ["obstacle"]),
        (4, "中点反转", f"{template['place']}·反转", _fill(template["reversal1"], slots), [lead_name, opponent_name], ["reversal1"]),
        (5, "逼迫选择", f"{template['place']}·选择", _fill(template["choice_scene"], slots), [lead_name, opponent_name, support1_name], ["choice"]),
        (6, "高潮行动", f"{template['place']}·高潮", _fill(template["climax"], slots), [lead_name, opponent_name, support1_name], ["climax"]),
        (7, "高潮余波", f"{template['place']}·余波", _fill(template["witness_action"], slots), [lead_name, support2_name], ["witness"]),
        (8, "余味图像", f"{template['place']}·余味", _fill(template["echo"], slots), [lead_name], ["echo"]),
    ]
    scenes: list[dict[str, Any]] = []
    for scene_no, step, name, action, present, _tags in eight_scenes:
        scenes.append({
            "scene_no": scene_no,
            "scene_id": f"sc_{scene_no:02d}",
            "name": name,
            "location": name.split("·")[0],
            "int_ext": "内" if template["place"] in ("养老院活动室", "深夜自习室", "街角小店") else "外",
            "day_night": "夜" if "夜" in template["deadline"] or "天亮" in template["deadline"] else "日",
            "step": step,
            "characters_present": present,
            "coverage": ["大全景", "正打", "反打"],
            "lighting": {
                "direction": "侧顶光" if scene_no % 2 else "侧逆光",
                "hardness": "硬" if scene_no in (4, 6) else "半硬",
                "warmth": "暖" if scene_no in (1, 8) else "冷",
                "contrast": "高" if scene_no in (3, 4, 6) else "中",
            },
            "beats": [
                {
                    "beat_id": f"sc_{scene_no:02d}_b01",
                    "duration_s": 45,
                    "action": ["△ " + action],
                    "dialogue": _scene_dialogue(template, scene_no, {
                        "lead": lead_name, "opponent": opponent_name,
                        "elder": support1_name, "ally": support1_name,
                        "classmate": support1_name, "mother": support1_name,
                        "witness": support2_name,
                    }),
                }
            ],
        })
    # Split scene 5/6 dialogue into a second beat so no beat carries a whole
    # argument; the checks then stay local.
    scenes[4]["beats"].append({
        "beat_id": "sc_05_b02",
        "duration_s": 20,
        "action": [f"△ {opponent_name}把笔推到{lead_name}面前，{lead_name}没有接。"],
        "dialogue": [
            _line(opponent_name, "签了，今晚就当没发生。", "said"),
            _line(lead_name, "我不签。", "said"),
        ],
    })
    name_to_id = {str(c["name"]): str(c["id"]) for c in characters}
    for scene in scenes:
        for beat in scene.get("beats") or []:
            for line in beat.get("dialogue") or []:
                speaker = str(line.get("speaker") or "")
                if speaker in name_to_id:
                    line["speaker_name"] = speaker
                    line["speaker"] = name_to_id[speaker]
        scene["characters_present"] = [name_to_id.get(str(x), str(x)) for x in scene.get("characters_present") or []]
    script = {
        "title": f"{topic}·短片",
        "logline": _fill(template["want"], slots),
        "style": "live_action",
        "aspect": "9:16",
        "duration_target_s": duration_s,
        "hook": {"first_3s_conflict": _fill(template["opening"], slots)[:38], "hook_type": "反差", "pass": True},
        "characters": characters,
        "props": [
            {"name": name, "size_cm": size, "note": "片中按此尺寸出现"}
            for name, size in template["prop_sizes"].items()
        ],
        "scenes": scenes,
    }
    filmability = _filmability(script)
    cast_check = check_characters(characters)
    premise = evaluate_premise(
        topic=topic,
        slots={
            "protagonist": f"{template['place']}里被一件旧事困住的普通人",
            "trigger": template["opening"].replace("{lead}", lead_name)[:40],
            "goal": _fill(template["want"], slots),
            "stakes": "错过今晚，就再也没有机会把话说清",
        },
        questions={
            "genre": template["genre"],
            "identification": "心里有一件没说完的事的人",
            "strongest_conflict": _fill(template["choice"], slots),
            "best_payoff": _fill(template["echo"], slots),
            "secret_reversal": _fill(template["reversal1"], slots),
            "route": "混合",
        },
        mode="short_film",
    )
    master = {
        "title": topic,
        "door": f"一个{template['place']}里的普通人，必须{template['want']}，否则会永远失去最后一次把话说清的机会。",
        "genre": template["genre"],
        "lead": lead,
        "opponent": opponent,
        "supporting": supporting,
        "dramatic_game": dramatic_game,
        "seven_steps": [
            {"step": 1, "label": "开场图像", "scene": 1, "summary": scenes[0]["beats"][0]["action"][0]},
            {"step": 2, "label": "目标确立", "scene": 2, "summary": scenes[1]["beats"][0]["action"][0]},
            {"step": 3, "label": "第一阻碍", "scene": 3, "summary": scenes[2]["beats"][0]["action"][0]},
            {"step": 4, "label": "中点反转", "scene": 4, "summary": scenes[3]["beats"][0]["action"][0]},
            {"step": 5, "label": "逼迫选择", "scene": 5, "summary": scenes[4]["beats"][0]["action"][0]},
            {"step": 6, "label": "高潮行动", "scene": 6, "summary": scenes[5]["beats"][0]["action"][0]},
            {"step": 7, "label": "余味图像", "scene": 8, "summary": scenes[7]["beats"][0]["action"][0]},
        ],
        "reversals": reversals,
        "motif": {"object": template["motif"], "appearances": [1, 6, 8], "count": 3},
        "ending": _fill(template["echo"], slots),
        "subtext": "人物不说主题，只处理眼前这件小事；主题藏在最后那个动作里。",
    }
    review_document_source = {**script, **master}
    review = review_document(review_document_source, mode="short_film", filmability=filmability)
    must = [f for f in review["findings"] if f["severity"] == "must"]
    must += [f for f in filmability["findings"] if f["severity"] == "must"]
    must += [f for f in cast_check if f["severity"] == "must"]
    return {
        "kind": "short_film",
        "topic": topic,
        "template": key,
        "premise_gate": premise,
        "gate": {
            "stage": "short_film_master_plan",
            "requires_confirmation": True,
            "confirmed": bool(confirm),
            "can_continue": bool(confirm) and premise["verdict"] == "pass",
            "message": "先确认短片总盘（戏剧游戏/7 步/反转/母题），再写分场与剧本。" if not confirm else "已确认。",
        },
        "master_plan": master,
        "characters": characters,
        "cast_cards": [{
            "id": c["id"], "name": c["name"], "role": c["role"],
            "visual_markers": c["visual_markers"],
        } for c in characters],
        "scenes": scenes,
        "script": script,
        "checks": {
            "premise": premise["findings"],
            "cast": cast_check,
            "filmability": filmability,
            "must_count": len(must),
            "passed": not must,
        },
        "review": review,
        "next": "review" if not must else "fix_checks",
        "duration_s": duration_s,
    }


def _scene_dialogue(
    template: dict[str, Any],
    scene_no: int,
    names: dict[str, str],
) -> list[dict[str, Any]]:
    rows = template["dialogue"][scene_no - 1]
    out: list[dict[str, Any]] = []
    for speaker_key, text in rows:
        kind = "inner" if len(rows) == 1 else "said"
        out.append(_line(names.get(speaker_key, names["lead"]), text, kind))
    return out


def _filmability(script: dict[str, Any]) -> dict[str, Any]:
    from .filmability import check_filmability

    return check_filmability(script)


__all__ = ["SUPPORT_FUNCTIONS", "TEMPLATES", "build_short_film"]
