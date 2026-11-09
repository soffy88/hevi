"""Checkable rules for every ai_drama node.

Each rule returns findings shaped as ``{rule, severity, message, ref}``.
``severity`` is ``blocker`` (the node must not pass), ``major`` (visible
defect that a reviewer must accept or fix) or ``minor`` (advisory).  A node
passes only when it has no blocker -- the same fail-closed contract the rest
of hevi uses.

The rules are the brief's own checklist turned into code: only filmable
action, scene heading form, 2 s per 10 characters, cut on speaker change,
one event per 5-15 s segment, 2-4 shots per segment, no three same sizes in
a row, identity board fields, no people in scene plates, verbatim dialogue,
fixed per-character voice, dialogue > sfx > music, inner monologue in a
different subtitle colour, and the game_pov daily/anomaly/reversal spine.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from .schema import (
    ASPECTS,
    DIALOGUE_KINDS,
    PICTURE_REF_RE,
    SCENE_HEADER_RE,
    SHOT_SIZES,
    STYLES,
    dialogue_chars,
    estimate_seconds,
    iter_dialogue,
    iter_shots,
    ref_index,
)

UNFILMABLE = ("心想", "心里想", "暗自", "内心感到", "回忆起", "意识到", "感到", "他知道", "她明白")
BIG_ACTION = ("然后", "接着", "先", "再", "最后", "忽然", "突然")
SPEAKER_MARK = re.compile(r"[：:]")
NEGATIVE_TERMS = ("无字幕", "无文字", "无logo", "无水印", "不要音乐")
POV_BODY = ("手", "袖", "鞋")


def finding(rule: str, severity: str, message: str, ref: str = "") -> dict[str, Any]:
    return {"rule": rule, "severity": severity, "message": message, "ref": ref}


def _fail(rule: str, msg: str, ref: str = "") -> dict[str, Any]:
    return finding(rule, "blocker", msg, ref)


def _major(rule: str, msg: str, ref: str = "") -> dict[str, Any]:
    return finding(rule, "major", msg, ref)


def _minor(rule: str, msg: str, ref: str = "") -> dict[str, Any]:
    return finding(rule, "minor", msg, ref)


def passed(findings: Iterable[dict[str, Any]]) -> bool:
    return not any(f["severity"] == "blocker" for f in findings)


def summarise(findings: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"blocker": 0, "major": 0, "minor": 0}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return {"passed": passed(findings), "counts": counts, "findings": findings}


# ---------------------------------------------------------------- script


def check_script(script: dict[str, Any], *, target_s: float | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    title = str(script.get("title") or "").strip()
    if not title:
        out.append(_major("S-TITLE", "剧本缺标题"))
    if not str(script.get("logline") or "").strip():
        out.append(_major("S-LOGLINE", "剧本缺一句话梗概"))
    style = str(script.get("style") or "")
    if style not in STYLES:
        out.append(_fail("S-STYLE", f"未知 style: {style!r}"))
    if str(script.get("aspect") or "") not in ASPECTS:
        out.append(_fail("S-ASPECT", "画幅必须是 9:16"))
    elif script.get("aspect") != "9:16":
        out.append(_major("S-ASPECT", "短剧默认交付 9:16"))

    chars = {str(c.get("id")): c for c in script.get("characters") or [] if c.get("id")}
    if len(chars) < 2:
        out.append(_minor("S-CHAR", "主要角色少于 2 个，对话戏会单薄"))
    for cid, char in chars.items():
        voice = char.get("voice") or {}
        if not str(voice.get("description") or "").strip():
            out.append(_major("S-VOICE", f"角色 {cid} 缺固定声音描述", cid))
        if not str(voice.get("piper_voice") or "").strip():
            out.append(_major("S-VOICE", f"角色 {cid} 缺 piper 音色", cid))

    scenes = script.get("scenes") or []
    if not scenes:
        out.append(_fail("S-SCENES", "剧本没有任何场景"))
    total_s = 0.0
    total_chars = 0
    for i, scene in enumerate(scenes, start=1):
        ref = str(scene.get("scene_id") or f"scene[{i}]")
        header = str(scene.get("header") or "").strip()
        if not SCENE_HEADER_RE.match(header):
            out.append(_fail("S-HEADER", f"场景题头不符合“场号 场景名 [内/外] [日/夜]”: {header!r}", ref))
        light = scene.get("lighting") or {}
        for key in ("direction", "hardness", "warmth", "contrast"):
            if not str(light.get(key) or "").strip():
                out.append(_major("S-LIGHT", f"场景缺光影字段 {key}", ref))  # noqa: PERF401
        for j, beat in enumerate(scene.get("beats") or [], start=1):
            bref = str(beat.get("beat_id") or f"{ref}_b{j}")
            for line in beat.get("action") or []:
                text = str(line).strip()
                if not text.startswith("△"):
                    out.append(_major("S-ACTION-PREFIX", "动作行必须以 △ 开头", bref))
                if any(word in text for word in UNFILMABLE):
                    out.append(_major("S-UNFILMABLE", f"动作行写了镜头拍不到的心理活动: {text[:30]}", bref))
            for line in beat.get("dialogue") or []:
                kind = str(line.get("kind") or "said")
                if kind not in DIALOGUE_KINDS:
                    out.append(_fail("S-DIALOGUE-KIND", f"台词类型必须是 said/inner/vo，得到 {kind!r}", bref))
                speaker = str(line.get("speaker") or "")
                if speaker not in chars:
                    out.append(_fail("S-DIALOGUE-SPEAKER", f"说话人 {speaker!r} 不在角色表", bref))
                if not str(line.get("text") or "").strip():
                    out.append(_fail("S-DIALOGUE-EMPTY", "空台词", bref))

    dialogue = [line for _, _, line in iter_dialogue(script)]
    total_chars = dialogue_chars(dialogue)
    line_seconds = 0.0
    for line in dialogue:
        line_seconds += estimate_seconds(str(line.get("text") or ""))
    action_seconds = 0.0
    for scene in scenes:
        for beat in scene.get("beats") or []:
            action_seconds += 3.0  # one establishing/reaction beat per beat
            action_seconds += 0.2 * sum(len(str(a)) for a in beat.get("action") or [])
    total_s = line_seconds + action_seconds
    target = float(target_s or script.get("duration_target_s") or 60.0)
    if abs(total_s - target) > max(8.0, target * 0.3):
        out.append(_major("S-DURATION", f"估算时长 {total_s:.1f}s 与目标 {target:.0f}s 偏差过大"))
    if total_chars * 0.2 > target * 1.05:
        out.append(_fail("S-DURATION", "台词按每 10 字 2 秒已超过目标时长"))

    hook = script.get("hook") or {}
    if not str(hook.get("first_3s_conflict") or "").strip():
        out.append(_major("S-HOOK", "开头 3 秒没有写明冲突"))
    elif len(str(hook.get("first_3s_conflict"))) > 40:
        out.append(_minor("S-HOOK", "开头冲突描述过长，3 秒内说不完"))

    if style == "game_pov":
        spine = script.get("game_pov") or {}
        for key, label in (("daily", "日常"), ("anomaly", "异常"), ("reversal", "反转")):
            if not str(spine.get(key) or "").strip():
                out.append(_fail("S-GAME-POV", f"game_pov 剧本缺{label}", key))
    return out


# ---------------------------------------------------------------- storyboard


def check_storyboard(
    storyboard: dict[str, Any],
    script: dict[str, Any] | None = None,
    assets: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    segments = storyboard.get("segments") or []
    if not segments:
        return [_fail("B-SEGMENTS", "分镜表没有任何段")]
    if storyboard.get("aspect") != "9:16":
        out.append(_fail("B-ASPECT", "分镜画幅必须是 9:16"))

    scene_of_segment: dict[str, str] = {}
    last_sizes: list[str] = []
    for seg_idx, seg in enumerate(segments):
        seg_id = str(seg.get("segment_id") or f"seg[{seg_idx}]")
        shots = seg.get("shots") or []
        dur = float(seg.get("duration_s") or sum(float(s.get("duration_s") or 0) for s in shots))
        if not (5.0 <= dur <= 15.0):
            sev = _fail if dur > 16.0 or dur < 3.0 else _major
            out.append(sev("B-SEG-DURATION", f"段长 {dur:.1f}s 不在 5–15s", seg_id))
        if not (2 <= len(shots) <= 4):
            out.append(_major("B-SEG-SHOTS", f"段内有 {len(shots)} 镜，应为 2–4 镜", seg_id))
        if not str(seg.get("event") or "").strip():
            out.append(_major("B-ONE-EVENT", "每段只讲一件事：段缺 event", seg_id))
        sound = str(seg.get("sound") or "").strip()
        if not sound:
            out.append(_major("B-SOUND", "段缺声音描述", seg_id))

        seg_scenes = {str(s.get("scene_id") or "") for s in shots}
        if len(seg_scenes) > 1:
            out.append(_fail("B-SCENE-CUT", "换场景必须切段，一个段不能跨场景", seg_id))
        if len(seg_scenes) == 1:
            scene_of_segment[seg_id] = next(iter(seg_scenes))

        for j, shot in enumerate(shots):
            sid = str(shot.get("shot_id") or f"{seg_id}_s{j + 1}")
            size = str(shot.get("size") or "")
            if size not in SHOT_SIZES:
                out.append(_fail("B-SIZE", f"未知景别 {size!r}", sid))
            last_sizes.append(size)
            if len(last_sizes) >= 3 and len(set(last_sizes[-3:])) == 1:
                out.append(_major("B-SAME-SIZE", "连续 3 个同景别", sid))
            if not str(shot.get("staging") or "").strip():
                out.append(_fail("B-STAGING", "先写站位再写动作：缺 staging", sid))
            if not str(shot.get("action") or "").strip():
                out.append(_fail("B-ACTION", "镜头缺动作", sid))
            if j > 0 and not str(shot.get("continues_from") or "").strip():
                out.append(_major("B-CONTINUITY", "动作要接上一段结尾：缺 continues_from", sid))
            if not str(shot.get("sound") or "").strip():
                out.append(_major("B-SOUND", "镜头缺声音描述", sid))
            elif sound and shot.get("sound") != sound:
                out.append(_major("B-SOUND-REUSE", "同一段的声音描述必须原样复用", sid))
            for key in ("camera", "lighting", "subject"):
                if not str(shot.get(key) or "").strip():
                    out.append(_major("B-SHOT-FIELD", f"镜头缺 {key}", sid))  # noqa: PERF401
            neg = " ".join(str(x) for x in shot.get("negatives") or [])
            for term in ("无字幕", "无文字"):
                if term not in neg:
                    out.append(_major("B-NEGATIVE", f"否定约束缺 {term}", sid))  # noqa: PERF401
            dlg = shot.get("dialogue") or []
            speakers = {str(d.get("speaker")) for d in dlg}
            if len(speakers) > 1:
                out.append(_fail("B-CUT-SPEAKER", "换人说话就切：一个镜头里出现多个说话人", sid))
            est = sum(estimate_seconds(str(d.get("text") or "")) for d in dlg)
            if float(shot.get("duration_s") or 0) + 0.05 < est:
                out.append(_major("B-DURATION-DIALOGUE", f"镜头 {shot.get('duration_s')}s 装不下台词约 {est:.1f}s", sid))
            if j > 0:
                prev = shots[j - 1]
                if (str(prev.get("size")) == size and str(prev.get("scene_id")) == str(shot.get("scene_id"))
                        and str(prev.get("emotion")) != str(shot.get("emotion"))):
                    # emotion changed without a size/angle change is still a cut,
                    # but flag the flat coverage.
                    out.append(_minor("B-EMOTION-CUT", "情绪已变，建议换景别或角度", sid))
            if re.search(r"[。！？!?]", str(shot.get("action") or "")) and any(w in str(shot.get("action")) for w in BIG_ACTION):
                out.append(_major("B-BIG-ACTION", "大动作要拆三步，不能压在一个镜头里", sid))
        if props := seg.get("props"):
            for prop in props:
                if not str(prop).strip():
                    out.append(_minor("B-PROP", "空道具引用", seg_id))  # noqa: PERF401

    if script is not None:
        script_lines = [(str(line.get("speaker")), str(line.get("text") or ""), str(line.get("kind") or "said"))
                        for _, _, line in iter_dialogue(script)]
        sb_lines = [(str(line.get("speaker")), str(line.get("text") or ""), str(line.get("kind") or "said"))
                    for shot in iter_shots(storyboard) for line in shot.get("dialogue") or []]
        if script_lines != sb_lines:
            out.append(_fail("B-VERBATIM", "分镜台词必须与剧本逐字一致且顺序一致"))

    if assets is not None:
        known = ref_index(assets)
        for shot in iter_shots(storyboard):
            refs = [str(r) for r in shot.get("refs") or []]
            if not refs:
                out.append(_fail("B-REFS", "镜头没有参考图 @图片N", str(shot.get("shot_id"))))
            for ref in refs:
                if ref not in known:
                    out.append(_fail("B-REFS", f"参考图 {ref} 不在资产清单"))  # noqa: PERF401
        for ref in known:
            if not any(ref in (s.get("refs") or []) for s in iter_shots(storyboard)):
                out.append(_minor("B-REFS-UNUSED", f"资产 {ref} 没有被任何镜头使用"))  # noqa: PERF401
    return out


# ---------------------------------------------------------------- assets


def check_assets(assets: dict[str, Any], script: dict[str, Any], storyboard: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    images = assets.get("images") or []
    if not images:
        return [_fail("A-IMAGES", "资产清单为空")]
    seen_refs: list[str] = []
    char_ids = {str(c.get("id")) for c in script.get("characters") or []}
    dialogue_scenes = {
        str(scene.get("scene_id"))
        for scene in script.get("scenes") or []
        if any((beat.get("dialogue") or []) for beat in scene.get("beats") or [])
    }
    for _i, img in enumerate(images, start=1):
        ref = str(img.get("ref") or "")
        if not PICTURE_REF_RE.fullmatch(ref):
            out.append(_fail("A-REF", f"参考图编号必须是 @图片N，得到 {ref!r}"))
        elif ref in seen_refs:
            out.append(_fail("A-REF", f"参考图编号重复 {ref}"))
        else:
            seen_refs.append(ref)
        kind = str(img.get("kind") or "")
        prompt = str(img.get("prompt") or "")
        usage = str(img.get("usage") or "")
        if not usage.strip():
            out.append(_major("A-USAGE", f"{ref} 没写用途", ref))
        if kind == "character_identity":
            for term in ("正面", "侧面", "背面", "表情", "白底"):
                if term not in prompt:
                    out.append(_fail("A-IDENTITY", f"角色身份板缺 {term}", ref))  # noqa: PERF401
            if "鞋" not in prompt:
                out.append(_major("A-IDENTITY", "角色全身图要在白底上写清鞋子", ref))
            if not img.get("character_id"):
                out.append(_major("A-IDENTITY", "身份板没绑定角色 id", ref))
        elif kind == "character_portrait":
            for term in ("正面", "白底", "表情", "胸像"):
                if term not in prompt:
                    out.append(_major("A-IDENTITY", f"角色肖像缺 {term}", ref))  # noqa: PERF401
            if not img.get("character_id"):
                out.append(_major("A-IDENTITY", "肖像没绑定角色 id", ref))
        elif kind == "scene":
            if not any(w in prompt for w in ("无人", "空镜", "没有人物")):
                out.append(_fail("A-SCENE-EMPTY", "场景图必须无人", ref))
            if any(w in prompt for w in ("主角", "人物站在", "一个男人", "一个女人")):
                out.append(_fail("A-SCENE-EMPTY", "场景提示词写进了人物", ref))
            if str(img.get("scene_id") or "") in dialogue_scenes:
                coverage = img.get("coverage") or []
                for term in ("正打", "反打", "大全景"):
                    if term not in coverage:
                        out.append(_fail("A-COVERAGE", f"对话戏场景缺 {term}", ref))  # noqa: PERF401
        elif kind == "prop":
            if "白底" not in prompt:
                out.append(_major("A-PROP", "道具图白底", ref))
            if not (img.get("size_cm") or "尺寸" in prompt):
                out.append(_major("A-PROP", "道具图要写实际尺寸", ref))
        elif kind not in ("expression", "game_ui"):
            out.append(_major("A-KIND", f"未知资产类型 {kind!r}", ref))

    for cid in char_ids:
        if not any(img.get("character_id") == cid and img.get("kind") in ("character_identity", "character_portrait") for img in images):
            out.append(_fail("A-CHAR-ASSET", f"角色 {cid} 没有身份/肖像图"))  # noqa: PERF401
    known = ref_index(assets)
    for shot in iter_shots(storyboard):
        for ref in shot.get("refs") or []:
            if str(ref) not in known:
                out.append(_fail("A-REF-BOUND", f"镜头引用 {ref} 不存在"))  # noqa: PERF401
    return out


# ---------------------------------------------------------------- segments / edit


def check_segments(storyboard: dict[str, Any], assets: dict[str, Any]) -> list[dict[str, Any]]:
    """A segment is ready only when every shot has an existing image and sound cue."""
    out: list[dict[str, Any]] = []
    known = ref_index(assets)
    for seg in storyboard.get("segments") or []:
        seg_id = str(seg.get("segment_id"))
        total = sum(float(s.get("duration_s") or 0) for s in seg.get("shots") or [])
        if total <= 0:
            out.append(_fail("G-DURATION", "段总时长为 0", seg_id))
        for shot in seg.get("shots") or []:
            if not any(ref in known for ref in shot.get("refs") or []):
                out.append(_fail("G-REFS", "段内镜头没有可用参考图", str(shot.get("shot_id"))))  # noqa: PERF401
    return out


def check_edit(edit: dict[str, Any], script: dict[str, Any], storyboard: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    items = edit.get("items") or []
    shot_order = [str(s.get("shot_id")) for s in iter_shots(storyboard)]
    if [str(i.get("shot_id")) for i in items] != shot_order:
        out.append(_fail("E-ORDER", "剪辑单顺序必须与分镜/剧本一致"))
    script_lines = [(str(line.get("speaker")), str(line.get("text") or "")) for _, _, line in iter_dialogue(script)]
    sub_lines = [(str(r.get("speaker")), str(r.get("text") or "")) for r in edit.get("subtitles") or []]
    if script_lines != sub_lines:
        out.append(_fail("E-VERBATIM", "字幕必须按剧本文稿逐字对齐"))
    styles = edit.get("subtitle_styles") or {}
    for kind in DIALOGUE_KINDS:
        if not styles.get(kind):
            out.append(_fail("E-SUB-STYLE", f"字幕缺 {kind} 样式"))  # noqa: PERF401
    if styles.get("said", {}).get("color") == styles.get("inner", {}).get("color"):
        out.append(_fail("E-INNER-COLOR", "内心独白字幕必须异色"))
    long_dialogue_shots = {
        str(line.get("shot_id"))
        for line in edit.get("subtitles") or []
        if estimate_seconds(str(line.get("text") or "")) > 5.0
    }
    overlayed = {str(o.get("during_shot")) for o in edit.get("reaction_overlays") or []}
    for shot_id in sorted(long_dialogue_shots - overlayed):
        out.append(_major("E-REACTION", f"长台词 {shot_id} 应保留声音并盖 1–2s 听者反应镜头", shot_id))  # noqa: PERF401
    loud = edit.get("loudness") or {}
    if float(loud.get("target_lufs", 0)) > -14.0 or float(loud.get("true_peak", 0)) > -1.5:
        out.append(_major("E-LOUDNESS", "响度目标应为 -14 LUFS / 真峰值 ≤ -1.5 dBTP"))
    layers = edit.get("layers") or []
    if layers and layers != ["dialogue", "sfx", "music"]:
        out.append(_major("E-LAYERS", "混音层级必须是 对白>音效>配乐"))
    if not str(edit.get("ending_suspense") or "").strip():
        out.append(_major("E-END", "结尾必须停在悬念"))
    if edit.get("ai_label") is not True:
        out.append(_fail("E-AI-LABEL", "成片必须带“AI 生成”标识"))
    if edit.get("bgm") and not edit.get("bgm_allowed"):
        out.append(_minor("E-BGM", "分镜要求不要 BGM；如加配乐必须显式允许并压低"))
    return out


# ---------------------------------------------------------------- game pov


def check_game_pov(script: dict[str, Any], storyboard: dict[str, Any], edit: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if str(script.get("style")) != "game_pov":
        return out
    spine = script.get("game_pov") or {}
    for key in ("daily", "anomaly", "reversal"):
        if not str(spine.get(key) or "").strip():
            out.append(_fail("G-SPINE", f"game_pov 缺 {key}", key))  # noqa: PERF401
    shots = list(iter_shots(storyboard))
    pov = [s for s in shots if str(s.get("mode")) == "pov"]
    third = [s for s in shots if str(s.get("mode")) == "third_person_pass"]
    if not pov:
        out.append(_fail("G-POV", "game_pov 没有任何第一人称 POV 镜头"))
    if not third:
        out.append(_fail("G-THIRD", "game_pov 需要第三人称过场镜头限定画面人物构成"))
    for shot in pov:
        info = shot.get("pov") or {}
        for key in ("where", "looking", "next_move"):
            if not str(info.get(key) or "").strip():
                out.append(_fail("G-POV-FIELDS", f"POV 提示词缺 {key}", str(shot.get("shot_id"))))  # noqa: PERF401
        body = " ".join(str(info.get(k) or "") for k in ("where", "looking", "next_move", "body"))
        if not any(term in body for term in POV_BODY):
            out.append(_fail("G-POV-BODY", "POV 必须写清可见的手/袖子/鞋", str(shot.get("shot_id"))))
    for shot in third:
        comp = shot.get("composition") or {}
        for key in ("protagonist", "other", "camera"):
            if not str(comp.get(key) or "").strip():
                out.append(_fail("G-THIRD-COMP", f"过场镜头缺人物构成 {key}", str(shot.get("shot_id"))))  # noqa: PERF401
    for shot in shots:
        neg = " ".join(str(x) for x in shot.get("negatives") or [])
        for term in NEGATIVE_TERMS:
            if term not in neg:
                out.append(_fail("G-NEGATIVE", f"game_pov 否定约束缺 {term}", str(shot.get("shot_id"))))  # noqa: PERF401
    overlays = edit.get("ui_overlays") or []
    if not overlays:
        out.append(_major("G-UI", "game_pov 剪辑单没有交互提示 UI 叠加"))
    timeline_end = float(edit.get("duration_s") or 0.0)
    for ui in overlays:
        t = float(ui.get("start_s") or 0)
        if timeline_end and t > timeline_end:
            out.append(_major("G-UI-TIME", f"UI {ui.get('text')} 出现时间超出片长"))
        if not str(ui.get("png") or "").strip():
            out.append(_major("G-UI-PNG", f"UI {ui.get('text')} 没有透明 PNG"))
    if edit.get("dialogue_box") and not edit.get("dialogue_box", {}).get("font_license"):
        out.append(_major("G-FONT", "游戏对话框字体必须写明可商用许可"))
    return out
