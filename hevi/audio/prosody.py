"""prosody —— 配音前置韵律规划层(3O oskill 风格, 差距 B3)。

对标 agent-video-pipeline 的 `analyze_prosody`(先产 prosody.json 再配音), 补 hevi
差距: 此前 subtitle_align 只有对齐, 无韵律规划层; TTS 重音/停顿/语速全靠提示词。

设计(纯函数 + 显式数据, 无外部依赖):
  - `ProsodyUnit`: 单句韵律单元 {text, pause_ms(句后停顿), speed(语速档),
    emphasis(重音词表), tone(情绪倾向)}
  - `analyze_prosody(text, lang) -> ProsodyPlan`: 确定性启发式拆分
      * 句切分: 按 。！？；… 与换行(中文); .!?; 换行(拉丁)
      * 停顿分级: 句号 600ms / 问号感叹 500ms / 分号 350ms / 逗号 200ms
      * 重音: 引号词、强调词表(中文: 必须/绝对/最/非常; 拉丁: MUST/NEVER/always…)
      * 语速: 长句 > 28 字降速 0.9; 短句 < 8 字 1.05
  - `plan_to_cues(plan, base_rate) -> list[dict]`: 输出下游配音 cue(TTS 消费)
  - `merge_with_srt(plan, segments)`: 韵律单元与已有字幕段合并(供对齐校验)

将来回迁 oskill: 本模块无 hevi 依赖, 可整体搬移; LLM 增强版(重音语义判断)留注入点。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 句末标点 → 句后停顿(ms)。数值为经验基准, 与 AVP 量级一致(0.2-0.6s)。
_PAUSE_AFTER = {
    "。": 600,
    "！": 500,
    "？": 500,
    "…": 400,
    "；": 350,
    "，": 200,
}
_SENTENCE_BREAK = re.compile(r"[。！？…；\n]|[.!?;]")
_COMMA_BREAK = re.compile(r"[，,]")
_EMPHASIS_WORDS_ZH = ("必须", "绝对", "最", "非常", "极其", "绝不能", "务必")
_EMPHASIS_WORDS_EN = ("must", "never", "always", "absolutely", "extremely", "crucial")
_QUOTE_RE = re.compile(r"[“\"「『]([^”\"」』]{1,12})[”\"」』]")


@dataclass(frozen=True)
class ProsodyUnit:
    text: str
    pause_ms: int = 200  # 句后停顿
    speed: float = 1.0  # 语速倍率
    emphasis: tuple[str, ...] = ()  # 重音词
    tone: str = "neutral"  # 情绪倾向提示(neutral/happy/urgent/serious)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "pause_ms": self.pause_ms,
            "speed": round(self.speed, 3),
            "emphasis": list(self.emphasis),
            "tone": self.tone,
        }


@dataclass
class ProsodyPlan:
    lang: str
    units: list[ProsodyUnit] = field(default_factory=list)
    base_speed: float = 1.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "lang": self.lang,
            "base_speed": self.base_speed,
            "units": [u.to_dict() for u in self.units],
            "notes": self.notes,
        }


def _tone_hint(text: str) -> str:
    if any(c in text for c in "！?？"):
        return "urgent" if any(c in text for c in "！!") else "serious"
    if "。" not in text and len(text) < 14:
        return "happy"
    return "neutral"


def _split_sentences(text: str) -> list[str]:
    """按句末标点切句, 保留标点(逗号不切)。空段剔除。"""
    parts = _SENTENCE_BREAK.split(text)
    # 切分会丢标点; 这里用 finditer 保留边界。改为扫描式切分:
    out: list[str] = []
    start = 0
    for m in _SENTENCE_BREAK.finditer(text):
        seg = text[start : m.end()].strip()
        if seg:
            out.append(seg)
        start = m.end()
    tail = text[start:].strip()
    if tail:
        out.append(tail)
    return out


def _pause_for(sentence: str) -> int:
    for ch in reversed(sentence):
        if ch in _PAUSE_AFTER:
            return _PAUSE_AFTER[ch]
    return 200


def _emphases(sentence: str, lang: str) -> list[str]:
    found: list[str] = []
    if lang == "zh":
        words = _EMPHASIS_WORDS_ZH
        low = sentence
    else:
        words = _EMPHASIS_WORDS_EN
        low = sentence.lower()
    for w in words:
        if w in low:
            found.append(w)
    for m in _QUOTE_RE.finditer(sentence):
        found.append(m.group(1))
    return found


def _speed_for(sentence: str) -> float:
    n = len(re.sub(r"\s", "", sentence))
    if n > 28:
        return 0.9
    if n < 8:
        return 1.05
    return 1.0


def analyze_prosody(text: str, *, lang: str = "zh", base_speed: float = 1.0) -> ProsodyPlan:
    """确定性韵律分析: 分句 + 停顿 + 重音 + 语速 + 情绪提示。"""
    plan = ProsodyPlan(lang=lang, base_speed=base_speed)
    cleaned = text.strip()
    if not cleaned:
        return plan
    # 先把段间空行降级为分号级停顿(保持句内连贯)
    cleaned = re.sub(r"\n\s*\n", "；", cleaned)
    for sent in _split_sentences(cleaned):
        if not sent.strip():
            continue
        if sent.strip() in "。！？…；，.!?;,":
            continue  # 纯标点段(如空行降级产生的独立“；”)剔除
        emph = _emphases(sent, lang)
        plan.units.append(
            ProsodyUnit(
                text=sent,
                pause_ms=_pause_for(sent),
                speed=round(_speed_for(sent) * base_speed, 3),
                emphasis=tuple(emph),
                tone=_tone_hint(sent),
            )
        )
    return plan


def plan_to_cues(plan: ProsodyPlan) -> list[dict]:
    """韵律计划 → 下游 TTS 配音 cue 列表(供 audio 服务消费)。"""
    return [u.to_dict() for u in plan.units]


def merge_with_srt(plan: ProsodyPlan, segments: list[dict]) -> list[dict]:
    """韵律单元与已有字幕段(含 start/end)合并, 供对齐校验。

    segments: [{"text", "start", "end"}]。按文本顺序贪心配对: 字幕段文本包含
    单元文本的首/尾字即配对; 未配对段保持原样(notes 说明)。
    返回合并列表(每项 = 字幕段 + 韵律字段)。
    """
    merged: list[dict] = []
    segs = list(segments)
    units = list(plan.units)
    si = ui = 0
    while si < len(segs) and ui < len(units):
        seg_text = segs[si].get("text", "")
        unit_text = units[ui].text
        head = unit_text[:2]
        tail = unit_text[-2:]
        if head and (seg_text.startswith(head) or seg_text.endswith(tail) or head in seg_text):
            merged.append({**segs[si], **units[ui].to_dict(), "prosody_matched": True})
            ui += 1
        else:
            merged.append({**segs[si], "prosody_matched": False})
        si += 1
    while si < len(segs):
        merged.append({**segs[si], "prosody_matched": False})
        si += 1
    return merged


__all__ = ["ProsodyPlan", "ProsodyUnit", "analyze_prosody", "merge_with_srt", "plan_to_cues"]
