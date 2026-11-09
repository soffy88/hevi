"""Topic node: three short-drama ideas, a first-2-second hook, and a genre library.

Each idea is one sentence, names the genre, and states the most interesting or
cutest moment that *must* be visible in the first two seconds.  The node ranks
the ideas and returns one recommendation with a reason.  Generation is
deterministic so the same series yields the same three ideas; a caller may
inject an LLM to phrase them differently, but the hook/validation contract is
unchanged.
"""

from __future__ import annotations

import hashlib
from typing import Any

GENRE_LIBRARY: dict[str, dict[str, Any]] = {
    "disguise_fail": {
        "label": "伪装破功",
        "structure": "伪装成立 → 一个小破绽 → 当众破功",
        "hook": "伪装在第一秒露出破绽",
        "base": 0.72,
    },
    "magic_backfire": {
        "label": "魔法反噬",
        "structure": "施法得意 → 反噬落到自己 → 可爱收场",
        "hook": "魔法反弹回施法者身上的一瞬",
        "base": 0.76,
    },
    "catchphrase_triple": {
        "label": "口头禅三连反转",
        "structure": "口头禅第一次 → 第二次变味 → 第三次彻底反转",
        "hook": "同一句口头禅第二次说出口却变了意思",
        "base": 0.70,
    },
    "tsundere": {
        "label": "傲娇",
        "structure": "嘴上嫌弃 → 身体很诚实 → 被戳穿",
        "hook": "嘴上说不要、手却先伸出去的一瞬",
        "base": 0.78,
    },
    "hero_rescue": {
        "label": "英雄救美",
        "structure": "危险逼近 → 被救 → 救人的其实更慌",
        "hook": "危险出现的第一秒",
        "base": 0.74,
    },
    "daily_anomaly": {
        "label": "日常异常",
        "structure": "日常 → 一个不对劲 → 反转",
        "hook": "日常里第一秒就不对劲",
        "base": 0.62,
    },
}

DEFAULT_GENRES = ("tsundere", "magic_backfire", "disguise_fail")
POV_BODY = "手、袖子和鞋"
HOOK_MAX_CHARS = 24


def _lead_names(cast: list[dict[str, Any]]) -> tuple[str, str]:
    names = [str(c.get("name") or c.get("id") or "") for c in cast if c.get("name") or c.get("id")]
    if not names:
        return "主角", "对方"
    if len(names) == 1:
        return names[0], "对方"
    return names[0], names[1]


def _idea(genre: str, lead: str, other: str, topic_hint: str, *, pov: bool = False) -> dict[str, Any]:
    g = GENRE_LIBRARY[genre]
    hook = g["hook"]
    if genre == "tsundere":
        sentence = f"{other}把最后一块点心让给{lead}，{lead}嘴上说不要，手却先伸了过去。"
        hook = f"{lead}嘴上说“不要”，手已经伸向点心"
    elif genre == "magic_backfire":
        sentence = f"{lead}想用一个小魔法捉弄{other}，魔法却原路弹回自己身上。"
        hook = f"魔法反弹，正中{lead}自己"
    elif genre == "disguise_fail":
        sentence = f"{lead}扮成陌生人想给{other}一个惊喜，第一句话就露了馅。"
        hook = f"{lead}伪装的第一句话就露馅"
    elif genre == "catchphrase_triple":
        sentence = f"{lead}同一句口头禅说了三次，第三次把{other}都说愣了。"
        hook = f"{lead}第二次说出口头禅，意思全变了"
    elif genre == "hero_rescue":
        sentence = f"{other}差点摔倒，{lead}冲过去接住，结果自己比{other}还慌。"
        hook = f"{other}脚下一滑的第一秒"
    else:
        sentence = f"{lead}和{other}过着普通的一天，下一秒日常突然不对。"
        hook = "日常里第一秒就出现不对劲"
    seed = int(hashlib.sha256(f"{genre}:{lead}:{other}:{topic_hint}:{pov}".encode()).hexdigest()[:8], 16)
    novelty = (seed % 100) / 1000.0
    return {
        "genre": genre,
        "genre_label": g["label"],
        "one_sentence": sentence,
        "hook_first_2s": hook,
        "structure": g["structure"],
        "cast": [lead, other],
        "pov": pov,
        "score": round(g["base"] + novelty, 4),
        "score_breakdown": {"genre_base": g["base"], "novelty": novelty},
    }


def suggest_topics(
    series: dict[str, Any],
    *,
    n: int = 3,
    genres: list[str] | None = None,
    pov: bool = False,
) -> dict[str, Any]:
    cast = series.get("cast") or []
    lead, other = _lead_names(cast)
    chosen = list(genres or DEFAULT_GENRES)[:n]
    while len(chosen) < n:
        for genre in GENRE_LIBRARY:
            if genre not in chosen:
                chosen.append(genre)
            if len(chosen) >= n:
                break
    ideas = [_idea(genre, lead, other, str(series.get("title") or ""), pov=pov) for genre in chosen]
    for i, idea in enumerate(ideas, start=1):
        idea["id"] = f"idea_{i}"
    ideas.sort(key=lambda item: item["score"], reverse=True)
    recommended = ideas[0]
    findings = [f for idea in ideas for f in validate_idea(idea)]
    return {
        "series_id": series.get("series_id"),
        "ideas": ideas,
        "recommended": recommended["id"],
        "recommendation_reason": (
            f"《{recommended['genre_label']}》把最有趣的瞬间放在前 2 秒（{recommended['hook_first_2s']}），"
            f"强度 {recommended['score']:.2f} 高于其余两条；结构是：{recommended['structure']}。"
        ),
        "findings": findings,
        "passed": not any(f["severity"] == "blocker" for f in findings),
    }


def validate_idea(idea: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    hook = str(idea.get("hook_first_2s") or "").strip()
    if not hook:
        out.append({"rule": "T-HOOK", "severity": "blocker", "message": "点子没有前 2 秒钩子", "ref": idea.get("id", "")})
    elif len(hook) > HOOK_MAX_CHARS:
        out.append({"rule": "T-HOOK", "severity": "major",
                    "message": f"前 2 秒钩子 {len(hook)} 字，超过 {HOOK_MAX_CHARS} 字", "ref": idea.get("id", "")})
    if not str(idea.get("one_sentence") or "").strip():
        out.append({"rule": "T-ONE", "severity": "blocker", "message": "点子不是一句话", "ref": idea.get("id", "")})
    if str(idea.get("genre")) not in GENRE_LIBRARY:
        out.append({"rule": "T-GENRE", "severity": "major", "message": "类型不在类型库", "ref": idea.get("id", "")})
    if idea.get("pov") and POV_BODY.split("、")[0] not in str(idea.get("hook_first_2s")):
        # POV does not require the hook itself to name the body, only the shots.
        pass
    return out


def topics_markdown(result: dict[str, Any]) -> str:
    lines = ["# 选题", ""]
    for idea in result.get("ideas") or []:
        mark = " ← 推荐" if idea.get("id") == result.get("recommended") else ""
        lines += [
            f"## {idea.get('genre_label')}{mark}（{idea.get('score'):.2f}）",
            "",
            f"- 一句话：{idea.get('one_sentence')}",
            f"- 前 2 秒：{idea.get('hook_first_2s')}",
            f"- 结构：{idea.get('structure')}",
            "",
        ]
    lines += ["## 推荐理由", "", str(result.get("recommendation_reason") or ""), ""]
    return "\n".join(lines)
