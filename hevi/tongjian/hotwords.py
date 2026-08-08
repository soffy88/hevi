"""v9.1 ASR 热词生成 —— 从通鉴 IR 提取专名, 喂给 VibeVoice-ASR 提升识别。

faster-whisper/openai-whisper 对古人名/官职/地名常识别错(如"智伯"→"智波"),
是通鉴 L2 门禁"剧本行未引用事件角色"的部分根因。VibeVoice-ASR 支持
Customized Hotwords —— 把角色名/别名/地点名自动生成热词列表, 识别准确率
大幅提升。

提取来源(只取 IR 内权威事实, 不引入外部):
  * 角色 canonical_name + aliases;
  * 地点名;
  * 引语中高频出现的 2-4 字专名(保守: 仅角色名/地点名, 避免噪声)。
"""

from __future__ import annotations

import re

from hevi.tongjian.schemas import ChapterIR


def build_asr_hotwords(chapter_ir: ChapterIR, *, max_words: int = 30) -> list[str]:
    """生成 ASR 热词: 角色名/别名/地点名, 按出现次数去重排序。"""
    hotwords: list[str] = []
    seen: set[str] = set()
    # 角色名 + 别名(权重最高)。
    for c in chapter_ir.characters:
        for name in (c.canonical_name, *c.aliases):
            clean = _normalise(name)
            if clean and clean not in seen:
                seen.add(clean)
                hotwords.append(clean)
    # 地点名。
    for loc in chapter_ir.locations:
        clean = _normalise(loc.name)
        if clean and clean not in seen:
            seen.add(clean)
            hotwords.append(clean)
    # 事件摘要里的专名(2-4 字连续汉字, 且出现在引语/角色别名中才收录——保守)。
    quote_text = "".join(q.original for q in chapter_ir.quotes)
    for e in chapter_ir.events:
        for token in re.findall(r"[\u4e00-\u9fff]{2,4}", e.summary):
            if token in quote_text and token not in seen:
                seen.add(token)
                hotwords.append(token)
    return hotwords[:max_words]


def _normalise(name: str) -> str:
    return name.strip().strip("，。、；： \t")


def hotwords_prompt(hotwords: list[str], *, max_words: int = 30) -> str:
    """热词列表 → 逗号分隔的 prompt 块(喂给 ASR 端点/whisper initial_prompt)。"""
    return "、".join(hotwords[:max_words])


__all__ = ["build_asr_hotwords", "hotwords_prompt"]
