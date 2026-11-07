"""提示词 moderation 预审（规则词表，纯函数，不调用任何模型/API）。

方法论借鉴 Emily2040/seedance-2.0（MIT，仅思路）：生成平台的审核常因“字面触发词”拒绝，
提交前先本地扫一遍：标出风险词、给出电影化/含蓄的等义改写（暗示代替直写、原创角色代替真人/IP、
通用物代替品牌），一次只改风险词，不动其它镜头描述，便于和 retake 单变量归因兼容。

返回 {"ok","risk":"none|low|medium|high","hits":[{term,category,severity,start,end,suggestion}],
      "rewritten","changed":[(old,new)],"notes":[...]}
"""

from __future__ import annotations

import re

_SEV = {"low": 1, "medium": 2, "high": 3}

# (类别, 严重度, [触发词正则...], 改写建议/替换)；替换为 None 时只提示不自动改（需人工判断）
LEXICON: list[tuple[str, str, list[str], str | None]] = [
    ("gore", "high", [r"\bgore\b", r"\bgory\b", r"dismember\w*", r"decapitat\w*", r"severed (?:head|limb)s?",
                      r"\bentrails\b", r"血肉模糊", r"肢解", r"断头", r"开膛"], "aftermath implied off-screen"),
    ("blood", "medium", [r"\bblood(?:y|ied)?\b", r"\bbleeding\b", r"鲜血", r"血迹", r"流血", r"血泊"],
     "dark red stains"),
    ("violence", "medium", [r"\bstab(?:s|bed|bing)?\b", r"\bslaughter\w*", r"\bmurder\w*", r"\bkill(?:s|ed|ing)?\b",
                            r"\btorture\w*", r"\bshoot(?:s|ing)? (?:him|her|them|someone)\b", r"杀死", r"砍杀",
                            r"捅", r"虐待", r"屠杀", r"枪杀"], "a tense confrontation"),
    ("weapon", "low", [r"\bgun\b", r"\bpistol\b", r"\brifle\b", r"\bknife\b", r"\bblade\b", r"枪支?", r"匕首", r"刀刃"],
     "prop tool"),
    ("sexual", "high", [r"\bnude\b", r"\bnaked\b", r"\bnsfw\b", r"\bsex(?:ual|y)?\b", r"\btopless\b", r"\berotic\b",
                        r"\blingerie\b", r"裸体", r"全裸", r"裸露", r"色情", r"性感", r"情色", r"内衣"],
     "fully clothed, tasteful"),
    ("minor", "high", [r"\bchild(?:ren)?\b", r"\bkids?\b", r"\bminors?\b", r"\bteen(?:ager)?s?\b", r"\bschoolgirl\b",
                       r"儿童", r"小孩", r"未成年", r"幼女", r"女学生"], None),
    ("self_harm", "high", [r"\bsuicid\w*", r"self[- ]harm", r"cut(?:s|ting)? (?:her|his) wrists?", r"自杀", r"自残",
                           r"割腕"], "a moment of quiet despair"),
    ("drugs", "medium", [r"\bcocaine\b", r"\bheroin\b", r"\bmeth\b", r"\binject(?:s|ing)? drugs?\b", r"吸毒", r"毒品",
                         r"注射毒"], "a hazy, disoriented moment"),
    ("hate", "high", [r"\bnazi\w*", r"\bswastika\b", r"\bkkk\b", r"纳粹", r"卐"], "a fictional authoritarian emblem"),
    ("real_person", "high", [r"\b(?:elon musk|donald trump|joe biden|taylor swift|xi jinping|barack obama|"
                             r"tom cruise|keanu reeves|scarlett johansson)\b", r"马斯克", r"特朗普", r"拜登",
                             r"习近平", r"泰勒[·・]?斯威夫特"], "an original character (describe look, not identity)"),
    ("ip_brand", "medium", [r"\b(?:mickey mouse|spider-?man|batman|superman|pikachu|harry potter|darth vader|"
                            r"iron man|elsa|mario)\b", r"\b(?:coca-?cola|pepsi|nike|adidas|apple logo|"
                            r"mcdonald'?s|starbucks|disney)\b", r"米老鼠", r"蜘蛛侠", r"蝙蝠侠", r"皮卡丘",
                            r"哈利[·・]?波特", r"可口可乐", r"耐克", r"迪士尼", r"星巴克"],
     "an original, unbranded design"),
    ("politics", "medium", [r"\bflag burning\b", r"\briot\b", r"\bprotest(?:ers)?\b", r"焚烧国旗", r"暴乱", r"游行示威"],
     "a crowded public square"),
]

# 中文触发词用中文改写；英文形容词形态（bloody/bloodied）用形容词改写，保持句子通顺
ZH_REWRITE = {"gore": "画外暗示的后果", "blood": "暗红色痕迹", "violence": "紧张的对峙", "weapon": "道具",
              "sexual": "衣着得体", "self_harm": "安静的低落时刻", "drugs": "恍惚失神的状态",
              "hate": "虚构的权力标志", "real_person": "原创角色（只描述外观）", "ip_brand": "原创无品牌设计",
              "politics": "熙攘的广场"}
ADJ_REWRITE = {"blood": "red-stained", "gore": "grim"}
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _rewrite_for(cat: str, term: str, rep: str | None) -> str | None:
    if rep is None or cat == "custom":
        return rep
    if _CJK_RE.search(term):
        return ZH_REWRITE.get(cat, rep)
    if cat in ADJ_REWRITE and term.lower().endswith(("y", "ied")):
        return ADJ_REWRITE[cat]
    return rep


_COMPILED = [(cat, sev, re.compile("|".join(f"(?:{p})" for p in pats), re.I), rep)
             for cat, sev, pats, rep in LEXICON]


def moderation_prescreen(
    text: str,
    *,
    extra_terms: dict[str, str] | None = None,
    allow: list[str] | tuple = (),
    auto_rewrite: bool = True,
) -> dict:
    """规则预审。extra_terms={词: 替换}（项目自定义，类别 custom/medium）；allow=放行词（如 'knife' 在厨艺片）。"""
    allow_l = {a.lower() for a in allow}
    hits = []
    rules = list(_COMPILED)
    for term, rep in (extra_terms or {}).items():
        rules.append(("custom", "medium", re.compile(re.escape(term), re.I), rep))
    for cat, sev, rx, rep in rules:
        for m in rx.finditer(text):
            if m.group(0).lower() in allow_l:
                continue
            hits.append({"term": m.group(0), "category": cat, "severity": sev, "start": m.start(),
                         "end": m.end(), "_rep": (r2 := _rewrite_for(cat, m.group(0), rep)),
                         "suggestion": r2 or "需人工改写（不自动替换）"})
    hits.sort(key=lambda h: (h["start"], -_SEV[h["severity"]]))
    dedup, last_end = [], -1  # 重叠命中保留最严重/最先的
    for h in hits:
        if h["start"] >= last_end:
            dedup.append(h)
            last_end = h["end"]
    cats = {h["category"] for h in dedup}
    notes = []
    if "minor" in cats and cats & {"sexual", "violence", "gore", "blood"}:
        for h in dedup:
            h["severity"] = "high"
        notes.append("未成年 + 色情/暴力 组合：必须删除该元素，不可改写提交")
    elif "minor" in cats:
        notes.append("出现未成年人：确认镜头内容完全无害，并避免近距离肢体描写")
    if "real_person" in cats:
        notes.append("真人肖像：改为原创角色，只描述外观特征（发型/服装/年龄段），不写姓名")
    risk = "none" if not dedup else max((h["severity"] for h in dedup), key=lambda s: _SEV[s])
    rewritten, changed = text, []
    if auto_rewrite:
        for h in sorted(dedup, key=lambda h: -h["start"]):
            rep = h["_rep"]
            if rep:
                rewritten = rewritten[:h["start"]] + rep + rewritten[h["end"]:]
                changed.append((h["term"], rep))
        changed.reverse()
    for h in dedup:
        h.pop("_rep", None)
    blocked = any(n.startswith("未成年 + ") for n in notes)
    return {"ok": risk in ("none", "low") and not blocked, "risk": risk, "hits": dedup,
            "rewritten": rewritten, "changed": changed, "notes": notes}
