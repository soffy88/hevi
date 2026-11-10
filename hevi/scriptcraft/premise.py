"""Premise gate: one sentence, four slots, six questions.

A story enters production only when the four slots are filled and a reader
understands the setup within three sentences.  When they are not, the gate
returns ``change_topic`` plus three complete alternates instead of writing a
script around a vague idea.
"""

from __future__ import annotations

import re
from typing import Any

from .text import sentence_count

SLOTS = ("protagonist", "trigger", "goal", "stakes")
SLOT_LABELS = {
    "protagonist": "弱势身份/处境",
    "trigger": "意外或金手指",
    "goal": "具体目标",
    "stakes": "否则会失去什么",
}
ROUTES = ("男频", "女频", "情感", "复仇", "悬疑", "混合")
QUESTION_KEYS = (
    "genre",
    "identification",
    "strongest_conflict",
    "best_payoff",
    "secret_reversal",
    "route",
)
QUESTION_LABELS = {
    "genre": "类型",
    "identification": "代入谁",
    "strongest_conflict": "最强矛盾",
    "best_payoff": "最大爽点/打动点",
    "secret_reversal": "秘密或反转",
    "route": "路线",
}
GENERIC_GOALS = {"成功", "变强", "改变命运", "复仇", "赢", "幸福", "活下去", "翻身", "搞钱"}
WEAK_MARKERS = (
    "被", "失业", "欠债", "离婚", "单亲", "新人", "实习生", "外卖", "保洁", "护工",
    "农村", "残疾", "生病", "替身", "私生", "养女", "上门", "小职员", "封杀", "破产",
    "坐牢", "失忆", "底层", "临时工", "保姆", "保安", "代驾", "陪诊", "聋", "哑",
)
LOSS_MARKERS = (
    "失去", "坐牢", "离婚", "被赶", "破产", "死", "手术费", "抚养权", "工作", "名声",
    "房子", "孩子", "母亲", "父亲", "清白", "自由", "命", "店铺", "账号", "学位",
)
TRIGGER_MARKERS = (
    "意外", "突然", "收到", "捡到", "醒来", "穿越", "重生", "系统", "金手指", "继承",
    "发现", "被选中", "回到", "获得", "错认", "顶替", "误打", "救下", "拍到", "录到",
)


def _finding(rule: str, severity: str, message: str, ref: str = "") -> dict[str, Any]:
    return {"rule": rule, "severity": severity, "message": message, "ref": ref}


def premise_sentence(slots: dict[str, Any]) -> str:
    return (
        f"一个【{slots.get('protagonist', '')}】的人，"
        f"因为【{slots.get('trigger', '')}】，"
        f"必须【{slots.get('goal', '')}】，"
        f"否则【{slots.get('stakes', '')}】。"
    )


def check_slots(slots: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in SLOTS:
        value = str(slots.get(key) or "").strip()
        if not value:
            out.append(_finding("P-SLOT", "must", f"四槽缺「{SLOT_LABELS[key]}」", key))
    protagonist = str(slots.get("protagonist") or "")
    if protagonist and not any(word in protagonist for word in WEAK_MARKERS):
        out.append(_finding(
            "P-WEAK", "should",
            "主角的弱势身份/处境不够具体（用职业、债务、关系或身体处境写出来）", "protagonist",
        ))
    goal = str(slots.get("goal") or "").strip()
    if goal and (goal in GENERIC_GOALS or len(goal) < 4):
        out.append(_finding(
            "P-GOAL", "must",
            f"目标「{goal}」太抽象；写成能拍出来、能判定输赢的事", "goal",
        ))
    trigger = str(slots.get("trigger") or "")
    if trigger and not any(word in trigger for word in TRIGGER_MARKERS):
        out.append(_finding(
            "P-TRIGGER", "should",
            "意外/金手指不够具体；写清触发了什么", "trigger",
        ))
    stakes = str(slots.get("stakes") or "")
    if stakes and not any(word in stakes for word in LOSS_MARKERS):
        out.append(_finding(
            "P-STAKE", "should",
            "「否则」缺少可失去的具体东西", "stakes",
        ))
    setup = str(slots.get("setup") or "")
    if setup and sentence_count(setup) > 3:
        out.append(_finding(
            "P-LONG", "must",
            f"设定需要 {sentence_count(setup)} 句才懂；超过 3 句就换题",
            "setup",
        ))
    return out


def check_six_questions(questions: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in QUESTION_KEYS:
        if not str(questions.get(key) or "").strip():
            out.append(_finding("P-Q6", "must", f"6 问缺「{QUESTION_LABELS[key]}」", key))
    route = str(questions.get("route") or "")
    if route and route not in ROUTES:
        out.append(_finding("P-Q6-ROUTE", "must", f"路线必须是 {'/'.join(ROUTES)}，得到 {route!r}", "route"))
    return out


def recommend_mode(slots: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
    """Series vs short film, from the shape of the goal and opposition."""
    route = str(questions.get("route") or "")
    goal = str(slots.get("goal") or "")
    conflict = str(questions.get("strongest_conflict") or "")
    reversal = str(questions.get("secret_reversal") or "")
    series_signals = 0
    film_signals = 0
    if route in {"男频", "女频", "复仇"}:
        series_signals += 2
    if route in {"悬疑", "混合", "情感"}:
        film_signals += 1
    if any(word in conflict for word in ("家族", "公司", "集团", "豪门", "多年", "长期", "连环")):
        series_signals += 2
    if any(word in goal for word in ("夺回", "扳倒", "上位", "复仇", "揭开", "查清")):
        series_signals += 1
    if any(word in reversal for word in ("一次", "一夜", "当天", "最后", "真相")):
        film_signals += 1
    if any(word in conflict for word in ("一次", "当天", "这一晚", "一个晚上", "一场")):
        film_signals += 2
    mode = "series" if series_signals >= film_signals else "short_film"
    reason = (
        "目标需要连续升级、反派有多层资源，适合每集一个冲突的连续短剧"
        if mode == "series"
        else "冲突集中在一段时间/一个场地内，适合 5–8 分钟一次收束的短片"
    )
    return {"mode": mode, "reason": reason, "series_signals": series_signals, "film_signals": film_signals}


def _alternates(topic: str) -> list[dict[str, Any]]:
    t = str(topic or "这个话题").strip() or "这个话题"
    return [
        {
            "route": "复仇",
            "protagonist": f"被合伙人踢出公司的项目负责人（{t}）",
            "trigger": "收到一份当年被藏起来的原始合同",
            "goal": "在发布会上拿回署名和股权",
            "stakes": "母亲的手术费和新公司一起没了",
            "one_line": "一个被踢出公司的项目负责人，因为收到原始合同，必须在发布会上拿回署名和股权，否则母亲的手术费和新公司一起没了。",
        },
        {
            "route": "悬疑",
            "protagonist": f"在夜班岗位上的普通员工（{t}）",
            "trigger": "监控里出现了本不该存在的第二个人",
            "goal": "在天亮前找出监控被谁改过",
            "stakes": "被当成凶手带走，失去自由",
            "one_line": "一个在夜班岗位上的普通员工，因为监控里出现第二个人，必须在天亮前找出谁改过监控，否则会被当成凶手带走。",
        },
        {
            "route": "情感",
            "protagonist": f"独自照顾家人的普通人（{t}）",
            "trigger": "发现家人一直瞒着一件旧事",
            "goal": "在家人走之前把这件事问清楚",
            "stakes": "余生都带着误会，失去最后的告别",
            "one_line": "一个独自照顾家人的普通人，因为发现家人一直瞒着一件旧事，必须在家人走之前问清楚，否则余生都带着误会。",
        },
    ]


def evaluate_premise(
    *,
    topic: str = "",
    slots: dict[str, Any] | None = None,
    questions: dict[str, Any] | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    slots = dict(slots or {})
    questions = dict(questions or {})
    findings = check_slots(slots) + check_six_questions(questions)
    must = [f for f in findings if f["severity"] == "must"]
    verdict = "pass" if not must else "change_topic"
    recommendation = recommend_mode(slots, questions)
    if mode in {"series", "short_film"}:
        recommendation["mode"] = mode
        recommendation["reason"] = "用户指定：" + (
            "连续短剧" if mode == "series" else "5–8 分钟短片"
        )
    result: dict[str, Any] = {
        "verdict": verdict,
        "requires_confirmation": True,
        "confirmed": False,
        "one_line": premise_sentence(slots) if slots else "",
        "slots": slots,
        "questions": questions,
        "findings": findings,
        "must_fix": must,
        "recommendation": recommendation,
        "next": "confirm" if verdict == "pass" else "choose_alternate",
    }
    if verdict != "pass":
        result["alternates"] = _alternates(topic)
        result["message"] = "四槽不完整或设定超过 3 句：判「换题」，先从 3 个备选里选一个。"
    return result


def parse_premise_text(text: str) -> dict[str, str]:
    """Best-effort slot extraction from the four-slot sentence form."""
    raw = str(text or "").strip()
    slots = dict.fromkeys(SLOTS, "")
    patterns = {
        "protagonist": r"一个【(.+?)】的人",
        "trigger": r"因为【(.+?)】",
        "goal": r"必须【(.+?)】",
        "stakes": r"否则【(.+?)】",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, raw)
        if match:
            slots[key] = match.group(1).strip()
    if not any(slots.values()):
        slots["setup"] = raw
    return slots


__all__ = [
    "QUESTION_KEYS",
    "QUESTION_LABELS",
    "ROUTES",
    "SLOTS",
    "SLOT_LABELS",
    "check_six_questions",
    "check_slots",
    "evaluate_premise",
    "parse_premise_text",
    "premise_sentence",
    "recommend_mode",
]
