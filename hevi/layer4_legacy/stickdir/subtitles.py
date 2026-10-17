"""字幕切分与 SRT —— 标点 + 词边界, 不拆词不断行。

无外部依赖(无 jieba/pkuseg 环境):用确定性分词器 —— 标点切句 + 词典最长匹配
+ 单字兜底。英文按空白切词, **绝不把单词拆到两行或两条**。

测试(``tests/stickdir/test_subtitles.py``)把每条字幕拼回, 与分词结果比对,
断言没有任何 token 被拆开。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: 中文标点(切句用;保留在 token 尾部)
_PUNCT = "。！？；，、：!?;,:…—～"

#: 英文 token
_LATIN = re.compile(r"[A-Za-z0-9]+(?:['\-][A-Za-z0-9]+)*")

#: 常用词词典(确定性最长匹配;覆盖高频双/三/四字词, 兜底单字)
_LEXICON: frozenset[str] = frozenset(
    """
    效率 选择 时间 决策 成本 大脑 顶尖 事情 重要 事情 方法 目标 结果 过程 系统 机制
    逻辑 认知 注意 习惯 环境 信息 价值 增长 复利 长期 短期 风险 收益 机会 代价 取舍
    专注 焦虑 拖延 行动 反馈 迭代 复盘 结构 框架 模型 思维 视角 边界 资源 精力
    很多人 其实 真正 来自 努力 更少 更多 时候 因为 所以 但是 如果 就是 不是 而是
    每一个 一步 重新 评估 吃掉 全部 不是 而是 直接 删掉 胜过 完成 别再 先问
    到底 该不该 这件事 当 选项 变多 会 把 不 重要 的 事 直接 删除
    我们 他们 你们 自己 别人 大家 有人 有些 所有 任何 每个 这个 那个 这些 那些
    可以 应该 必须 需要 能够 想要 开始 结束 坚持 放弃 改变 提升 降低 增加 减少
    问题 答案 原因 方法 办法 步骤 阶段 层次 维度 角度 方向 路径 选择 决定
    """.split()
)


def tokenize(text: str) -> list[str]:
    """把文本切成 token:标点独立成 token, 英文按词, 中文按词典最长匹配。"""
    tokens: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch in _PUNCT:
            tokens.append(ch)
            i += 1
            continue
        m = _LATIN.match(text, i)
        if m:
            tokens.append(m.group())
            i = m.end()
            continue
        # 中文最长匹配(≤4 字)
        matched = None
        for length in (4, 3, 2):
            if i + length <= n:
                cand = text[i : i + length]
                if all("一" <= c <= "鿿" for c in cand) and cand in _LEXICON:
                    matched = cand
                    break
        if matched:
            tokens.append(matched)
            i += len(matched)
        else:
            tokens.append(ch)
            i += 1
    return tokens


def _is_word(tok: str) -> bool:
    return tok not in _PUNCT


@dataclass
class Cue:
    start: float
    end: float
    text: str

    def to_dict(self) -> dict[str, object]:
        return {"start": round(self.start, 3), "end": round(self.end, 3), "text": self.text}


def split_cues(text: str, start: float, end: float, *, max_chars: int = 14) -> list[Cue]:
    """把一段旁白按词边界切成若干字幕条, 时间在 [start, end] 内按字数分配。

    * 不在 token 内部断开(不拆词);
    * 优先在标点处断行;
    * 英文 token 整体保留(不拆词)。
    """
    tokens = tokenize(text)
    if not tokens:
        return []
    # 贪心装行:遇到标点或超长则断行
    lines: list[list[str]] = []
    cur: list[str] = []
    cur_len = 0
    for tok in tokens:
        tok_len = len(tok)
        if cur and (cur_len + tok_len > max_chars or (cur and cur[-1] in _PUNCT and _is_word(tok))):
            lines.append(cur)
            cur, cur_len = [], 0
        cur.append(tok)
        cur_len += tok_len
        if tok in _PUNCT:
            lines.append(cur)
            cur, cur_len = [], 0
    if cur:
        lines.append(cur)

    # 合并"只有标点"的孤儿行到前一行(避免"。"独占一条)
    merged: list[list[str]] = []
    for ln in lines:
        if merged and all(not _is_word(t) for t in ln):
            merged[-1].extend(ln)
        else:
            merged.append(ln)

    texts = ["".join(ln).strip() for ln in merged]
    texts = [t for t in texts if t]
    if not texts:
        return []
    total = max(end - start, 0.001)
    weights = [max(len(t), 1) for t in texts]
    wsum = sum(weights)
    cues: list[Cue] = []
    t = start
    for txt, w in zip(texts, weights):
        d = total * w / wsum
        cues.append(Cue(start=round(t, 3), end=round(t + d, 3), text=txt))
        t += d
    if cues:
        cues[-1].end = round(end, 3)
    return cues


def _ts(sec: float) -> str:
    sec = max(sec, 0.0)
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    out: list[str] = []
    for i, c in enumerate(cues, 1):
        out.append(str(i))
        out.append(f"{_ts(c.start)} --> {_ts(c.end)}")
        out.append(c.text)
        out.append("")
    return "\n".join(out)


def cue_tokens(cue: Cue) -> list[str]:
    """一条字幕的 token(测试用:拼回后与原文分词一致, 无拆词)。"""
    return tokenize(cue.text)


def _ass_ts(sec: float) -> str:
    sec = max(sec, 0.0)
    cs = int(round(sec * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def to_ass(
    cues: list[Cue],
    width: int,
    height: int,
    *,
    font_size: int | None = None,
    margin_v: int | None = None,
) -> str:
    """生成 ASS(显式 PlayRes = 画面尺寸, 字幕不越界)。

    直接给 ffmpeg 用, 避免 ``subtitles`` 滤镜默认 PlayRes=288 导致的巨大字号。
    """
    fs = font_size or max(20, int(height * 0.038))
    mv = margin_v or max(30, int(height * 0.055))
    side = max(20, int(width * 0.06))
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {width}\n"
        f"PlayResY: {height}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Noto Sans CJK SC,{fs},&H00FFFFFF,&H000000FF,&H00101010,&H00000000,"
        f"0,0,0,0,100,100,0,0,1,{max(2, fs // 14)},1,2,{side},{side},{mv},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    rows = []
    for c in cues:
        text = c.text.replace("\n", "\\N")
        rows.append(f"Dialogue: 0,{_ass_ts(c.start)},{_ass_ts(c.end)},Default,,0,0,0,,{text}")
    return header + "\n".join(rows) + "\n"


__all__ = ["Cue", "cue_tokens", "split_cues", "to_ass", "to_srt", "tokenize"]
