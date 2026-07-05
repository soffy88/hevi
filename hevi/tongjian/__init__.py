"""hevi.tongjian —— 通鉴全自动流水线(设计 §docs/specs/导演台/HEVI-SPEC-01)。

与 hevi/director/(通用"一句话主题→视频"管线)是完全不同的产品方向,只是撞了同一个
中文名"导演台"——这里是"资治通鉴原文 → 历史解说/叙事视频"的垂直编译器式流水线,
命名空间独立以免混淆。

L0 史料预处理 → L1 立意 → L2 剧本 → ...(后续层逐步建)。每层出口有校验门(G0/G1/...),
门失败 → 重试/降级,流水线永不卡死。
"""

from hevi.tongjian.chapter_ir import extract_chapter_ir
from hevi.tongjian.character_bible import gate_character_bible, generate_character_bible
from hevi.tongjian.constitution import build_constitution, gate_constitution, generate_constitution
from hevi.tongjian.gates import gate_chapter_ir
from hevi.tongjian.schemas import (
    Act,
    CharacterBible,
    CharacterBibleEntry,
    CharacterIR,
    ChapterIR,
    Constitution,
    EventIR,
    GateResult,
    LocationHint,
    QuoteIR,
    Script,
    ScriptLine,
    VisualStyle,
)
from hevi.tongjian.script import build_script, gate_script, generate_script

__all__ = [
    "Act",
    "CharacterBible",
    "CharacterBibleEntry",
    "CharacterIR",
    "ChapterIR",
    "Constitution",
    "EventIR",
    "GateResult",
    "LocationHint",
    "QuoteIR",
    "Script",
    "ScriptLine",
    "VisualStyle",
    "build_constitution",
    "build_script",
    "extract_chapter_ir",
    "gate_chapter_ir",
    "gate_character_bible",
    "gate_constitution",
    "gate_script",
    "generate_character_bible",
    "generate_constitution",
    "generate_script",
]
