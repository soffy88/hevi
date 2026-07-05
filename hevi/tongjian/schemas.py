"""L0 输出契约 chapter_ir —— 见 HEVI-SPEC-01 §1.2。pydantic 模型天然给 G0 的
"结构校验: JSON Schema 强校验"那一条,不用另写校验器。

source_span 是 [start, end) 字符下标,指向 meta 之外传入的原文(raw_text)。这些下标
**由代码算,不由 LLM 报**——LLM 抽"确切引文原句",代码用确定性字符串查找定位下标,
避免 LLM 数字符的老毛病(小模型对着长文本数下标几乎必错)。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CharacterIR(BaseModel):
    character_id: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    role_in_chapter: str = ""  # protagonist/antagonist/supporting/anonymous...
    faction: str | None = None
    fate: str | None = None
    source_spans: list[tuple[int, int]] = Field(default_factory=list)


class EventIR(BaseModel):
    event_id: str
    summary: str
    actors: list[str] = Field(default_factory=list)  # character_id 列表
    location: str | None = None
    year: int | None = None  # 公元纪年,负数=公元前
    causes: list[str] = Field(default_factory=list)  # event_id 列表
    effects: list[str] = Field(default_factory=list)  # event_id 列表
    dramatic_weight: int = 3  # 1-5,戏剧性权重,决定该事件是否必入某一幕(G1 用)
    source_span: tuple[int, int] = (0, 0)


class QuoteIR(BaseModel):
    quote_id: str
    speaker: str  # character_id
    original: str  # 原文引语(未经改写,dialogue 只准改写自这里 —— 全流水线的史实红线)
    modern: str = ""  # 白话译文(供 L2 剧本改写参考)
    event_id: str | None = None
    emotion: str = ""


class LocationHint(BaseModel):
    scene_hint_id: str
    name: str
    type: str = ""  # 城池/宫殿/战场...
    events: list[str] = Field(default_factory=list)  # event_id 列表


class ChapterMeta(BaseModel):
    source: str  # 如"资治通鉴·周纪一"
    year_range: tuple[int, int] | None = None
    char_count: int = 0


class ChapterIR(BaseModel):
    meta: ChapterMeta
    characters: list[CharacterIR] = Field(default_factory=list)
    events: list[EventIR] = Field(default_factory=list)
    quotes: list[QuoteIR] = Field(default_factory=list)
    locations: list[LocationHint] = Field(default_factory=list)


class GateResult(BaseModel):
    """各层校验门(G0/G1/...)的统一返回形状。"""

    passed: bool
    coverage: float = 1.0
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ── L1 立意(constitution.json)—— HEVI-SPEC-01 §2.1 ──────────────────────


class VisualStyle(BaseModel):
    art_direction: str = ""
    palette: list[str] = Field(default_factory=list)
    aspect_ratio: str = "16:9"
    negative_style: list[str] = Field(default_factory=list)


class Act(BaseModel):
    act: int
    title: str = ""
    events: list[str] = Field(default_factory=list)  # event_id 列表,引用 chapter_ir.events
    emotion_curve: str = ""


class Constitution(BaseModel):
    thesis: str = ""
    logline: str = ""
    narrative_stance: str = ""
    tone: list[str] = Field(default_factory=list)
    visual_style: VisualStyle = Field(default_factory=VisualStyle)
    act_structure: list[Act] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    target_duration_sec: int = 180
    bgm_mood_arc: list[str] = Field(default_factory=list)


# ── L2 剧本(script.json)—— HEVI-SPEC-01 §3.2 ─────────────────────────────


class ScriptLine(BaseModel):
    line_id: str
    act: int = 1
    type: str = "narration"  # narration/dialogue/commentary
    speaker: str = "NARRATOR"
    text: str = ""
    event_id: str | None = None
    quote_id: str | None = None  # 仅 dialogue 行:必须引用 chapter_ir.quotes 里真实存在的 quote_id
    emotion: str = ""
    visual_hint: str = ""


class Script(BaseModel):
    lines: list[ScriptLine] = Field(default_factory=list)


# ── L5 角色卡(character_bible.json)—— HEVI-SPEC-01 §5.2 ─────────────────
#
# 本次只实现步骤 2(LLM 依据 chapter_ir + 宪法生成外形描述,纯文本)。步骤 3-4
# (文生图产出候选立绘 + VLM 年代审 → 锁定 ref_image/gen_lock)需要本地 GPU 图像
# 生成能力,当前环境 GPU 不可用(nvidia-smi/torch.cuda 均报错),先留空等环境恢复。
# voice_id 同理待 L3 TTS 声音库接入后再填。


class CharacterBibleEntry(BaseModel):
    character_id: str
    name: str
    appearance: str = ""
    era_check: str = ""
    ref_image: str | None = None  # 待图像生成阶段(GPU 恢复后)接入
    gen_lock: dict | None = None  # {"seed":..., "ip_adapter_weight":...}
    voice_id: str | None = None  # 待 L3 TTS 接入后填入


class CharacterBible(BaseModel):
    characters: list[CharacterBibleEntry] = Field(default_factory=list)
