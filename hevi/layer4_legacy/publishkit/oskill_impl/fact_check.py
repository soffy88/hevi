"""事实核查与来源台账（oskill 层）。

上游 ``fact-check.md`` 要求：每个数字、日期、价格、引语都进来源文件，写清
来源链接/页码、支持哪一句、核对日期；估算值必须标注。

本模块只登记**文稿里真实出现的**事实点，并指向支撑它的那一句；链接需要人
来补，台账会如实标成 ``unsourced``——不编造出处，也不把旁白本身冒充成外部
来源。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from hevi.layer4_legacy.publishkit.oprim_impl.contracts import FactClaim, ScriptDoc

# 数字（含百分比、金额、万/亿、年份）
_NUMBER = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:%|％|个百分点|倍|万|亿|千万|百亿|元|美元|块|年|月|天|小时|分钟|秒|次|人|个|步|天))"
    r"|(?:\d{4}\s*年)"
)
# 中文数字量词（"三步""三个词""第一年"）同样是需要在台账里核口径的事实点。
# 宁可多收进人工复核清单，也不要漏掉一个数字。
_CN_NUMBER = re.compile(
    r"第?[一二三四五六七八九十百千万零两]+(?:个|步|年|月|天|次|人|倍|块|元|万|亿|种|条|件|秒|分钟|小时|%|％)"
)
# 日期
_DATE = re.compile(r"(?:\d{4}\s*年(?:\s*\d{1,2}\s*月)?(?:\s*\d{1,2}\s*日)?|\d{1,2}\s*月\s*\d{1,2}\s*日)")
# 引号内的话
_QUOTE = re.compile(r"[“\"]([^”\"]{2,60})[”\"]")
# 需要标注的估算/质疑措辞（fact-check.md「写」条）
_ESTIMATE = re.compile(r"(据报道|被质疑|舆论认为|估算|预计|据\s*\$\{0,1\}|报道称|数据表明)")

_HEDGE_REQUIRED = re.compile(r"(大约|左右|接近|将近|逾|超\d|超过)")


def extract_claims(doc: ScriptDoc) -> list[FactClaim]:
    """逐句抽出需要出处的事实点。"""

    claims: list[FactClaim] = []
    for line in doc.lines:
        text = line.text
        hedged = bool(_ESTIMATE.search(text))
        note = "文稿已带估算/质疑标注" if hedged else ""

        claims.extend(
            FactClaim("date", m.group(0), line.index, text, note="需核对原始出处")
            for m in _DATE.finditer(text)
        )
        for match in _NUMBER.finditer(text):
            value = match.group(0)
            if _DATE.fullmatch(value):
                continue
            claim_note = note or (
                "含近似量词，需在文案里保留'大约/左右'口径" if _HEDGE_REQUIRED.search(text) else "需核对原始出处"
            )
            claims.append(FactClaim("number", value, line.index, text, note=claim_note))

        seen_cn: set[str] = set()
        for match in _CN_NUMBER.finditer(text):
            value = match.group(0)
            if value in seen_cn or _DATE.fullmatch(value):
                continue
            seen_cn.add(value)
            claims.append(FactClaim("number", value, line.index, text, note=note or "中文数字量词，需核对口径"))

        claims.extend(
            FactClaim("quote", m.group(1), line.index, text, note="引语需真实出处才可加引号")
            for m in _QUOTE.finditer(text)
        )
    return claims


@dataclass(frozen=True)
class SourceLedger:
    payload: dict
    unsourced_count: int
    claim_count: int

    @property
    def status(self) -> str:
        if self.claim_count == 0:
            return "no_claims"
        return "unsourced" if self.unsourced_count else "sourced"


def build_source_ledger(doc: ScriptDoc, claims: list[FactClaim], *, checked_on: str) -> SourceLedger:
    """来源台账：逐条登记 + 口径一致节 + 人工待补清单。"""

    entries = [
        {
            "kind": c.kind,
            "claim": c.text,
            "supports_line": c.line_index,
            "script_excerpt": c.supported_by,
            "source_url": "",
            "source_locator": "",
            "checked_on": checked_on if c.sourced else "",
            "sourced": c.sourced,
            "note": c.note,
        }
        for c in claims
    ]

    # 口径一致节：同一个数字在文稿里出现多次时只登记一次，避免各改一处
    口径: dict[str, int] = {}
    for c in claims:
        口径[c.text] = 口径.get(c.text, 0) + 1
    repeated = {k: v for k, v in 口径.items() if v > 1}

    payload = {
        "status": "unsourced" if any(not c.sourced for c in claims) else ("no_claims" if not claims else "sourced"),
        "checked_on": checked_on,
        "script": doc.path,
        "script_kind": doc.source_kind,
        "claim_count": len(claims),
        "unsourced_count": sum(1 for c in claims if not c.sourced),
        "claims": entries,
        "canonical_numbers": repeated,
        "manual_todo": [
            "给每条 claim 补 source_url / source_locator 后把 sourced 置 true",
            "引入新事实或时效性规则时重新核对并更新 checked_on",
        ],
        "note": "台账只登记文稿里真实出现的数字/日期/引语及其支撑句；链接未由本流程编造。",
    }
    return SourceLedger(payload, payload["unsourced_count"], len(claims))


def hedge_warnings(doc: ScriptDoc) -> list[str]:
    """近似量词但没有估算标注的句子——发布前应当人工确认口径。"""

    return [
        f"L{line.index}: {line.text}"
        for line in doc.lines
        if _HEDGE_REQUIRED.search(line.text) and not _ESTIMATE.search(line.text)
    ]