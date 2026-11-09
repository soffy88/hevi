"""Beat script: ~5 timed beats (time + picture + line), one-beat edits, POV.

A beat script sits between the topic node and the structured screenplay.  It is
small enough for a person to change exactly one beat ("只改某一拍") while the
other four stay byte-identical.  POV means the audience *is* the male lead:
only hands, sleeves and shoes are ever visible; his face never appears.
"""

from __future__ import annotations

import copy
from typing import Any

POV_BODY = "手、袖子和鞋"
POV_NEGATIVES = ("不露脸", "看不到主角的脸", "无正脸")


def _f(text: str) -> str:
    return str(text or "").strip()


def _cast_pair(cast: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    cards = [c for c in cast if c.get("id") or c.get("name")]
    if not cards:
        return ({"id": "c1", "name": "主角"}, {"id": "c2", "name": "对方"})
    if len(cards) == 1:
        return cards[0], {"id": "c2", "name": "对方"}
    return cards[0], cards[1]


def build_beats(
    idea: dict[str, Any],
    cast: list[dict[str, Any]],
    *,
    pov: bool | None = None,
    duration_s: float = 18.0,
) -> list[dict[str, Any]]:
    lead, other = _cast_pair(cast)
    lead_id = str(lead.get("id") or "c1")
    other_id = str(other.get("id") or "c2")
    lead_name = str(lead.get("name") or "主角")
    other_name = str(other.get("name") or "对方")
    pov = bool(idea.get("pov") if pov is None else pov)
    genre = str(idea.get("genre") or "daily_anomaly")
    hook = _f(idea.get("hook_first_2s")) or "日常里第一秒就不对劲"

    if genre == "tsundere":
        lines = [
            (other_name, "最后一块，给你。"),
            (lead_name, "谁、谁要啊。"),
            (other_name, "那你手伸过来干嘛？"),
            (lead_name, "……我看看有没有坏。"),
        ]
        pictures = [
            f"{hook}：{other_name}递出点心，{lead_name}的手先伸了过去",
            f"{other_name}把点心往前送，{lead_name}别过脸",
            f"{lead_name}的指尖已经碰到点心",
            f"{other_name}笑出声，{lead_name}耳朵红了",
        ]
        button = f"{lead_name}把点心塞进嘴里，含糊地说“下次不要了”。"
    elif genre == "magic_backfire":
        lines = [
            (lead_name, "看我的小魔法。"),
            (other_name, "你确定？"),
            (lead_name, "哎——怎么冲我来了！"),
            (other_name, "因为你念反了。"),
        ]
        pictures = [
            f"{hook}：一道光从{other_name}那边弹回{lead_name}",
            f"{lead_name}得意地抬手施法",
            "光团在两人之间拐了个弯",
            f"{lead_name}头发被自己炸起来",
        ]
        button = f"{lead_name}顶着炸毛，{other_name}递来一把梳子。"
    elif genre == "disguise_fail":
        lines = [
            (lead_name, "你好，我是新来的。"),
            (other_name, "你帽子底下那撮头发我认得。"),
            (lead_name, "……认错人了。"),
            (other_name, "你鞋也是昨天那双。"),
        ]
        pictures = [
            f"{hook}：{lead_name}压着帽子开口，{other_name}一眼看穿",
            f"{lead_name}把帽子往下压",
            f"{other_name}盯着{lead_name}露出的那撮头发",
            f"{lead_name}低头看见自己的鞋",
        ]
        button = f"{lead_name}摘下帽子，{other_name}忍着笑说“惊喜收到了”。"
    elif genre == "catchphrase_triple":
        lines = [
            (lead_name, "问题不大。"),
            (other_name, "真的？"),
            (lead_name, "问题……有点大。"),
            (other_name, "你刚才可不是这么说的。"),
        ]
        pictures = [
            f"{hook}：{lead_name}第二次说“问题不大”，表情已经绷不住",
            f"{lead_name}拍胸口说第一次口头禅",
            f"东西塌下来，{lead_name}后退半步",
            f"{other_name}挑眉看着{lead_name}",
        ]
        button = f"{lead_name}第三次改口：“问题很大，但能修。”"
    elif genre == "hero_rescue":
        lines = [
            (other_name, "啊——"),
            (lead_name, "小心！"),
            (other_name, "你比我还慌。"),
            (lead_name, "我、我没有。"),
        ]
        pictures = [
            f"{hook}：{other_name}脚下一滑，{lead_name}扑过去",
            f"{other_name}身体失去平衡",
            f"{lead_name}一把接住，自己差点摔倒",
            f"两人站稳，{lead_name}手还在抖",
        ]
        button = f"{other_name}拍拍{lead_name}的肩：“谢啦，英雄。”"
    else:
        lines = [
            (lead_name, "今天也和平时一样。"),
            (other_name, "你确定？"),
            (lead_name, "等等，那是什么？"),
            (other_name, "别回头。"),
        ]
        pictures = [
            f"{hook}：日常画面里多出一个不该在的东西",
            f"{lead_name}照常做着手上的事",
            f"{other_name}的表情突然僵住",
            "两人同时看向同一个方向",
        ]
        button = "画面停在那个不该在的东西上。"

    if pov:
        pictures = [
            p if any(term in p for term in ("手", "袖", "鞋"))
            else f"{other_name}的视角：画面边缘露出主角的手、袖子和鞋（{p}）"
            for p in pictures
        ]
        if not any(term in button for term in ("手", "袖", "鞋")):
            button = f"主角视角：只可见手、袖子和鞋；{button}"
    first_two = 2.0
    total = max(15.0, min(20.0, float(duration_s or 18.0)))
    # Five beats: hook [0,2), then setup/turn/punch/button share the rest.
    remaining = total - first_two
    weights = (0.20, 0.28, 0.30, 0.22)
    boundaries = [0.0, first_two]
    cursor = first_two
    for weight in weights:
        cursor += remaining * weight
        boundaries.append(round(min(total, cursor), 3))
    boundaries[-1] = round(total, 3)
    boundaries = sorted(set(boundaries))
    while len(boundaries) < 6:
        boundaries.insert(-1, round((boundaries[-2] + boundaries[-1]) / 2, 3))

    beats: list[dict[str, Any]] = []
    stages = ["hook", "setup", "turn", "punch"]
    for i in range(4):
        speaker, text = lines[i]
        kind = "said"
        if pov and speaker == lead_name:
            kind = "inner"
        start, end = boundaries[i], boundaries[i + 1]
        beats.append({
            "index": i,
            "beat_id": f"bt_{i + 1:02d}",
            "stage": stages[i],
            "start_s": round(start, 3),
            "end_s": round(end, 3),
            "duration_s": round(end - start, 3),
            "picture": pictures[i],
            "speaker": other_id if speaker == other_name else lead_id,
            "speaker_name": speaker,
            "dialogue": [{"speaker": other_id if speaker == other_name else lead_id,
                          "text": text, "kind": kind}],
            "sfx": "叮" if i == 0 else "",
            "pov": pov,
        })
    beats.append({
        "index": 4,
        "beat_id": "bt_05",
        "stage": "button",
        "start_s": round(boundaries[4], 3),
        "end_s": round(boundaries[5], 3),
        "duration_s": round(boundaries[5] - boundaries[4], 3),
        "picture": button,
        "speaker": other_id,
        "speaker_name": other_name,
        "dialogue": [],
        "sfx": "叮",
        "pov": pov,
    })
    if pov:
        for beat in beats:
            if str(beat.get("speaker")) == lead_id:
                for line in beat.get("dialogue") or []:
                    line["kind"] = "inner"
    return beats


def revise_beat(beats: list[dict[str, Any]], index: int, patch: dict[str, Any]) -> list[dict[str, Any]]:
    """Change exactly one beat; every other beat is returned unchanged."""
    if not 0 <= index < len(beats):
        raise IndexError(f"beat index out of range: {index}")
    out = copy.deepcopy(beats)
    out[index].update(copy.deepcopy(patch))
    out[index]["index"] = index
    out[index]["beat_id"] = beats[index].get("beat_id") or f"bt_{index + 1:02d}"
    return out


def validate_beats(beats: list[dict[str, Any]], *, pov: bool = False, lead_id: str = "") -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not 4 <= len(beats) <= 6:
        out.append({"rule": "P-COUNT", "severity": "major",
                    "message": f"节拍数 {len(beats)}，建议 4–6 拍", "ref": ""})
    if not beats:
        return out
    first = beats[0]
    if float(first.get("end_s") or 0) > 2.05:
        out.append({"rule": "P-HOOK", "severity": "blocker",
                    "message": "最有趣的瞬间必须在前 2 秒出现", "ref": str(first.get("beat_id"))})
    total = max(float(b.get("end_s") or 0) for b in beats)
    if not 15.0 <= total <= 20.5:
        out.append({"rule": "P-DURATION", "severity": "major",
                    "message": f"总时长 {total:.1f}s，应为 15–20s", "ref": ""})
    for i, beat in enumerate(beats):
        if not _f(beat.get("picture")):
            out.append({"rule": "P-PICTURE", "severity": "blocker",
                        "message": "节拍缺画面", "ref": str(beat.get("beat_id"))})
        if i and float(beat.get("start_s") or 0) < float(beats[i - 1].get("end_s") or 0) - 0.01:
            out.append({"rule": "P-TIME", "severity": "major",
                        "message": "节拍时间重叠", "ref": str(beat.get("beat_id"))})
    if pov:
        for beat in beats:
            picture = _f(beat.get("picture"))
            if not any(term in picture for term in ("手", "袖", "鞋")):
                out.append({"rule": "P-POV-BODY", "severity": "blocker",
                            "message": "POV 节拍必须只露手/袖子/鞋", "ref": str(beat.get("beat_id"))})
            if lead_id and lead_id == str(beat.get("speaker")) and any(
                term in picture for term in ("正脸", "主角的脸", "特写脸")
            ):
                out.append({"rule": "P-POV-FACE", "severity": "blocker",
                            "message": "POV 不能出现主角正脸", "ref": str(beat.get("beat_id"))})
    return out


def beats_to_script(
    idea: dict[str, Any],
    beats: list[dict[str, Any]],
    cast: list[dict[str, Any]],
    *,
    style: str = "anime",
    pov: bool | None = None,
) -> dict[str, Any]:
    lead, other = _cast_pair(cast)
    pov = bool(idea.get("pov") if pov is None else pov)
    chars = []
    for card in (lead, other):
        cid = str(card.get("id") or "c1")
        chars.append({
            "id": cid,
            "name": str(card.get("name") or cid),
            "look": str(card.get("look") or "日常穿着"),
            "character_card": card if card.get("hair") else None,
            "pov_viewer": bool(pov and cid == str(lead.get("id") or "c1")),
            "voice": card.get("voice") or {
                "description": "自然、日常",
                "piper_voice": "zh_CN-huayan-medium.onnx",
                "pitch_semitones": 0.0 if cid == str(lead.get("id")) else 1.5,
            },
        })
    scene = {
        "scene_no": 1, "scene_id": "sc_01", "name": str(idea.get("genre_label") or "日常空间"),
        "int_ext": "内", "day_night": "日", "header": "1 日常空间 [内] [日]",
        "location": str(idea.get("genre_label") or "日常空间"),
        "lighting": {"direction": "侧光", "hardness": "柔光", "warmth": "暖色", "contrast": "中等"},
        "coverage": ["大全景", "正打", "反打"],
        "ambience": "室内底噪，远处城市低频",
        "beats": [],
    }
    for beat in beats:
        action = ["△" + _f(beat.get("picture"))]
        if pov:
            action.append(f"△镜头是主角视角，只可见{POV_BODY}，主角不露脸。")
        scene["beats"].append({
            "beat_id": beat.get("beat_id"),
            "event": _f(beat.get("stage")) or "推进",
            "emotion": "日常",
            "sound": "室内底噪" + ("，叮" if beat.get("sfx") else ""),
            "staging": f"主角与对方在{idea.get('genre_label') or '空间'}内，先站位后动作",
            "sfx": beat.get("sfx") or "",
            "action": action,
            "dialogue": copy.deepcopy(beat.get("dialogue") or []),
        })
    total = max(float(b.get("end_s") or 0) for b in beats) if beats else 18.0
    script: dict[str, Any] = {
        "episode_no": 1,
        "title": f"{idea.get('genre_label')}：{idea.get('one_sentence', '')[:16]}",
        "style": style,
        "aspect": "9:16",
        "logline": str(idea.get("one_sentence") or ""),
        "duration_target_s": round(total, 2),
        "hook": {"first_3s_conflict": str(idea.get("hook_first_2s") or ""), "first_2s_hook": True},
        "characters": chars,
        "scenes": [scene],
        "genre": idea.get("genre"),
        "genre_label": idea.get("genre_label"),
    }
    if pov:
        script["pov"] = {"viewer": str(lead.get("id") or "c1"), "body": POV_BODY,
                         "negatives": list(POV_NEGATIVES)}
    return script
