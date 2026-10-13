"""文案 → 中文旁白重写 + 无编造校验。

契约(STICKDIR_TASK.md §(a)):

* 结构: 钩子 → 打破预期 → 机制 → 结论 → 回调;Style 3 用 铺垫 → 升级 → 反转回调。
* **不得编造原文没有的数字/人名/引语** —— :func:`verify_no_fabrication` 是硬闸。
* 字数按中文约 4–5 字/秒控制, 使旁白时长贴合目标时长。
* 免费 LLM 可用则用, 不可用/超时则走确定性 fallback;两条路径都必须过同一套
  schema + 白名单 + 无编造校验。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from hevi.layer4_legacy.stickdir import whitelist

logger = logging.getLogger(__name__)

#: 中文语速(字/秒)默认值
CPS = 4.5

#: 句子切分标点
_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")

#: 引语: 中英文引号/书名号
_QUOTE_RE = re.compile(r"[「『\"“'‘《]([^」』\"”'’》]{1,40})[」』\"”'’》]")

#: 阿拉伯数字
_ARABIC_RE = re.compile(r"\d+(?:\.\d+)?")

#: 中文数字(数字/单位串)
_CN_NUM_RE = re.compile(r"[零一二三四五六七八九十百千万亿两]+")

#: 中文量词/单位(单字数字后跟这些才算"数值", 否则"一样/一定"这类成语被误报)
_MEASURE = set(
    "倍年月日天秒分时个次种项条步件块元斤吨人岁米度层遍番成折轮场届期段落篇章句字页张枚只支杯碗盘箱包批组套对双打"
)
#: 本身即"数级"的单字(无需量词也算数值)
_CN_UNIT_CHARS = set("十百千万亿")

#: 拉丁词(潜在人名/专名)
_LATIN_RE = re.compile(r"[A-Za-z][A-Za-z\-]{1,}")

#: 常见中文姓氏(用于人名启发式;保守取高频)
_SURNAMES = set(
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊胡凌霍虞万支柯昝管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔吉钮龚程嵇邢滑裴陆荣翁荀羊甄封芮羿储靳汲邴糜松井段富巫乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔阴胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通边扈燕冀郏浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终暨居衡步都耿满弘匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓公"
)

#: 无实义的高频词(不算"人名/专名")
_LATIN_STOP = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "is",
    "are",
    "it",
    "we",
    "you",
    "they",
    "ai",
    "ok",
}


@dataclass
class StageLine:
    """一条旁白: 所属叙事阶段 + 文本。"""

    stage: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return {"stage": self.stage, "text": self.text}


@dataclass
class Narration:
    """重写后的中文旁白。"""

    source: str
    stages: list[StageLine]
    method: str  # "llm" | "fallback"
    style: str = "1A"
    warnings: list[str] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        return "".join(s.text for s in self.stages)

    @property
    def char_count(self) -> int:
        return len(self.full_text)

    def est_seconds(self, cps: float = CPS) -> float:
        return round(self.char_count / cps, 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "style": self.style,
            "stages": [s.to_dict() for s in self.stages],
            "full_text": self.full_text,
            "char_count": self.char_count,
            "est_seconds": self.est_seconds(),
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# 数字/引语/人名 提取
# ---------------------------------------------------------------------------

_CN_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000}


def _cn_to_int(token: str) -> int | None:
    """解析中文数字串(支持到亿, 不支持小数)。失败返回 None。"""
    if not token:
        return None
    total, section, number = 0, 0, 0
    for ch in token:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            if unit >= 10000:
                section = (section + number) * unit
                total += section
                section = number = 0
            else:
                section += (number or 1) * unit
                number = 0
        else:
            return None
    return total + section + number


def extract_numbers(text: str) -> set[float]:
    """文本里的全部数值(阿拉伯 + 中文), 归一为 float 集合。

    中文单字数字只在"是数级(十百千万亿)"或"后面跟量词"时才算数值,
    避免把"一样/一定/一起"这类成语误报成数字。
    """
    out: set[float] = set()
    for m in _ARABIC_RE.finditer(text):
        try:
            out.add(float(m.group()))
        except ValueError:  # pragma: no cover - regex 保证可解析
            pass
    for m in _CN_NUM_RE.finditer(text):
        token = m.group()
        nxt = text[m.end()] if m.end() < len(text) else ""
        is_number = len(token) >= 2 or bool(set(token) & _CN_UNIT_CHARS) or nxt in _MEASURE
        if not is_number:
            continue
        v = _cn_to_int(token)
        if v is not None:
            out.add(float(v))
    return out


def extract_quotes(text: str) -> set[str]:
    """文本里的引语内容(去空白)。"""
    return {m.group(1).strip() for m in _QUOTE_RE.finditer(text) if m.group(1).strip()}


def extract_names(text: str) -> set[str]:
    """潜在人名/专名: 拉丁词 + 中文"姓+名"启发式。"""
    names: set[str] = set()
    for m in _LATIN_RE.finditer(text):
        tok = m.group()
        if tok.lower() not in _LATIN_STOP:
            names.add(tok)
    for i in range(len(text) - 1):
        if text[i] in _SURNAMES and "一" <= text[i + 1] <= "鿿":
            # 取 2–3 字姓名
            cand = text[i : i + 2]
            if (
                i + 2 < len(text)
                and "一" <= text[i + 2] <= "鿿"
                and text[i + 2] not in "的了是在和与也就都还"
            ):
                cand3 = text[i : i + 3]
                if cand3 not in text[:i] + text[i + 3 :]:  # 避免"在这/都是"这类
                    names.add(cand3)
                else:
                    names.add(cand)
            else:
                names.add(cand)
    return names


# ---------------------------------------------------------------------------
# 无编造校验
# ---------------------------------------------------------------------------


def verify_no_fabrication(source: str, narration_text: str) -> list[str]:
    """返回旁白里"原文没有"的数字/引语/人名(空列表 = 通过)。

    数字按数值比较(阿拉伯与中文互通);引语按内容子串;人名按出现。
    """
    violations: list[str] = []
    src_nums = extract_numbers(source)
    for v in sorted(extract_numbers(narration_text) - src_nums):
        violations.append(f"number:{v:g}")
    for q in sorted(extract_quotes(narration_text)):
        if q not in source:
            violations.append(f"quote:{q}")
    for n in sorted(extract_names(narration_text)):
        if n not in source:
            violations.append(f"name:{n}")
    return violations


# ---------------------------------------------------------------------------
# 切句 / 字数
# ---------------------------------------------------------------------------


def split_sentences(text: str) -> list[str]:
    """按中文标点切句, 去空、保留标点。"""
    parts = [p.strip() for p in _SENT_SPLIT.split(text) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def target_chars(duration: int, cps: float = CPS) -> tuple[int, int]:
    """目标时长对应的字数区间(4–5 字/秒)。"""
    return int(duration * 4.0), int(duration * 5.0)


# ---------------------------------------------------------------------------
# 确定性 fallback 重写
# ---------------------------------------------------------------------------


def _arc_for(style: str) -> tuple[str, ...]:
    return whitelist.ARC_STAGES_STYLE3 if style == "3" else whitelist.ARC_STAGES


def fallback_rewrite(copy: str, duration: int, style: str) -> Narration:
    """确定性重写: 把原文句子按叙事弧重新编排, 不新增任何事实。

    不编造 —— 只重排、裁剪原文句子;裁剪以字数预算为准。
    """
    arc = _arc_for(style)
    sentences = split_sentences(copy)
    if not sentences:
        sentences = [copy.strip()]
    n = len(arc)
    # 按弧长切分句子(尽量均分, 至少每段一句)
    buckets: list[list[str]] = [[] for _ in range(n)]
    for i, s in enumerate(sentences):
        buckets[min(i * n // max(len(sentences), 1), n - 1)].append(s)
    # 空桶从相邻桶借一句(仍只用原文)
    for i, b in enumerate(buckets):
        if not b:
            for j in (i - 1, i + 1):
                if 0 <= j < n and len(buckets[j]) > 1:
                    buckets[i].append(buckets[j].pop())
                    break
    stages = [StageLine(stage=arc[i], text="".join(buckets[i])) for i in range(n) if buckets[i]]
    narration = Narration(source=copy, stages=stages, method="fallback", style=style)
    return trim_to_budget(narration, duration)


def trim_to_budget(nar: Narration, duration: int, cps: float = CPS) -> Narration:
    """把旁白裁到目标时长字数上限内(只删原文句, 不新增)。

    每个阶段至少保留第一句;从后往前丢弃多余句子直到 <= hi。
    """
    lo, hi = target_chars(duration, cps)
    if nar.char_count <= hi:
        if nar.char_count < lo:
            nar.warnings.append(
                f"narration {nar.char_count} chars below {lo} (target {lo}-{hi}); source may be short"
            )
        return nar
    per_stage: list[list[str]] = [split_sentences(s.text) or [s.text] for s in nar.stages]
    kept: list[list[str]] = [[sents[0]] for sents in per_stage]
    extra: list[tuple[int, str]] = []
    for i, sents in enumerate(per_stage):
        for s in sents[1:]:
            extra.append((i, s))
    dropped = 0
    while extra and sum(len("".join(k)) for k in kept) > hi:
        extra.pop()  # 从最后一句起丢弃
        dropped += 1
    for i, s in extra:
        kept[i].append(s)
    stages = [
        StageLine(stage=nar.stages[i].stage, text="".join(kept[i])) for i in range(len(nar.stages))
    ]
    trimmed = Narration(source=nar.source, stages=stages, method=nar.method, style=nar.style)
    trimmed.warnings.extend(nar.warnings)
    if dropped:
        trimmed.warnings.append(
            f"trimmed {dropped} sentence(s) to fit {hi} chars (target {lo}-{hi})"
        )
    return trimmed


# ---------------------------------------------------------------------------
# LLM 重写
# ---------------------------------------------------------------------------

_PROMPT = """你是一名中文短视频导演。把下面的原始文案重写成一段中文口播旁白。

硬性要求:
1. 结构严格按这 {n} 个阶段: {stages}。每个阶段给一句话。
2. 绝对不许编造原文没有的数字、人名、引语、研究结论或产品数据;只能复述、改写原文已有的内容。
3. 全片旁白总字数控制在 {lo}–{hi} 字之间(中文口播约 4-5 字/秒, 目标 {dur} 秒)。
4. 口语化、有钩子、不空洞;不要出现"本期视频""点赞关注"这类套话。

原始文案:
\"\"\"{copy}\"\"\"

只输出 JSON, 形如:
{{"stages": [{{"stage": "{first}", "text": "..."}}, ...]}}
阶段键必须依次是: {stages}。不要输出任何解释。"""


def llm_rewrite(
    copy: str,
    duration: int,
    style: str,
    *,
    complete: Callable[[str], str],
) -> Narration:
    """用 LLM 重写;失败抛异常由调用方回退。"""
    arc = _arc_for(style)
    lo, hi = target_chars(duration)
    prompt = _PROMPT.format(
        n=len(arc),
        stages="/".join(arc),
        lo=lo,
        hi=hi,
        dur=duration,
        first=arc[0],
        copy=copy,
    )
    raw = complete(prompt)
    data = _extract_json(raw)
    stages_raw = data.get("stages")
    if not isinstance(stages_raw, list) or not stages_raw:
        raise ValueError("llm output has no stages list")
    stages: list[StageLine] = []
    for i, item in enumerate(stages_raw):
        if not isinstance(item, dict):
            raise ValueError("stage item not an object")
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        stage = str(item.get("stage") or (arc[i] if i < len(arc) else arc[-1]))
        if stage not in arc:
            stage = arc[i] if i < len(arc) else arc[-1]
        stages.append(StageLine(stage=stage, text=text))
    if not stages:
        raise ValueError("llm produced no non-empty stages")
    return Narration(source=copy, stages=stages, method="llm", style=style)


def _extract_json(raw: str) -> dict[str, Any]:
    """从 LLM 回复里抠出第一个 JSON 对象。"""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise ValueError("no JSON object in llm output")
    return json.loads(raw[start : end + 1])


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------


def rewrite(
    copy: str,
    duration: int,
    style: str,
    *,
    complete: Callable[[str], str] | None = None,
    cps: float = CPS,
) -> Narration:
    """重写旁白: 优先 LLM, 失败/越界/编造则回退确定性方案。

    两条路径都过 :func:`verify_no_fabrication`;LLM 结果若有编造则弃用回退。
    """
    if complete is not None:
        try:
            nar = llm_rewrite(copy, duration, style, complete=complete)
            viol = verify_no_fabrication(copy, nar.full_text)
            lo, hi = target_chars(duration, cps)
            if viol:
                logger.warning("llm narration fabricated facts %s; falling back", viol)
            elif not (lo * 0.6 <= nar.char_count <= hi * 1.3):
                logger.warning(
                    "llm narration %d chars outside %d-%d window; falling back",
                    nar.char_count,
                    lo,
                    hi,
                )
            else:
                return trim_to_budget(nar, duration, cps)
        except Exception as exc:  # noqa: BLE001 - 任何 LLM 失败都回退
            logger.warning("llm rewrite failed (%s); falling back", exc)
    nar = fallback_rewrite(copy, duration, style)
    viol = verify_no_fabrication(copy, nar.full_text)
    nar.warnings.extend(viol)
    return nar


__all__ = [
    "CPS",
    "Narration",
    "StageLine",
    "extract_names",
    "extract_numbers",
    "extract_quotes",
    "fallback_rewrite",
    "llm_rewrite",
    "rewrite",
    "split_sentences",
    "target_chars",
    "trim_to_budget",
    "verify_no_fabrication",
]
