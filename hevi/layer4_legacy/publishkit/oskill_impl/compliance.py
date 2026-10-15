"""合规自查（oskill 层）。上游 ``compliance.md`` 三条红线：

1. 主角是事 / 公司 / 现象，不碰活人私德与塌房类措辞；
2. 估算与质疑有标注；
3. 无投资建议措辞，结尾问"你会不会"而不是"该不该买"。

规则只对**实际生成的文案**做检查，命中即失败并给出原句。
"""

from __future__ import annotations

import re

from hevi.layer4_legacy.publishkit.oprim_impl.contracts import ComplianceFinding, ScriptDoc

_INVEST_BANNED = ("必赚", "稳赚", "抄作业", "建议买入", "无风险收益", "保本")
_SENSATIONAL = ("翻车", "塌房", "割韭菜", "骗子", "黑幕")
_PERSON_PATTERN = re.compile(r"[\u4e00-\u9fa5]{2,4}(?:总|老师|哥|姐|先生|女士|教授|董事长)")
_PERSON_BANNED_TAIL = ("总统", "主席", "总理")  # 公开职务属可讲范围外的绕行区提示
_BYPASS_TOPICS = ("政治", "宗教", "民族", "司法", "灾难", "伤亡", "未成年人")
_ESTIMATE = re.compile(r"(据报道|被质疑|舆论认为|估算|预计|报道称|数据表明|公开资料)")
_ASK_BUYS = re.compile(r"(该不该买|要不要买|值不值得买|买不买)")
_ASK_EXPERIENCE = re.compile(r"(你会不会|你会先|你更|你有没有|你是否|你能不能|你会怎么|你会从)")


def _iter_titles_bodies(copies) -> list[tuple[str, str]]:
    for copy in copies:
        yield f"{copy.label}/主推标题", copy.title
        yield f"{copy.label}/备选标题", copy.alt_title
        yield f"{copy.label}/正文", copy.body
        if copy.pinned_comment:
            yield f"{copy.label}/置顶评论", copy.pinned_comment


def run_compliance(doc: ScriptDoc, copies) -> list[ComplianceFinding]:
    """对文案全集 + 文稿跑三条红线。"""

    findings: list[ComplianceFinding] = []
    pairs = list(_iter_titles_bodies(copies))

    banned_hits = [
        f"{where}: {word}"
        for where, text in pairs
        for word in _INVEST_BANNED
        if word in text
    ]
    findings.append(
        ComplianceFinding(
            rule="no_investment_advice",
            passed=not banned_hits,
            hits=tuple(banned_hits),
            detail="不写必赚/稳赚/抄作业/建议买入等投资建议措辞",
        )
    )

    sensational_hits = [
        f"{where}: {word}"
        for where, text in pairs
        for word in _SENSATIONAL
        if word in text
    ]
    findings.append(
        ComplianceFinding(
            rule="no_private_person_attack",
            passed=not sensational_hits,
            hits=tuple(sensational_hits),
            detail="标题与正文不出现塌房/骗/割韭菜类私德指控措辞",
        )
    )

    person_hits = sorted({m.group(0) for _where, text in pairs for m in _PERSON_PATTERN.finditer(text)})
    findings.append(
        ComplianceFinding(
            rule="no_living_person_subject",
            passed=not person_hits,
            hits=tuple(person_hits),
            detail="主角是事/公司/现象，不以活人为主语",
        )
    )

    bypass_hits = [f"{where}: {topic}" for where, text in pairs for topic in _BYPASS_TOPICS if topic in text]
    findings.append(
        ComplianceFinding(
            rule="no_bypass_topics",
            passed=not bypass_hits,
            hits=tuple(bypass_hits),
            detail="绕行区：政治/宗教/民族/司法未决/灾难伤亡/未成年人",
        )
    )

    findings.append(_estimate_rule(doc, copies))
    findings.append(_ending_question_rule(copies))
    return findings


def _estimate_rule(doc: ScriptDoc, copies) -> ComplianceFinding:
    """有估算/质疑口吻的句子，标题与正文必须出现标注词。"""

    needs_hedge = [line.text for line in doc.lines if _ESTIMATE.search(line.text)]
    if not needs_hedge:
        return ComplianceFinding("estimate_is_hedged", True, (), "文稿未使用估算/质疑表述")

    joined = " ".join(text for _where, text in _iter_titles_bodies(copies))
    missing = [line for line in needs_hedge if line not in joined]
    return ComplianceFinding(
        "estimate_is_hedged",
        passed=not missing,
        hits=tuple(missing),
        detail="文稿中的估算/质疑句需要在文案里带标注（据报道/估算/舆论认为）",
    )


def _ending_question_rule(copies) -> ComplianceFinding:
    """结尾互动必须是"你会不会"式经验邀请，不是"该不该买"。"""

    buy_hits: list[str] = []
    ask_hits: list[str] = []
    for where, text in _iter_titles_bodies(copies):
        if _ASK_BUYS.search(text):
            buy_hits.append(where)
        if _ASK_EXPERIENCE.search(text):
            ask_hits.append(where)
    return ComplianceFinding(
        "ending_question_is_experience",
        passed=not buy_hits and bool(ask_hits),
        hits=tuple(buy_hits or ask_hits[:1]),
        detail="结尾问'你会不会/你会先'式经验邀请，不问'该不该买'",
    )