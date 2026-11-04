"""ASR 词流 → 断句 → 翻译 → SRT/ASS（思路：VideoCaptioner 的断句/合成、VideoLingo 的语义断句与术语表）。

纯函数；翻译通过注入的 llm(prompt)->str 调用，便于单测与切换本地模型。
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

_END = set("。！？!?.;；…")
_SOFT = set("，,、：:")


def _is_cjk(s: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]", s))


def segment_sentences(
    words: list[dict],
    *,
    max_chars: int = 0,
    max_dur: float = 6.0,
    gap_split: float = 0.6,
    min_dur: float = 0.6,
) -> list[dict]:
    """按句末标点、停顿间隙、长度上限切句；软标点在过长时优先作为切点。

    max_chars=0 时自动：CJK 22 字，拉丁 42 字符。
    """
    if not words:
        return []
    cjk = _is_cjk("".join(w["word"] for w in words))
    lim = max_chars or (22 if cjk else 42)
    cues, cur = [], []

    def text(ws):
        t = "".join(w["word"] for w in ws)
        return t.strip() if not cjk else t.replace(" ", "").strip()

    def flush():
        if cur:
            cues.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": text(cur)})
            cur.clear()

    for i, w in enumerate(words):
        if cur and w["start"] - cur[-1]["end"] >= gap_split:
            flush()
        cur.append(w)
        tok = w["word"].strip()
        last = tok[-1:] if tok else ""
        n = len(text(cur))
        d = cur[-1]["end"] - cur[0]["start"]
        if last in _END or (last in _SOFT and n >= lim * 0.6) or n >= lim or d >= max_dur:
            flush()
    flush()
    # 合并过短的碎句到前一句（若合并后不超限）
    merged: list[dict] = []
    for c in cues:
        if (
            merged
            and c["end"] - c["start"] < min_dur
            and len(merged[-1]["text"]) + len(c["text"]) <= lim * 1.3
            and c["start"] - merged[-1]["end"] < gap_split
        ):
            sep = "" if cjk else " "
            merged[-1] = {
                "start": merged[-1]["start"],
                "end": c["end"],
                "text": merged[-1]["text"] + sep + c["text"],
            }
        else:
            merged.append(dict(c))
    for i, c in enumerate(merged):
        c["id"] = i + 1
        c["start"], c["end"] = round(c["start"], 3), round(c["end"], 3)
    return merged


_LANG = {"zh": "Simplified Chinese", "en": "English", "ja": "Japanese", "ko": "Korean"}


def _prompt(lines: list[str], src: str, tgt: str, glossary: dict | None, context: str) -> str:
    g = ""
    if glossary:
        g = (
            "Glossary (always use these translations):\n"
            + "\n".join(f"- {k} => {v}" for k, v in glossary.items())
            + "\n"
        )
    numbered = "\n".join(f"{i + 1}. {l}" for i, l in enumerate(lines))
    return (
        f"You are a professional subtitle translator. Translate each numbered {_LANG.get(src, src)} subtitle line "
        f"into {_LANG.get(tgt, tgt)}. Keep it concise and natural for subtitles, keep the numbering, one output per input, "
        f"no explanations.\n{g}{('Context: ' + context + chr(10)) if context else ''}"
        f'Return JSON: {{"t": ["line1", "line2", ...]}} with exactly {len(lines)} items.\n\n{numbered}'
    )


def _parse(resp: str, n: int) -> list[str] | None:
    try:
        m = re.search(r"\{.*\}", resp, re.S)
        arr = json.loads(m.group(0))["t"] if m else None
        if isinstance(arr, list) and len(arr) == n:
            return [re.sub(r"^\s*\d+[.、)]\s*", "", str(x)).strip() for x in arr]
    except Exception:
        return None
    return None


def translate_cues(
    cues: list[dict],
    llm: Callable[[str], str],
    *,
    src: str,
    tgt: str,
    glossary: dict | None = None,
    batch: int = 8,
    context: str = "",
) -> list[dict]:
    """批量翻译（带上一批末句作上下文），批失败则逐句兜底；结果写入 cue['tr']。"""
    out = [dict(c) for c in cues]
    for b in range(0, len(out), batch):
        chunk = out[b : b + batch]
        ctx = context or (" / ".join(c["text"] for c in out[max(0, b - 2) : b]))
        res = _parse(llm(_prompt([c["text"] for c in chunk], src, tgt, glossary, ctx)), len(chunk))
        if res is None:
            res = []
            for c in chunk:
                r = _parse(llm(_prompt([c["text"]], src, tgt, glossary, ctx)), 1)
                res.append(r[0] if r else "")
        for c, t in zip(chunk, res):
            c["tr"] = t
            if glossary:  # 术语强制统一（VideoLingo 思路）：模型漏用时做确定性替换
                for k, v in glossary.items():
                    c["tr"] = c["tr"].replace(k, v)
    return out


def _ts(t: float, sep: str = ",", cs: bool = False) -> str:
    unit = 100 if cs else 1000
    n = int(round(max(0.0, t) * unit))
    frac = n % unit
    secs = n // unit
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    if cs:
        return f"{h}:{m:02d}:{s:02d}.{frac:02d}"
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{frac:03d}"


def to_srt(cues: list[dict], mode: str = "bilingual") -> str:
    """mode: src | tr | bilingual（原文在上，译文在下）。"""
    blocks = []
    for i, c in enumerate(cues, 1):
        lines = {
            "src": [c["text"]],
            "tr": [c.get("tr", "")],
            "bilingual": [c["text"], c.get("tr", "")],
        }[mode]
        blocks.append(
            f"{i}\n{_ts(c['start'])} --> {_ts(c['end'])}\n" + "\n".join(l for l in lines if l)
        )
    return "\n\n".join(blocks) + "\n"


def to_ass(
    cues: list[dict],
    *,
    width: int = 1920,
    height: int = 1080,
    font: str = "Noto Sans CJK SC",
    tr_on_top: bool = False,
) -> str:
    """双语 ASS：两个样式（Src 大字 / Tr 小字），各自一条 Dialogue，便于播放器与烧录。"""
    fs = round(height * 0.052)
    fs2 = round(height * 0.040)
    mv = round(height * 0.05)
    head = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Src,{font},{fs},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,3,1,2,40,40,{mv + (0 if tr_on_top else fs2 + 12)},1\n"
        f"Style: Tr,{font},{fs2},&H0000E5FF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,1,2,40,40,{mv + (fs + 12 if tr_on_top else 0)},1\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")

    ev = []
    for c in cues:
        a, b = _ts(c["start"], cs=True), _ts(c["end"], cs=True)
        ev.append(f"Dialogue: 0,{a},{b},Src,,0,0,0,,{esc(c['text'])}")
        if c.get("tr"):
            ev.append(f"Dialogue: 0,{a},{b},Tr,,0,0,0,,{esc(c['tr'])}")
    return head + "\n".join(ev) + "\n"


# ====================================================================== P1：规则化断句修补（无大模型）
_EN_FUNC = {
    "a", "an", "the", "of", "in", "at", "on", "to", "for", "from", "by", "with", "into", "onto", "and",
    "or", "but", "nor", "as", "than", "that", "which", "who", "whose", "whom", "very", "so", "its",
    "his", "her", "their", "our", "my", "your", "this", "these", "those", "mr.", "mrs.", "ms.", "dr.",
    "st.", "about", "around", "over", "under", "between", "per", "via", "de", "van", "von", "la", "le", "du",
}
_EN_UNITS = {
    "years", "year", "km", "kilometers", "kilometres", "meters", "metres", "miles", "percent", "%",
    "people", "times", "days", "months", "hours", "minutes", "seconds", "dollars", "yuan", "bc", "ad",
    "million", "billion", "thousand", "hundred", "centuries", "century", "feet", "kg", "tons",
}
_ZH_TAIL_DE = set("的地得")
_ZH_TAIL_BAD = set("在和与及把被对从向给跟将于为是一这那每各")
_ZH_HEAD_BAD = set("的了着过吗呢吧啊呀们")
_ZH_MEASURE = set("个位年月日天岁米公里斤元万亿千百次只条张件名座本")
_TRAIL = ".,!?;:\"')]"


def _tokens(text: str, cjk: bool) -> list[str]:
    return list(text) if cjk else text.split()


def _join(toks: list[str], cjk: bool) -> str:
    return ("" if cjk else " ").join(toks).strip()


def _bad_boundary(prev: list[str], nxt: list[str], cjk: bool, terms: list[str]) -> tuple[str, int] | None:
    """判断 prev|nxt 的切点是否切开了短语。返回 (原因, 建议移动量：>0 把 nxt 头 n 个移到 prev，<0 把 prev 尾 n 个移到 nxt)。"""
    if not prev or not nxt:
        return None
    sep = "" if cjk else " "
    # 1) 受保护术语跨边界
    for t in terms:
        tt = _tokens(t, cjk)
        n = len(tt)
        for k in range(1, n):  # prev 尾 k 个 + nxt 头 n-k 个 = 术语
            a = [x.strip(_TRAIL).lower() for x in prev[-k:]]
            b = [x.strip(_TRAIL).lower() for x in nxt[: n - k]]
            if len(a) == k and len(b) == n - k and a + b == [x.lower() for x in tt]:
                return (f"term:{t}", (n - k) if n - k <= k else -k)
    last, first = prev[-1], nxt[0]
    if last[-1:] in _END:
        return None
    if cjk:
        if last in _ZH_TAIL_DE:  # “X的|名词”：把下一句开头的双字词拉上来
            return ("zh-tail-de", 2)
        if last in _ZH_TAIL_BAD:
            return ("zh-tail-func", -1)
        if first in _ZH_HEAD_BAD:
            return ("zh-head-particle", 1)
        if last.isdigit() and (first in _ZH_MEASURE or first.isdigit()):
            return ("zh-num-measure", 1)
        return None
    lw, fw = last.lower().strip(_TRAIL), first.lower().strip(_TRAIL)
    if last[-1:] in _SOFT:
        return None
    if lw in _EN_FUNC:
        return ("en-tail-func", -1)
    if re.fullmatch(r"[\d][\d,.]*", lw) and fw in _EN_UNITS:
        return ("en-num-unit", 1)
    # 专名链：Dragonbone | Hill、New | York（两侧都首字母大写，且 nxt 首词不是句首代词）
    if (last[:1].isupper() and first[:1].isupper() and len(prev) > 1
            and fw not in {"i", "he", "she", "it", "they", "we", "you", "the", "a", "an", "this", "but", "and"}):
        return ("en-proper-chain", 1)
    return None


def _split_time(c: dict, frac: float) -> float:
    return round(c["start"] + (c["end"] - c["start"]) * frac, 3)


def repair_breaks(
    cues: list[dict],
    *,
    terms: list[str] | tuple = (),
    max_gap: float = 0.35,
    max_chars: int = 0,
    passes: int = 2,
) -> list[dict]:
    """规则化修补“切开短语/专名”的断句（不依赖 LLM）。

    规则：受保护术语（glossary 键/用户词表）不跨句；英文句尾不以虚词/冠词/介词结束；数字与单位不分离；
    相邻大写专名链不切开；中文句尾不以“的/在/和…”结束、句首不以“了/吗/们…”开始、数字与量词不分离。
    修复方式：移动边界（少的一侧移给多的一侧），时间按词级时间戳（cue["words"]）或字符比例重估。
    只处理时间上相邻（间隙≤max_gap）的句子；有译文的句子改动后标 tr_stale=True（不调模型）。
    每个 cue 记录 fix 原因到 cue["fix"]。
    """
    out = [dict(c) for c in cues]
    terms = sorted({t for t in terms if t}, key=len, reverse=True)
    for _ in range(passes):
        changed = False
        for i in range(len(out) - 1):
            a, b = out[i], out[i + 1]
            if b["start"] - a["end"] > max_gap:
                continue
            cjk = _is_cjk(a["text"] + b["text"])
            lim = max_chars or (22 if cjk else 42)
            pa, pb = _tokens(a["text"], cjk), _tokens(b["text"], cjk)
            r = _bad_boundary(pa, pb, cjk, list(terms))
            if not r:
                continue
            why, n = r
            if n > 0 and len(pb) > n:  # nxt 头 n 个 → prev
                moved, pa2, pb2 = pb[:n], pa + pb[:n], pb[n:]
            elif n < 0 and len(pa) > -n:  # prev 尾 → nxt
                moved, pa2, pb2 = pa[n:], pa[:n], pa[n:] + pb
            else:
                continue
            ta, tb = _join(pa2, cjk), _join(pb2, cjk)
            if max(len(ta), len(tb)) > lim * 1.5:
                continue
            # 新边界时间
            ws = (a.get("words") or []) + (b.get("words") or [])
            if ws and len(ws) == len(pa) + len(pb):
                cut = len(pa2)
                t = round((ws[cut - 1]["end"] + ws[cut]["start"]) / 2, 3)
                a["words"], b["words"] = ws[:cut], ws[cut:]
            elif n > 0:
                L = max(1, len(b["text"]))
                t = _split_time(b, len(_join(moved, cjk)) / L)
            else:
                L = max(1, len(a["text"]))
                t = _split_time(a, 1 - len(_join(moved, cjk)) / L)
            if not (a["start"] + 0.2 < t < b["end"] - 0.2):
                continue
            a["text"], b["text"] = ta, tb
            a["end"], b["start"] = t, t if n > 0 else t
            if n < 0:
                b["start"] = t
            for c in (a, b):
                c.setdefault("fix", []).append(why)
                if c.get("tr"):
                    c["tr_stale"] = True
            changed = True
        if not changed:
            break
    return out
