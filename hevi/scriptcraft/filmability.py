"""AI-filmability self-check for a script document.

The checks are deliberately local: a failing beat is the only thing that has
to change.  They cover what a camera can actually see, how long the line takes,
what a character is holding or sitting on, prop scale and how many bodies share
the frame.
"""

from __future__ import annotations

import re
from typing import Any

from .text import (
    ACTION_PREFIX,
    EMOTION_WORDS,
    PHYSICAL_VERBS,
    TOO_CONVENIENT,
    estimate_seconds,
    suggested_duration,
)

UNFILMABLE = (
    "心里想", "心想", "暗自", "内心感到", "回忆起", "想起", "意识到", "感到", "他知道",
    "她明白", "明白了", "脑中", "脑海里", "思绪", "仿佛看到", "似乎看到",
)
DIALOGUE_KINDS = {"said", "inner", "vo"}
SIT = ("坐下", "坐回", "坐到", "落座", "坐进")
STAND = ("站起", "起身", "站起来", "站起身")
LIE = ("躺下", "躺到", "躺回")
SQUAT = ("蹲下", "蹲在", "蹲到")
KNEEL = ("跪下", "跪在", "跪到")
LEAVE = ("离开", "走出", "出门", "冲出去", "跑出去", "退场", "走了")
ENTER = ("走进", "进门", "推门进来", "回来", "回到", "冲进来")
PUT_DOWN = ("放下", "递给", "交给", "塞给", "扔掉", "丢下", "松开", "撤手")
PICK_UP = ("拿起", "抓住", "握住", "接过", "攥着", "抱着", "提着", "捏着", "举着")
CONTACT = ("握手", "扶住", "拉住", "抱住", "抓住对方", "按住", "碰", "推了", "拽")
FIGHT = ("打人", "打架", "殴打", "踢", "扇", "扭打", "撕打", "推倒", "挥拳", "砸", "踹")
WATER_FIRE = ("水", "雨", "淋", "火", "烟", "燃烧", "烧", "蒸汽")
READABLE_TEXT = ("写着", "屏幕显示", "短信", "文件上", "牌子上", "字幕", "聊天记录", "合同上")


def _finding(
    rule: str,
    severity: str,
    message: str,
    ref: str = "",
    *,
    fix: str = "",
    audience: str = "",
) -> dict[str, Any]:
    return {
        "rule": rule,
        "severity": severity,
        "message": message,
        "ref": ref,
        "fix": fix,
        "audience": audience,
    }


def _characters(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(c.get("id") or c.get("name")): c for c in document.get("characters") or []}


def _char_id(document: dict[str, Any], name: str) -> str:
    for char in document.get("characters") or []:
        if str(char.get("name")) == name:
            return str(char.get("id") or name)
    return name


def _scene_chars(scene: dict[str, Any]) -> list[str]:
    return [str(x) for x in scene.get("characters_present") or scene.get("characters") or []]


def _initial_state(document: dict[str, Any]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for char in document.get("characters") or []:
        cid = str(char.get("id") or char.get("name"))
        state = char.get("state") or {}
        out[cid] = {
            "pose": str(state.get("pose") or "站"),
            "location": str(state.get("location") or ""),
            "prop": str(state.get("prop") or ""),
            "outfit": str(state.get("outfit") or ""),
        }
    return out


def _prop_from_line(line: str, props: list[dict[str, Any]]) -> str:
    for prop in props:
        name = str(prop.get("name") or "")
        if name and name in line:
            return name
    return ""


def _walk_state(
    document: dict[str, Any],
    findings: list[dict[str, Any]],
    *,
    ref_prefix: str = "",
) -> None:
    states = _initial_state(document)
    props = [p for p in document.get("props") or [] if isinstance(p, dict)]
    for scene in document.get("scenes") or []:
        scene_id = str(scene.get("scene_id") or scene.get("scene_no") or "")
        location = str(scene.get("location") or "")
        for cid in _scene_chars(scene):
            state = states.setdefault(cid, {"pose": "站", "location": "", "prop": "", "outfit": ""})
            if not state.get("location"):
                state["location"] = location
        for beat in scene.get("beats") or []:
            beat_ref = str(beat.get("beat_id") or f"{scene_id}_beat")
            for line in beat.get("action") or []:
                text = str(line)
                for cid, state in states.items():
                    name = next(
                        (str(c.get("name")) for c in document.get("characters") or []
                         if str(c.get("id") or c.get("name")) == cid),
                        cid,
                    )
                    if not name or name not in text:
                        continue
                    pose = state["pose"]
                    if any(word in text for word in SIT):
                        if pose == "坐":
                            findings.append(_finding(
                                "F-STATE", "must",
                                f"{name} 整场已经坐着，动作里又写「{'/'.join(w for w in SIT if w in text)}」",
                                beat_ref,
                                fix="改成「站起」「转身」或先写一个起身动作",
                                audience="观众会看出人物状态连续错了，AI 也会把姿势画乱",
                            ))
                        state["pose"] = "坐"
                    elif any(word in text for word in STAND):
                        if pose == "站":
                            findings.append(_finding(
                                "F-STATE", "should",
                                f"{name} 本来就是站着的，又写「{'/'.join(w for w in STAND if w in text)}」",
                                beat_ref,
                                fix="删掉重复的起身动作，直接写下一步",
                                audience="动作重复会显得水",
                            ))
                        state["pose"] = "站"
                    elif any(word in text for word in LIE):
                        state["pose"] = "躺"
                    elif any(word in text for word in SQUAT):
                        state["pose"] = "蹲"
                    elif any(word in text for word in KNEEL):
                        state["pose"] = "跪"
                    if any(word in text for word in LEAVE):
                        state["location"] = "场外"
                    elif any(word in text for word in ENTER):
                        state["location"] = location
                    elif state["location"] == "场外":
                        findings.append(_finding(
                            "F-STATE", "should",
                            f"{name} 已经离场，后面又有动作；要么写回来，要么删掉",
                            beat_ref,
                            fix="补「回来/推门进来」，或把动作换给在场的人",
                            audience="人物凭空出现，观众会出戏",
                        ))
                    prop = _prop_from_line(text, props)
                    if prop and any(word in text for word in PUT_DOWN):
                        state["prop"] = ""
                    elif prop and any(word in text for word in PICK_UP):
                        state["prop"] = prop
            state_after = beat.get("state_after") or {}
            for cid, patch in state_after.items():
                if cid in states and isinstance(patch, dict):
                    for key in ("pose", "location", "prop", "outfit"):
                        if str(patch.get(key) or "").strip():
                            states[cid][key] = str(patch[key])


def check_filmability(document: dict[str, Any], *, cps: float = 4.5) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    names = {str(c.get("name")): str(c.get("id") or c.get("name")) for c in document.get("characters") or []}
    id_to_name = {str(c.get("id") or c.get("name")): str(c.get("name") or c.get("id")) for c in document.get("characters") or []}
    present_ids = {
        names.get(str(x), str(x)) for scene in document.get("scenes") or [] for x in _scene_chars(scene)
    }
    props = [p for p in document.get("props") or [] if isinstance(p, dict)]
    prop_names = {str(p.get("name")): p for p in props if str(p.get("name") or "")}
    dialogue_seconds = 0.0
    said_count = 0
    inner_count = 0
    vo_count = 0
    for scene_index, scene in enumerate(document.get("scenes") or [], start=1):
        scene_id = str(scene.get("scene_id") or f"sc{scene_index}")
        present = _scene_chars(scene)
        present_ids = {names.get(str(x), str(x)) for x in present}
        if len(present) > 4:
            findings.append(_finding(
                "F-CROWD", "must",
                f"同框 {len(present)} 人；AI 出图容易多手多脸",
                scene_id,
                fix="拆成两三个镜头，每镜 ≤3 人",
                audience="人多时人物会变形，观众第一眼就不信",
            ))
        elif len(present) == 4:
            findings.append(_finding(
                "F-CROWD", "should",
                "同框 4 人，接近 AI 的稳定上限",
                scene_id,
                fix="让第 4 个人只出现手/背影，或拆镜",
                audience="人数多时画面容易崩",
            ))
        for beat_index, beat in enumerate(scene.get("beats") or [], start=1):
            beat_ref = str(beat.get("beat_id") or f"{scene_id}_b{beat_index}")
            actions = [str(a) for a in beat.get("action") or []]
            for line in actions:
                text = line.strip()
                if not text.startswith(ACTION_PREFIX):
                    findings.append(_finding(
                        "F-ACTION-PREFIX", "should",
                        "动作行建议以 △ 开头，分镜阶段好识别",
                        beat_ref,
                        fix=f"改成「△ {text}」",
                        audience="不影响观众，影响下游自动分镜",
                    ))
                for word in UNFILMABLE:
                    if word in text:
                        findings.append(_finding(
                            "F-UNFILMABLE", "must",
                            f"动作里写了镜头拍不到的心理活动「{word}」",
                            beat_ref,
                            fix="换成身体动作：手在做什么、眼睛看哪里、嘴上说什么",
                            audience="心理活动拍不出来，成片会靠旁白硬解释",
                        ))
                        break
                emotion = next((w for w in EMOTION_WORDS if w in text), "")
                if emotion and not any(verb in text for verb in PHYSICAL_VERBS):
                    findings.append(_finding(
                        "F-EMOTION", "must",
                        f"只写情绪「{emotion}」没有动作，演不出来",
                        beat_ref,
                        fix="补一个可见动作：低头、攥紧、后退、把杯子放下",
                        audience="演员/AI 都不知道该怎么演，画面会空",
                    ))
                if any(word in text for word in TOO_CONVENIENT):
                    findings.append(_finding(
                        "F-CONVENIENT", "should",
                        "用了「幸好/正好/突然出现」式的兜底，冲突被老天解决",
                        beat_ref,
                        fix="让主角自己付出代价解决，或让反派先赢一步",
                        audience="观众会觉得假，爽点不成立",
                    ))
                for prop_name in prop_names:
                    if prop_name in text and "size_cm" not in prop_names[prop_name]:
                        findings.append(_finding(
                            "F-PROP-SIZE", "must",
                            f"道具「{prop_name}」没写实际尺寸",
                            beat_ref,
                            fix="在道具表写 size_cm（例如公章 4cm）",
                            audience="尺寸不清，AI 会把道具画得忽大忽小",
                        ))
                if len(re.findall(r"[，,、]", text)) >= 5 and len(text) > 60:
                    findings.append(_finding(
                        "F-ACTION-LONG", "should",
                        "一个动作行太长，可能压了两个以上动作",
                        beat_ref,
                        fix="拆成两行，每行一个动作",
                        audience="镜头里动作挤在一起会看不清",
                    ))
            for line_index, line in enumerate(beat.get("dialogue") or [], start=1):
                if not isinstance(line, dict):
                    continue
                ref = f"{beat_ref}_d{line_index}"
                kind = str(line.get("kind") or "")
                speaker = str(line.get("speaker") or "")
                text = str(line.get("text") or "")
                if kind not in DIALOGUE_KINDS:
                    findings.append(_finding(
                        "F-KIND", "must",
                        f"台词类型必须是 said/inner/vo，得到 {kind!r}",
                        ref,
                        fix="当面说=said；内心独白=inner；画外音=vo",
                        audience="不标类型就不知道该不该做口型",
                    ))
                elif kind == "said":
                    said_count += 1
                elif kind == "inner":
                    inner_count += 1
                elif kind == "vo":
                    vo_count += 1
                speaker_id = names.get(speaker, speaker)
                if speaker and speaker not in names and speaker not in id_to_name:
                    findings.append(_finding(
                        "F-SPEAKER", "must",
                        f"说话人「{speaker}」不在人物表",
                        ref,
                        fix="补人物表或改成在场角色",
                        audience="观众会分不清是谁在说",
                    ))
                elif speaker and speaker_id not in present_ids:
                    findings.append(_finding(
                        "F-PRESENT", "should",
                        f"说话人「{speaker}」不在本场出场表",
                        ref,
                        fix="加进 characters_present，或改成画外音 vo",
                        audience="人物凭空发声，会出戏",
                    ))
                needed = estimate_seconds(text, cps=cps)
                dialogue_seconds += needed
                declared = line.get("duration_s")
                if declared is not None and float(declared) + 0.25 < needed:
                    findings.append(_finding(
                        "F-DURATION", "must",
                        f"台词 {len(text)} 字按 {cps:.1f} 字/秒需 {needed:.1f}s，镜头只给了 {float(declared):.1f}s",
                        ref,
                        fix=f"把镜头时长改到 ≥{suggested_duration(text, cps=cps):.1f}s，或删短台词",
                        audience="台词会被截断或加速，听起来像赶火车",
                    ))
                if any(word in text for word in READABLE_TEXT):
                    findings.append(_finding(
                        "F-TEXT", "should",
                        "画面里需要看清的字，尽量后期叠加，不让模型生成",
                        ref,
                        fix="改成空镜/手部动作，文字用代码图层盖上去",
                        audience="模型生成的字大概率是乱码",
                    ))
            joined = " ".join(actions)
            if any(word in joined for word in CONTACT):
                findings.append(_finding(
                    "F-CONTACT", "should",
                    "有手部接触，AI 容易把手画错",
                    beat_ref,
                    fix="改成递物/隔桌/只拍手部特写，或拆成两个单人镜头",
                    audience="手一接触，变形最明显",
                ))
            if any(word in joined for word in FIGHT):
                findings.append(_finding(
                    "F-FIGHT", "should",
                    "有打斗动作，建议改成 AI 易拍版本",
                    beat_ref,
                    fix="用推搡前一秒、倒地后的结果、旁观者反应替代打斗过程",
                    audience="打斗过程 AI 很难拍连贯",
                ))
            if any(word in joined for word in WATER_FIRE):
                findings.append(_finding(
                    "F-ELEMENT", "should",
                    "有水/火/雨/烟，生成难度高",
                    beat_ref,
                    fix="只拍溅起的水花/远处的火光/湿掉的袖口",
                    audience="水火容易穿帮",
                ))
    _walk_state(document, findings)
    must = [f for f in findings if f["severity"] == "must"]
    return {
        "passed": not must,
        "dialogue_seconds": round(dialogue_seconds, 1),
        "dialogue_counts": {"said": said_count, "inner": inner_count, "vo": vo_count},
        "needs_lip_sync": said_count > 0,
        "counts": {
            "must": len(must),
            "should": len([f for f in findings if f["severity"] == "should"]),
        },
        "findings": findings,
    }


__all__ = [
    "DIALOGUE_KINDS",
    "check_filmability",
]
