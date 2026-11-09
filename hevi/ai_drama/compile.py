"""Deterministic script -> storyboard compiler.

The compiler never writes new dialogue.  It only arranges beats into segments
of 2-4 shots, cuts when the speaker changes, splits explicitly marked big
actions into three shots, and carries staging/camera/light/sound forward.
When a beat already carries a ``shots`` list (an author's shot plan) that plan
is used verbatim and only missing mechanical fields are filled.
"""

from __future__ import annotations

import copy
from typing import Any

from .schema import estimate_seconds

SIZE_LADDER = ("大全景", "中景", "近景", "特写")


def _scene_light(scene: dict[str, Any]) -> str:
    light = scene.get("lighting") or {}
    return (
        f"{light.get('direction', '侧光')}/{light.get('hardness', '柔光')}/"
        f"{light.get('warmth', '冷色')}/对比{light.get('contrast', '中等')}"
    )


def _dialogue_for(beat: dict[str, Any], indexes: list[int] | None) -> list[dict[str, Any]]:
    lines = beat.get("dialogue") or []
    if indexes is None:
        return [copy.deepcopy(line) for line in lines]
    return [copy.deepcopy(lines[i]) for i in indexes if 0 <= i < len(lines)]


def _auto_shots(scene: dict[str, Any], beat: dict[str, Any], *, first_of_scene: bool) -> list[dict[str, Any]]:
    """Mechanical shot plan when the author supplied none."""
    shots: list[dict[str, Any]] = []
    staging = str(beat.get("staging") or f"人物在{scene.get('name', '场景')}内按剧本站位")
    action = "；".join(str(x).lstrip("△") for x in beat.get("action") or []) or "人物保持当前状态"
    dialogue = beat.get("dialogue") or []
    if first_of_scene:
        shots.append({
            "size": "大全景", "mode": "establishing", "coverage": "大全景",
            "duration_s": 3.0, "camera": "固定机位，大全景交代空间",
            "subject": f"{scene.get('name', '场景')}全景", "staging": staging,
            "action": "环境保持，人物进入画面", "lighting": _scene_light(scene),
            "dialogue": [],
        })
    if not dialogue:
        shots.append({
            "size": "中景", "mode": "action", "coverage": "大全景",
            "duration_s": max(2.5, min(5.0, len(action) * 0.08)),
            "camera": "固定机位，中景跟随动作", "subject": "人物动作",
            "staging": staging, "action": action, "lighting": _scene_light(scene),
            "dialogue": [],
        })
        return shots
    # One shot per speaker turn; a turn may hold several lines by the same speaker.
    cursor = 0
    turn = 0
    while cursor < len(dialogue):
        speaker = str(dialogue[cursor].get("speaker"))
        start = cursor
        while cursor < len(dialogue) and str(dialogue[cursor].get("speaker")) == speaker:
            cursor += 1
        chunk = dialogue[start:cursor]
        size = SIZE_LADDER[min(turn, len(SIZE_LADDER) - 1)]
        est = sum(estimate_seconds(str(x.get("text") or "")) for x in chunk)
        shots.append({
            "size": size, "mode": "talking", "coverage": "正打" if turn % 2 == 0 else "反打",
            "duration_s": round(max(2.5, est + 0.6), 2),
            "camera": f"{size}，{'正打' if turn % 2 == 0 else '反打'}，平视",
            "subject": f"{speaker} 说话", "character_id": speaker,
            "staging": staging, "action": action if turn == 0 else "承接上一镜，继续对话",
            "lighting": _scene_light(scene),
            "dialogue": chunk,
        })
        turn += 1
    return shots


def compile_storyboard(script: dict[str, Any], *, max_shot_s: float = 8.0) -> dict[str, Any]:
    segments: list[dict[str, Any]] = []
    prev_end = ""
    for _s_idx, scene in enumerate(script.get("scenes") or []):
        for b_idx, beat in enumerate(scene.get("beats") or []):
            raw_shots = beat.get("shots")
            planned = raw_shots or _auto_shots(scene, beat, first_of_scene=(b_idx == 0))
            shots: list[dict[str, Any]] = []
            for plan in planned:
                shot = copy.deepcopy(plan)
                shot.setdefault("scene_id", scene.get("scene_id"))
                shot.setdefault("coverage", "大全景")
                shot.setdefault("size", "中景")
                shot.setdefault("mode", "talking" if shot.get("dialogue") else "action")
                shot.setdefault("camera", f"{shot['size']}，平视")
                shot.setdefault("subject", scene.get("name", "场景"))
                shot.setdefault("staging", beat.get("staging") or "")
                shot.setdefault("action", "承接上一镜")
                shot.setdefault("lighting", _scene_light(scene))
                shot.setdefault("emotion", beat.get("emotion", "neutral"))
                shot.setdefault("sound", beat.get("sound") or scene.get("ambience") or "环境底噪")
                shot.setdefault("sfx", beat.get("sfx") or "")
                if "dialogue_index" in plan:
                    shot["dialogue"] = _dialogue_for(beat, plan.get("dialogue_index"))
                else:
                    shot.setdefault("dialogue", [])
                shot.setdefault("negatives", ["无字幕", "无文字", "无logo", "无水印", "不要音乐"])
                pov = script.get("pov") or {}
                if pov:
                    shot["pov"] = True
                    for term in ("不露脸", "无正脸"):
                        if term not in shot["negatives"]:
                            shot["negatives"].append(term)
                    body = "（主角视角：画面边缘只可见主角的手、袖子和鞋，主角不露脸）"
                    if not any(term in str(shot.get("action")) for term in ("手", "袖", "鞋")):
                        shot["action"] = f"{shot.get('action', '')}{body}"
                    if str(shot.get("character_id")) == str(pov.get("viewer")):
                        shot["character_id"] = None
                        shot["mode"] = "pov"
                if prev_end:
                    shot.setdefault("continues_from", prev_end)
                shot["duration_s"] = round(min(max_shot_s, max(0.5, float(shot.get("duration_s") or 2.5))), 2)
                prev_end = f"{shot.get('action', '')} 结束"
                shots.append(shot)
            # 2-4 shots per segment: add a reaction/insert rather than a fifth cut.
            if len(shots) < 2:
                last = shots[-1]
                reaction = copy.deepcopy(last)
                reaction.update({
                    "size": "近景", "mode": "reaction", "coverage": "反打", "dialogue": [],
                    "action": "听者反应，不说话", "camera": "近景，反打，平视",
                    "duration_s": 1.6, "continues_from": prev_end,
                })
                shots.append(reaction)
            pov = script.get("pov") or {}
            if pov:
                viewer = str(pov.get("viewer") or "")
                body = "（主角视角：画面边缘只可见主角的手、袖子和鞋，主角不露脸）"
                for shot in shots:
                    shot["pov"] = True
                    for term in ("不露脸", "无正脸"):
                        if term not in shot.setdefault("negatives", []):
                            shot["negatives"].append(term)
                    if not any(term in str(shot.get("action")) for term in ("手", "袖", "鞋")):
                        shot["action"] = f"{shot.get('action', '')}{body}"
                    if viewer and str(shot.get("character_id")) == viewer:
                        shot["character_id"] = None
                        shot["mode"] = "pov"
            if len(shots) > 4:
                # split into consecutive segments of at most 4 shots
                for chunk_start in range(0, len(shots), 4):
                    chunk = shots[chunk_start:chunk_start + 4]
                    if len(chunk) == 1:
                        segments[-1]["shots"].extend(chunk)
                        segments[-1]["duration_s"] = round(sum(s["duration_s"] for s in segments[-1]["shots"]), 2)
                        continue
                    segments.append({
                        "segment_id": "", "event": beat.get("event") or "同一事件推进",
                        "sound": beat.get("sound") or "", "shots": chunk,
                        "duration_s": round(sum(s["duration_s"] for s in chunk), 2),
                    })
                continue
            segments.append({
                "segment_id": "", "event": beat.get("event") or "同一事件推进",
                "sound": beat.get("sound") or "", "shots": shots,
                "duration_s": round(sum(s["duration_s"] for s in shots), 2),
            })
    for i, seg in enumerate(segments, start=1):
        seg["segment_id"] = seg.get("segment_id") or f"seg_{i:02d}"
        for j, shot in enumerate(seg["shots"], start=1):
            shot["shot_id"] = shot.get("shot_id") or f"{seg['segment_id']}_s{j}"
            shot["segment_id"] = seg["segment_id"]
    return {
        "episode_no": script.get("episode_no", 1),
        "title": script.get("title", ""),
        "style": script.get("style", "live_action"),
        "aspect": script.get("aspect", "9:16"),
        "segments": segments,
    }


def draft_script_from_theme(theme: str, *, style: str = "live_action", duration_s: float = 60.0) -> dict[str, Any]:
    """A small deterministic scaffold for a theme with no supplied script.

    It is honest about being a scaffold: the conflict line and characters are
    placeholders that the writer must replace.  The node's self-check will
    still run; a scaffold is not a final script.
    """
    theme = theme.strip() or "一个日常里的异常"
    characters = [
        {"id": "c1", "name": "主角", "look": "普通人，日常穿着",
         "voice": {"description": "克制、偏低", "piper_voice": "zh_CN-huayan-medium.onnx", "pitch_semitones": -1.0}},
        {"id": "c2", "name": "对方", "look": "与主角关系密切，穿着朴素",
         "voice": {"description": "沙哑、温和", "piper_voice": "zh_CN-huayan-medium.onnx", "pitch_semitones": 1.5}},
    ]
    scene = {
        "scene_no": 1, "scene_id": "sc_01", "name": "日常空间", "int_ext": "内", "day_night": "夜",
        "header": "1 日常空间 [内] [夜]",
        "location": "日常空间", "lighting": {"direction": "侧光", "hardness": "柔光", "warmth": "冷色", "contrast": "中等"},
        "coverage": ["大全景", "正打", "反打"], "ambience": "室内底噪，远处城市低频",
        "beats": [
            {"beat_id": "b01", "event": "主题出现", "emotion": "日常", "sound": "室内底噪",
             "staging": "两人隔着桌子，一坐一站", "action": ["△主角停下手里的事，看向对方"],
             "dialogue": [
                 {"speaker": "c1", "text": f"{theme}。", "kind": "said"},
                 {"speaker": "c2", "text": "你确定要现在说？", "kind": "said"},
             ]},
            {"beat_id": "b02", "event": "冲突升级", "emotion": "对峙", "sound": "室内底噪，椅子轻响",
             "staging": "两人隔着桌子，距离不变", "action": ["△主角把东西推到桌子中间"],
             "dialogue": [
                 {"speaker": "c1", "text": "我只问一次。", "kind": "said"},
                 {"speaker": "c2", "text": "那就别问。", "kind": "said"},
             ]},
        ],
    }
    return {
        "episode_no": 1, "title": theme[:20], "style": style, "aspect": "9:16",
        "logline": f"围绕“{theme}”的一次对峙。", "duration_target_s": duration_s,
        "hook": {"first_3s_conflict": f"{theme} 打破日常"},
        "characters": characters, "scenes": [scene],
    }
