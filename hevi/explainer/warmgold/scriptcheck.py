"""逐拍脚本自检。

每条规则都有稳定 code，失败只重做脚本节点，不牵连渲染。
自检不调用模型、不联网，全部可复算。
"""

from __future__ import annotations

import re
from typing import Any

from hevi.explainer.warmgold import beats as beats_mod
from hevi.explainer.warmgold import style

CTA_ALLOWED = {"issue", "save", "share", "comment", "follow"}
NUMBER_SOURCES = {"实测", "估计", "用户提供", "示意"}
SUCCESS_PROMISE = [
    "保证",
    "包你",
    "一定能",
    "必然",
    "100%",
    "稳赚",
    "必火",
    "必爆",
    "轻松成功",
    "快速变现",
    "涨粉",
    "带你成功",
    "一定能成功",
]
ABSTRACT_ANCHORS = ["经济", "市场", "人生", "社会", "命运", "时代", "人性", "系统"]
DIGITS = re.compile(r"\d+(?:\.\d+)?%?")


def _chars(text: str) -> int:
    return sum(1 for ch in text if not ch.isspace())


def _shot_spans(beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    for beat in beats:
        if spans and spans[-1]["shot_id"] == beat["shot_id"]:
            spans[-1]["end"] = round(beat["t"] + beat["duration"], 4)
            spans[-1]["beats"] += 1
        else:
            spans.append(
                {
                    "shot_id": beat["shot_id"],
                    "start": float(beat["t"]),
                    "end": round(beat["t"] + beat["duration"], 4),
                    "beats": 1,
                    "big": beat.get("big") or "",
                    "small": beat.get("small") or "",
                    "visual": beat.get("visual") or "",
                    "narration": beat.get("narration") or "",
                    "focus": beat.get("focus") or "",
                }
            )
    return spans


def _issue(code: str, message: str, fix: str, severity: str = "fail") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message, "fix": fix}


def check_script(
    script: dict[str, Any],
    beat_data: dict[str, Any] | None = None,
    *,
    music_present: bool | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    shots = list(script.get("shots") or [])
    if not shots:
        return {
            "pass": False,
            "issues": [_issue("S00", "脚本没有镜头", "至少写一个镜头")],
            "metrics": {},
        }

    if beat_data is None:
        beat_data = beats_mod.build_beats(script)
    beats = list(beat_data.get("beats") or [])
    spans = _shot_spans(beats)
    by_id = {s["shot_id"]: s for s in spans}
    beat_s = float(beat_data.get("beat_s") or 0.5)
    total_s = float(beat_data.get("total_s") or sum(b["duration"] for b in beats))

    first_beat = beats[0] if beats else {}
    if not (str(first_beat.get("big") or "").strip() or str(first_beat.get("small") or "").strip()):
        issues.append(_issue("S01", "第 0 帧没有字", "开场第一拍就给出一句大字或小字"))
    if not str(first_beat.get("visual") or "").strip():
        issues.append(_issue("S01", "第 0 帧没有画面", "开场第一拍绑定一个零件"))

    # S02：≤17 秒交出问题或反常识结果。
    result_shot = next(
        (s for s in shots if str(s.get("role") or "") in ("problem", "result", "claim")),
        None,
    )
    if result_shot is None:
        issues.append(_issue("S02", "没有标明问题/结果镜头", "给镜头加 role=problem 或 result"))
    else:
        span = by_id.get(str(result_shot.get("id") or ""))
        end_s = span["end"] if span else float(result_shot.get("at_s") or 0.0)
        if end_s > 17.5:
            issues.append(_issue("S02", f"问题/结果到 {end_s:.1f}s 才出现", "把它提到 17 秒内"))

    # S03 / S04：一屏一个重点、阅读速度。
    for shot in shots:
        sid = str(shot.get("id") or "")
        span = by_id.get(sid)
        if span is None:
            continue
        dur = max(0.4, span["end"] - span["start"])
        big, small = span["big"], span["small"]
        focus = str(shot.get("focus") or "").strip()
        if focus and (focus.count("；") or focus.count(";") or focus.count("、") > 2):
            issues.append(_issue("S03", f"{sid} 一屏多个重点：{focus}", "只留一个重点"))
        if big and re.search(r"[。！？!?].+[。！？!?]", big):
            issues.append(_issue("S03", f"{sid} 大字里不止一句", "大字只留一句"))
        if big and _chars(big) / dur > style.STYLE_CARD["typography"]["big_max_chars_per_sec"]:
            issues.append(
                _issue(
                    "S04",
                    f"{sid} 大字 {_chars(big)} 字 / {dur:.1f}s 超 6 字/秒",
                    "删字或延长这一拍",
                )
            )
        if (
            small
            and _chars(small) / dur > style.STYLE_CARD["typography"]["small_max_chars_per_sec"]
        ):
            issues.append(
                _issue(
                    "S04",
                    f"{sid} 小字 {_chars(small)} 字 / {dur:.1f}s 超 7 字/秒",
                    "删字或延长这一拍",
                )
            )
        if big and not style.text_fits(big, style.STYLE_CARD["typography"]["big_size_px"]):
            issues.append(_issue("S13", f"{sid} 大字超出安全区宽度", "拆成两行或删字"))
        if small and not style.text_fits(small, style.STYLE_CARD["typography"]["small_size_px"]):
            issues.append(_issue("S13", f"{sid} 小字超出安全区宽度", "拆行或删字"))

    # S05 / S12：例子必须能证明主题。
    examples = [s for s in shots if str(s.get("role") or "") == "example"]
    if not examples:
        issues.append(_issue("S05", "没有例子镜头", "加一个 role=example 的镜头"))
    for ex in examples:
        data = ex.get("example") or {}
        missing = [
            k
            for k in ("visible_reading", "invisible_change", "jump_moment")
            if not str(data.get(k) or "").strip()
        ]
        if missing:
            issues.append(
                _issue(
                    "S05",
                    f"{ex.get('id')} 例子缺：{', '.join(missing)}",
                    "补齐看得见的读数/看不见的变化/突变时刻",
                )
            )
        if data.get("supports_theme") is not True:
            issues.append(
                _issue(
                    "S12",
                    f"{ex.get('id')} 例子没有声明能证明主题",
                    "换例子或加例子接力，并写 supports_theme=true",
                )
            )
    if len(examples) > 2:
        issues.append(
            _issue(
                "S12",
                f"例子有 {len(examples)} 个，片子会被扯散",
                "只留一个主例子，其余降为对照",
                "warn",
            )
        )
    conclusion = " ".join(str(s.get("big") or "") + str(s.get("small") or "") for s in shots)
    if examples:
        reading = str((examples[0].get("example") or {}).get("visible_reading") or "")
        if reading and reading[:6] not in conclusion and "这个例子" not in conclusion:
            issues.append(_issue("S12", "结尾没有回收例子", "在收束镜头点回例子的读数", "warn"))

    # S06：情绪最低点 / 兑现拍与音乐能量对齐。
    if music_present is None:
        music_present = bool(script.get("music"))
    if music_present:
        energy = beat_data.get("energy_per_bar") or []
        low_bar = script.get("low_point_bar")
        payoff_bar = script.get("payoff_bar")
        if not energy:
            issues.append(
                _issue("S06", "有音乐但没有逐小节能量", "重新分析音乐或标注为无音乐", "warn")
            )
        else:
            if low_bar is None or int(low_bar) != int(
                min(range(len(energy)), key=lambda i: energy[i])
            ):
                issues.append(
                    _issue(
                        "S06", "情绪最低点不在音乐最空的小节", "把最低点移到能量最小的小节", "warn"
                    )
                )
            if payoff_bar is None or int(payoff_bar) != int(
                max(range(len(energy)), key=lambda i: energy[i])
            ):
                issues.append(
                    _issue("S06", "兑现拍不在音乐回满的小节", "把兑现拍移到能量最大的小节", "warn")
                )
    else:
        if not script.get("low_point_shot") or not script.get("payoff_shot"):
            issues.append(
                _issue(
                    "S06", "无音乐时也要标最低点与兑现拍", "写 low_point_shot / payoff_shot", "warn"
                )
            )

    # S07：结尾回收开头物件，只一种互动。
    ending = script.get("ending") or {}
    anchor = script.get("anchor") or {}
    if str(ending.get("recall_object") or "") != str(anchor.get("object") or ""):
        issues.append(
            _issue("S07", "结尾没有回收开头的日常物件", "让 recall_object 等于 anchor.object")
        )
    cta = str(ending.get("cta") or "")
    if cta not in CTA_ALLOWED:
        issues.append(
            _issue("S07", f"结尾互动类型非法：{cta}", f"只选一种：{', '.join(sorted(CTA_ALLOWED))}")
        )
    if not str(ending.get("cta_text") or "").strip():
        issues.append(_issue("S07", "结尾没有具体互动句", "写一句具体的话，不喊口号"))
    if ending.get("recovers_opening") is not True:
        issues.append(_issue("S07", "没有声明回收开场", "写 recovers_opening=true"))

    # S08 / S15：屏幕数字必须有出处。
    numbers = list(script.get("numbers") or [])
    issues.extend(
        _issue("S08", f"数字 {num.get('value')} 没有合法出处", "标 实测/估计/用户提供/示意")
        for num in numbers
        if str(num.get("source") or "") not in NUMBER_SOURCES
    )
    declared = {str(n.get("value") or "") for n in numbers}
    for shot in shots:
        text = f"{shot.get('big') or ''} {shot.get('small') or ''}"
        issues.extend(
            _issue("S15", f"{shot.get('id')} 屏幕数字 {hit} 没有出处", "补进 numbers 并标来源")
            for hit in DIGITS.findall(text)
            if hit not in declared and not any(hit in d for d in declared)
        )

    # S09：不做成功承诺。
    all_text = " ".join(
        [str(script.get("topic") or "")]
        + [f"{s.get('big') or ''} {s.get('small') or ''} {s.get('narration') or ''}" for s in shots]
    )
    issues.extend(
        _issue("S09", f"出现成功承诺：{word}", "删掉承诺，只讲条件与结果")
        for word in SUCCESS_PROMISE
        if word in all_text
    )

    # S10：开场带「你」的亲历细节。
    first_shot = shots[0]
    opening = script.get("opening") or {}
    first_text = f"{first_shot.get('big') or ''} {first_shot.get('narration') or ''}"
    if "你" not in first_text:
        issues.append(_issue("S10", "开场没有「你」", "用一个带「你」的亲历细节开场"))
    if not str(opening.get("personal_detail") or "").strip():
        issues.append(_issue("S10", "开场没有具体亲历细节", "写清一个具体的、当天可见的细节"))

    # S11：锚必须是日常物件。
    anchor_obj = str(anchor.get("object") or "").strip()
    if not anchor_obj:
        issues.append(_issue("S11", "没有日常物件锚", "选一个观众每天都见得到的东西"))
    elif any(word in anchor_obj for word in ABSTRACT_ANCHORS):
        issues.append(_issue("S11", f"锚太抽象：{anchor_obj}", "换成看得见摸得着的日常物件"))
    if anchor.get("daily") is not True:
        issues.append(_issue("S11", "没有声明锚是日常可见", "确认 anchor.daily=true"))

    # S14：时长与拍数。
    for shot in shots:
        sid = str(shot.get("id") or "")
        if by_id.get(sid, {}).get("beats", 0) < 1:
            issues.append(_issue("S14", f"{sid} 没有分配拍数", "指定 beats≥1"))
    target = script.get("target_seconds")
    if target and not (float(target) * 0.75 <= total_s <= float(target) * 1.25):
        issues.append(
            _issue("S14", f"时长 {total_s:.1f}s 偏离目标 {target}s", "增删镜头或改拍数", "warn")
        )

    fails = [i for i in issues if i["severity"] == "fail"]
    return {
        "pass": not fails,
        "issues": issues,
        "metrics": {
            "shots": len(shots),
            "beats": len(beats),
            "total_s": round(total_s, 2),
            "beat_s": beat_s,
            "examples": len(examples),
            "numbers": len(numbers),
        },
    }


def check_banned_phrases(
    text: str,
    banned: list[str],
    *,
    n: int = 8,
    threshold: float = 0.62,
) -> dict[str, Any]:
    """n-gram 查重：脚本不得复用对标原句。"""
    normalized = re.sub(r"\s+", "", text)
    hits: list[dict[str, Any]] = []
    for phrase in banned:
        p = re.sub(r"\s+", "", phrase)
        if not p:
            continue
        if p in normalized:
            hits.append({"phrase": phrase, "similarity": 1.0, "exact": True})
            continue
        if len(p) < 4:
            continue
        grams_p = {p[i : i + 3] for i in range(len(p) - 2)}
        best = 0.0
        for i in range(max(0, len(normalized) - len(p) + 1)):
            window = normalized[i : i + len(p)]
            grams_w = {window[j : j + 3] for j in range(len(window) - 2)}
            if not grams_p:
                continue
            best = max(best, len(grams_p & grams_w) / len(grams_p | grams_w))
        if best >= threshold:
            hits.append({"phrase": phrase, "similarity": round(best, 3), "exact": False})
    return {"pass": not hits, "hits": hits, "threshold": threshold}
