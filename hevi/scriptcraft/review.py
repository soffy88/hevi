"""Three independent review rounds, one thing at a time.

Round 1 (screenwriter) reads premise, characters, causality and dialogue.
Round 2 (continuity) reads information source, time, props, costume and line
length.  Round 3 (production) reads what is hard for AI to shoot and proposes
a shootable rewrite.  Every finding says where it is, what the audience will
see, and how to change it; nothing is rewritten unless the caller selects it.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from .text import (
    NET_LITERARY,
    REACTION_ONLY,
    RESULT_WORDS,
    TOO_CONVENIENT,
    WATER_WORDS,
    document_text,
    estimate_seconds,
    flatten_strings,
    suggested_duration,
)

ROUNDS = (
    ("screenwriter", "编剧轮", "前提/人物/因果/台词"),
    ("continuity", "场记轮", "信息来源/时间位置方向/道具服装/台词时长"),
    ("production", "制作轮", "多人同时动/手部接触/打斗/需看清的字/水火"),
)
SEVERITIES = ("must", "should", "optional")
SEVERITY_LABELS = {"must": "必须修", "should": "应该修", "optional": "可选"}
EVIDENCE_WORDS = ("证据", "录音", "监控", "文件", "截图", "视频", "报表", "遗嘱", "合同")
SOURCE_VERBS = ("拿出", "调出", "播放", "打开", "递给", "举起", "投到", "发到", "拍到", "翻到")
TIME_WORDS = ("早上", "上午", "中午", "下午", "傍晚", "晚上", "夜里", "凌晨", "天亮")
FIGHT_WORDS = ("打人", "打架", "殴打", "踢", "扇", "扭打", "撕打", "推倒", "挥拳", "砸", "踹")
TEXT_WORDS = ("写着", "屏幕显示", "短信", "文件上", "牌子上", "字幕", "聊天记录", "合同上")
WATER_FIRE = ("水", "雨", "淋", "火", "烟", "燃烧", "烧", "蒸汽")


def _finding(
    code: str,
    round_name: str,
    severity: str,
    position: str,
    problem: str,
    audience: str,
    fix: str,
    *,
    patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "round": round_name,
        "round_label": {r[0]: r[1] for r in ROUNDS}[round_name],
        "severity": severity,
        "severity_label": SEVERITY_LABELS[severity],
        "position": position,
        "problem": problem,
        "audience": audience,
        "fix": fix,
        "patch": patch,
    }


def _beats(document: dict[str, Any]) -> list[tuple[str, int, dict[str, Any]]]:
    out: list[tuple[str, int, dict[str, Any]]] = []
    for scene in document.get("scenes") or []:
        sid = str(scene.get("scene_id") or scene.get("scene_no") or "")
        for index, beat in enumerate(scene.get("beats") or [], start=1):
            out.append((sid, index, beat))
    return out


def _action_lines(document: dict[str, Any]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for sid, index, beat in _beats(document):
        for line in beat.get("action") or []:
            out.append((f"{sid}.b{index}", str(line)))
    return out


def _dialogue_lines(document: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for sid, index, beat in _beats(document):
        for line in beat.get("dialogue") or []:
            if isinstance(line, dict):
                out.append((f"{sid}.b{index}", line))
    return out


def _character_names(document: dict[str, Any]) -> list[str]:
    return [str(c.get("name") or "") for c in document.get("characters") or [] if c.get("name")]


def _round_screenwriter(document: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    text_all = document_text(document)
    first_hook = str((document.get("hook") or {}).get("first_3s_conflict") or "")
    first_action = _action_lines(document)
    if not first_hook and not (first_action and any(
        word in first_action[0][1] for word in ("撕", "夺", "推", "摔", "抓住", "揭开", "亮出")
    )):
        out.append(_finding(
            "W-SLOW-OPEN", "screenwriter", "must", "第 1 场前 3 秒",
            "开场没有冲突/危机/反差，先用寒暄或环境铺陈",
            "观众在 3 秒内划走",
            "把最刺激的动作提到第一行；背景放到第 2 个节拍再补",
        ))
    payoffs: list[str] = [str(x) for x in document.get("payoffs") or []]
    for index, payoff in enumerate(payoffs, start=1):
        if not any(word in payoff for word in RESULT_WORDS):
            out.append(_finding(
                "W-PAYOFF", "screenwriter", "must", f"第 {index} 个爽点",
                f"爽点写成反应/情绪：「{payoff}」",
                "观众等不到事情真正发生，会觉得被吊着",
                "改成已发生的结果：拿到/曝光/被带走/签下/当场改口",
            ))
        elif any(word in payoff for word in REACTION_ONLY):
            out.append(_finding(
                "W-REACTION", "screenwriter", "should", f"第 {index} 个爽点",
                f"爽点混进了反应词：「{payoff[:16]}」",
                "反应镜头可以有，但不能代替结果",
                "把反应留给旁观者，爽点只写结果",
            ))
    core_events = [str(x) for x in document.get("core_events") or []]
    seen: dict[str, int] = {}
    for index, event in enumerate(core_events, start=1):
        key = re.sub(r"\s+", "", event)[:18]
        seen[key] = seen.get(key, 0) + 1
        if seen[key] >= 3:
            out.append(_finding(
                "W-LOOP", "screenwriter", "must", f"第 {index} 集",
                "同类事件第三次出现，剧情在绕圈",
                "观众会觉得主角没有前进",
                "给同一件事加一个新代价或新对手，或直接跳到下一步",
            ))
    for word in TOO_CONVENIENT:
        if word in text_all:
            out.append(_finding(
                "W-CONVENIENT", "screenwriter", "should", "剧本",
                f"用了兜底词「{word}」，冲突被巧合解决",
                "爽点站不住，观众不信",
                "让主角自己付代价解决，或让反派先赢一步",
                patch={"op": "replace_text", "find": word, "replace": ""},
            ))
    power = str(document.get("power") or document.get("cheat") or "")
    if power and not any(word in text_all for word in ("代价", "反噬", "失去", "副作用", "限制")):
        out.append(_finding(
            "W-CHEAT-FREE", "screenwriter", "should", "金手指",
            f"金手指「{power}」没有代价或限制",
            "主角一出手就赢，后面没有紧张感",
            "给能力加一个使用条件/次数限制，违反就失去更重要的东西",
        ))
    villain = document.get("villain") or {}
    if isinstance(villain, dict) and villain and not any(
        str(villain.get(key) or "").strip() for key in ("plan", "motive", "reason", "goal")
    ):
        out.append(_finding(
            "W-VILLAIN-DUMB", "screenwriter", "should", "反派",
            "反派只有身份，没有计划和动机",
            "反派会为了剧情降智，观众不信",
            "写清反派这一步想拿什么、下一步准备怎么堵主角",
        ))
    lead_arc = str((document.get("lead") or {}).get("arc") or "")
    if lead_arc and not any(word in text_all for word in ("代价", "失去", "牺牲", "输", "被停", "被带走", "破产")):
        out.append(_finding(
            "W-NO-COST", "screenwriter", "should", "主角弧光",
            "主角一路赢，没有付出代价",
            "爽点会变轻，观众不心疼",
            "让主角至少失去一样具体的东西（工作/住处/关系/名声）",
        ))
    if mode == "short_drama" and not document.get("cliffhanger") and not str(
        (document.get("hook") or {}).get("cliffhanger") or ""
    ):
        last = _action_lines(document)
        if last and not any(word in last[-1][1] for word in ("门", "电话", "视频", "名字", "抬头")):
            out.append(_finding(
                    "W-CLOSED", "screenwriter", "must", "最后一拍",
                    "第 1 集自己把自己讲完了，没有卡点",
                    "观众没有理由点下一集",
                    "把答案扣住一半：只给动作/物件/一句话，不给结果",
                ))
    for word in NET_LITERARY:
        if word in text_all:
            out.append(_finding(
                "W-NET-LIT", "screenwriter", "should", "台词/动作",
                f"网文腔「{word}」",
                "一听就是写的，不像人在说话",
                f"删掉「{word}」，换成具体动作或短句",
                patch={"op": "replace_text", "find": word, "replace": ""},
            ))
    water_hits = [w for w in WATER_WORDS if w in text_all]
    if len(water_hits) > 3:
        out.append(_finding(
            "W-WATER", "screenwriter", "should", "全篇",
            f"水词过多：{'、'.join(water_hits[:6])}",
            "节奏被解释拖慢",
            "每句台词只留推进/激化/揭示之一，解释性句子删掉",
        ))
    for sid, index, beat in _beats(document):
        dialogue = beat.get("dialogue") or []
        chars = sum(len(str(line.get("text") or "")) for line in dialogue if isinstance(line, dict))
        if chars > 120 and len(beat.get("action") or []) <= 1:
            out.append(_finding(
                "W-TV", "screenwriter", "should", f"{sid}.b{index}",
                f"一个节拍里 {chars} 字台词却只有一个动作，像电视剧",
                "手机竖屏会变成两个人干说",
                "每 40–60 字加一个动作/反应，或拆成两个节拍",
            ))
    if mode == "short_film":
        out.extend(_short_film_flaws(document, text_all))
    return out


def _short_film_flaws(document: dict[str, Any], text_all: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    game = document.get("dramatic_game") or {}
    if not game or not all(str(game.get(key) or "").strip() for key in ("deadline", "place", "public", "choice", "rule_object")):
        out.append(_finding(
            "W-SOCIAL-OBS", "screenwriter", "must", "戏剧游戏",
            "只有社会观察，没有时限/场地/公开场合/不可逆选择/规则物件",
            "观众看完只记得一个议题，不记得故事",
            "加一个倒计时、一条规则或一个必须当面做的选择",
        ))
    ending = str(document.get("ending") or "")
    if not ending or any(word in ending for word in ("下一集", "未完", "待续", "第一集")):
        out.append(_finding(
            "W-OPEN-END", "screenwriter", "must", "结尾",
            "结尾没有收，像短剧第一集",
            "短片观众会觉得没看完",
            "让主角做出一个不可逆的选择，给一个与开场呼应的画面",
        ))
    lead = document.get("lead") or {}
    if isinstance(lead, dict):
        for key, label in (("want", "表层目标"), ("need", "隐藏需求"), ("belief", "错误信念")):
            if not str(lead.get(key) or "").strip():
                out.append(_finding(
                    "W-LEAD-LAYER", "screenwriter", "must", f"主角{label}",
                    f"主角缺{label}",
                    "人物只有功能，观众不知道他真正要什么",
                    "补一句：他嘴上要什么、心里缺什么、他一直信错什么",
                ))
    reversals = [r for r in document.get("reversals") or [] if isinstance(r, dict)]
    if len(reversals) < 2 or len(reversals) > 3:
        out.append(_finding(
            "W-REVERSALS", "screenwriter", "must", "反转",
            f"反转 {len(reversals)} 次，应为 2–3 次",
            "少了不够，多了会乱",
            "保留两次：一次改事实，一次改关系或价值",
        ))
    for index, reversal in enumerate(reversals, start=1):
        if str(reversal.get("changes") or "") not in {"fact", "relation", "value", "事实", "关系", "价值"}:
            out.append(_finding(
                "W-REVERSAL-TYPE", "screenwriter", "must", f"反转 {index}",
                "反转没有写清改变的是事实/关系/价值",
                "观众不知道这次反转到底翻了什么",
                "在反转后面标：改的是事实、关系，还是价值判断",
            ))
    motif = document.get("motif") or {}
    if isinstance(motif, dict):
        appearances = int(motif.get("count") or 0)
        if appearances < 3:
            out.append(_finding(
                "W-MOTIF", "screenwriter", "should", "视听母题",
                f"母题只出现 {appearances} 次，应在生活/压力/答案各出现一次",
                "结尾呼应收不回来",
                "把同一个物件/声音/动作在开场、压力最大时、结尾各放一次",
            ))
    subtext = str(document.get("subtext") or "")
    if not subtext or any(word in text_all for word in ("主题是", "这部电影讲的是", "我想表达")):
        out.append(_finding(
            "W-SUBTEXT", "screenwriter", "should", "台词潜台词",
            "人物把主题直接说出来了",
            "观众被教育，而不是被说服",
            "把主题藏进动作和选择里，让人物说眼前的事",
        ))
    return out


def _round_continuity(document: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    props = {str(p.get("name")): p for p in document.get("props") or [] if isinstance(p, dict)}
    action_text = "\n".join(text for _, text in _action_lines(document))
    for word in EVIDENCE_WORDS:
        if word in action_text and not any(verb in action_text for verb in SOURCE_VERBS):
            out.append(_finding(
                "C-SOURCE", "continuity", "should", "证据出现处",
                f"出现了「{word}」，但没写它从哪来/怎么被拿出来",
                "观众会问这是哪来的，情绪断掉",
                "补一个来源动作：从哪掏出、谁递来、在哪翻到",
            ))
    for scene_index, scene in enumerate(document.get("scenes") or [], start=1):
        day_night = str(scene.get("day_night") or "")
        text = "\n".join(flatten_strings(scene))
        for word in TIME_WORDS:
            if word in text and day_night and (
                (day_night == "日" and word in ("夜里", "凌晨", "晚上")) or
                (day_night == "夜" and word in ("早上", "上午", "中午"))
            ):
                out.append(_finding(
                    "C-TIME", "continuity", "should", f"第 {scene_index} 场",
                    f"场标是「{day_night}」，台词/动作里却是「{word}」",
                    "观众会发现时间对不上",
                    "统一场标或改掉台词里的时间词",
                ))
        for prop in props:
            if prop in text and not str(props[prop].get("size_cm") or "").strip():
                out.append(_finding(
                    "C-PROP", "continuity", "must", f"第 {scene_index} 场",
                    f"道具「{prop}」没有尺寸",
                    "AI 会把道具画得忽大忽小",
                    "补 size_cm，并在第一次出现时写清",
                ))
        for character in document.get("characters") or []:
            name = str(character.get("name") or "")
            outfit = str((character.get("outfit") or {}).get("top") or "")
            if name and outfit and name in text and "换衣" in text and "换衣" not in outfit:
                out.append(_finding(
                    "C-COSTUME", "continuity", "optional", f"第 {scene_index} 场",
                    f"{name} 在本场换衣，但角色卡没写第二套",
                    "出图会前后不是同一件衣服",
                    "补第二套服装到角色卡，或删掉换衣动作",
                ))
    for ref, line in _dialogue_lines(document):
        text = str(line.get("text") or "")
        declared = line.get("duration_s")
        needed = estimate_seconds(text, cps=4.5)
        if declared is not None and float(declared) + 0.25 < needed:
            out.append(_finding(
                "C-DURATION", "continuity", "must", ref,
                f"台词 {len(text)} 字需 {needed:.1f}s，镜头只给 {float(declared):.1f}s",
                "台词会被截断或加速",
                f"镜头加到 ≥{suggested_duration(text):.1f}s，或删短到 {int(float(declared) * 4.5)} 字内",
            ))
    return out


def _round_production(document: dict[str, Any], filmability: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for sid, index, beat in _beats(document):
        ref = f"{sid}.b{index}"
        joined = " ".join(str(a) for a in beat.get("action") or [])
        if any(word in joined for word in ("同时", "一起", "众人", "所有人", "齐刷刷")):
            out.append(_finding(
                "P-MULTI", "production", "should", ref,
                "多人同时动作，AI 很难保持一致",
                "画面里会出现多只手/多张脸",
                "改成一个人动、其他人只给反应；或拆成两个单人镜头",
            ))
        if any(word in joined for word in ("握手", "扶住", "拉住", "抱住", "抓住对方", "按住", "碰", "拽")):
            out.append(_finding(
                "P-CONTACT", "production", "should", ref,
                "有手部接触",
                "手一接触最容易变形",
                "改成递物/隔桌/只拍手部特写，或拆单人",
            ))
        if any(word in joined for word in FIGHT_WORDS):
            out.append(_finding(
                "P-FIGHT", "production", "should", ref,
                "有打斗过程",
                "AI 打斗容易穿帮",
                "只拍动手前一秒、倒地后的结果、旁观者反应",
            ))
        if any(word in joined for word in TEXT_WORDS):
            out.append(_finding(
                "P-TEXT", "production", "should", ref,
                "画面里需要看清的字",
                "模型生成的字大概率是乱码",
                "文字改后期代码叠加，画面只拍空白纸/屏幕",
            ))
        if any(word in joined for word in WATER_FIRE):
            out.append(_finding(
                "P-ELEMENT", "production", "should", ref,
                "有水/火/雨/烟",
                "水火容易穿帮、闪烁",
                "只拍溅起的水花、湿袖口、远处火光，不拍大面积水火",
            ))
    if filmability:
        for item in filmability.get("findings") or []:
            if item.get("severity") == "must" and item.get("rule") in {"F-STATE", "F-UNFILMABLE", "F-EMOTION"}:
                out.append(_finding(
                    "P-" + str(item.get("rule")), "production", "must",
                    str(item.get("ref") or "剧本"),
                    str(item.get("message") or ""),
                    str(item.get("audience") or "画面会崩"),
                    str(item.get("fix") or "改成可拍动作"),
                ))
    return out


def _dedupe(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for item in findings:
        key = (item["code"], item["position"], item["problem"])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def review_document(
    document: dict[str, Any],
    *,
    mode: str = "short_drama",
    stage: str = "",
    filmability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rounds = {
        "screenwriter": _round_screenwriter(document, mode),
        "continuity": _round_continuity(document),
        "production": _round_production(document, filmability),
    }
    for name, items in rounds.items():
        rounds[name] = _dedupe(items)
    flat: list[dict[str, Any]] = []
    for name, items in rounds.items():
        for index, item in enumerate(items, start=1):
            item["id"] = f"{name[:1].upper()}{index:02d}"
            flat.append(item)
    counts = {severity: sum(1 for f in flat if f["severity"] == severity) for severity in SEVERITIES}
    score = max(0, 100 - counts["must"] * 20 - counts["should"] * 5 - counts["optional"])
    return {
        "stage": stage or mode,
        "mode": mode,
        "rounds": [
            {
                "round": name,
                "label": label,
                "focus": focus,
                "findings": rounds[name],
                "counts": {s: sum(1 for f in rounds[name] if f["severity"] == s) for s in SEVERITIES},
            }
            for name, label, focus in ROUNDS
        ],
        "findings": flat,
        "summary": {
            "must": counts["must"],
            "should": counts["should"],
            "optional": counts["optional"],
            "score": score,
            "passed": counts["must"] == 0,
        },
        "policy": "默认不改原稿：用户在画布勾选后只改选中处。",
    }


def apply_selected(
    document: dict[str, Any],
    review: dict[str, Any],
    selected_ids: list[str],
) -> dict[str, Any]:
    """Return a copy with only the selected findings applied.

    Findings carry a deterministic ``patch`` when the edit is safe (for
    example removing a net-literary filler word).  Findings without a patch
    are reported back as ``manual`` and never guessed at.
    """
    out = copy.deepcopy(document)
    selected = set(selected_ids)
    applied: list[str] = []
    manual: list[str] = []
    for finding in review.get("findings") or []:
        if finding.get("id") not in selected:
            continue
        patch = finding.get("patch")
        if not patch:
            manual.append(finding.get("id", ""))
            continue
        if patch.get("op") == "replace_text":
            find = str(patch.get("find") or "")
            replace = str(patch.get("replace") or "")
            if find:
                _replace_in_document(out, find, replace)
                applied.append(finding.get("id", ""))
        else:
            manual.append(finding.get("id", ""))
    out["review_applied"] = applied
    out["review_manual"] = manual
    return out


def _replace_in_document(value: Any, find: str, replace: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str):
                value[key] = item.replace(find, replace)
            else:
                _replace_in_document(item, find, replace)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, str):
                value[index] = item.replace(find, replace)
            else:
                _replace_in_document(item, find, replace)


__all__ = [
    "ROUNDS",
    "SEVERITIES",
    "SEVERITY_LABELS",
    "apply_selected",
    "review_document",
]
