"""post-W 确定性收尾 splitter（N0-D-003）——纯代码零 LLM，置于 W 产出与 R-hard 之间。

超窗拍（VO 分段估时 >15s）取最长句、按分句边界（。；：！？;:!?）拆两句，两半分入两拍
（parent 链回原拍，H8 对齐认 parent）；继承原句 type 与 refs，**quote span 与 ref 一字不动**
（拆点不落 quote 内，quote 归含它的半句）；递归至拍落窗或句不可再分——**句不可拆则原样
交 R-hard 判 FAIL，不掩盖**。

原则（N0-D-003）：长度/计数/格式这类可精确计算的约束由代码兜底，不交 LLM；
LLM 只负责内容与措辞。H2 引文逐字、H3 数字须 ref 之后，同族第三次适用。
"""

from __future__ import annotations

_BOUND = "。；：！？;:!?｡"  # 分句边界
_MAX_SECS = 15.0
_INHERIT = (
    "type",
    "fact_refs",
    "thesis_refs",
    "entities",
    "display",
    "number_refs",
    "e_banner",
    "conflict_callouts",
    "presentation",
)


def _quotes(s: dict) -> list[dict]:
    q = s.get("quote")
    qs = [q] if isinstance(q, dict) else list(q or [])
    return [x for x in qs if x.get("ulid") and x.get("text")]  # 过滤空占位


def _sent_secs(s: dict) -> float:
    # onscreen 引文句本体画面呈现、不口播计 0(N0-D-010)——长引文标 onscreen 即不触发拆分。
    if s.get("presentation") == "onscreen":
        return 0.0
    tchars = len(s.get("text", ""))
    qchars = sum(len(q.get("text", "")) for q in _quotes(s))
    return max(0, tchars - qchars) / 5.0 + qchars / 2.0


def _beat_secs(beat: dict) -> float:
    return sum(_sent_secs(s) for s in beat.get("sentences", []))


_OPEN = "『「“‘"
_CLOSE = "』」”’"


def _mark_ranges(text: str) -> list[tuple[int, int]]:
    """引号 span 区间（含引号本身）——『』「」""''。用于禁止在引号内拆句（N0-D-004）。"""
    r, stack = [], []
    for i, ch in enumerate(text):
        if ch in _OPEN:
            stack.append(i)
        elif ch in _CLOSE and stack:
            r.append((stack.pop(), i + 1))
    return r


def _quote_ranges(text: str, s: dict) -> list[tuple[int, int]]:
    r = []
    for q in _quotes(s):
        qt = q.get("text", "")
        i = text.find(qt)
        if qt and i >= 0:
            r.append((i, i + len(qt)))
    return r


def _split_sentence(s: dict) -> list[dict]:
    """按分句边界拆两句；拆点须**在引文外**（引号 span 与 quote span 内的标点不作边界，
    N0-D-004）；quote 归含它的半句；继承 type/refs。返回 [s]（不可拆）或 [a, b]。"""
    text = s.get("text", "")
    forbidden = _quote_ranges(text, s) + _mark_ranges(text)  # 引号内 + 已标 quote 内均不可拆
    cands = [
        i + 1
        for i, ch in enumerate(text)
        if ch in _BOUND and 0 < i + 1 < len(text) and not any(a < i + 1 <= b for a, b in forbidden)
    ]
    if not cands:
        return [s]  # 无引文外分句边界 → 不可拆（原样交 R-hard 判）
    mid = len(text) / 2
    cut = min(cands, key=lambda i: abs(i - mid))
    ta, tb = text[:cut], text[cut:]
    base = {k: s[k] for k in _INHERIT if k in s}
    a = {**base, "sid": f"{s.get('sid', '')}-a", "text": ta}
    b = {**base, "sid": f"{s.get('sid', '')}-b", "text": tb}
    for half, txt in ((a, ta), (b, tb)):
        qs = [q for q in _quotes(s) if q.get("text", "") and q.get("text", "") in txt]
        if qs:
            half["quote"] = qs[0] if len(qs) == 1 else qs
    return [a, b]


def _split_beat(beat: dict, max_secs: float) -> list[dict]:
    """把一个超窗拍拆成若干 ≤max 的拍（或含 1 个不可拆的超窗拍，交 R-hard FAIL）。

    N0-D-020 混合拍(N0-D-004 推广)：含 onscreen 句的拍，拆分只作用于**非-onscreen 句**——
    onscreen 句时长恒计 0 且**永不拆动**;剩余非-onscreen 句超窗则正常 _split_sentence。
    """
    if _beat_secs(beat) <= max_secs:
        return [beat]
    sents = beat.get("sentences", [])
    if not sents:
        return [beat]
    # N0-D-020：只在**非-onscreen** 句里挑最长者拆；onscreen 句(0 计)永不选为拆分对象。
    splittable = [i for i, s in enumerate(sents) if s.get("presentation") != "onscreen"]
    if not splittable:
        return [beat]  # 全 onscreen(0 计) → 不可能超窗;防御性兜底，不拆
    li = max(splittable, key=lambda i: _sent_secs(sents[i]))
    if len(sents) == 1:
        halves = _split_sentence(sents[0])
        if len(halves) == 1:
            return [beat]  # 句不可拆 → 不掩盖，交 R-hard 判 FAIL
        left = {**beat, "sentences": [halves[0]]}
        right = {**beat, "sentences": [halves[1]]}
        return _split_beat(left, max_secs) + _split_beat(right, max_secs)
    # 多句拍：把最长(非-onscreen)句移到新拍，onscreen 句留原拍(随非拆句),递归
    left = {**beat, "sentences": sents[:li] + sents[li + 1 :]}
    right = {**beat, "sentences": [sents[li]]}
    return _split_beat(left, max_secs) + _split_beat(right, max_secs)


def _root(b: dict) -> str:
    return b.get("parent_beat") or b.get("beat_id")


def _beat_role(b: dict) -> set[str]:
    """拍内容 role：非 transition 句的 type 集（{fact}/{thesis}/空=纯 transition）。"""
    return {s.get("type") for s in b.get("sentences", []) if s.get("type") in ("fact", "thesis")}


def _can_merge(a: dict, b: dict) -> bool:
    """可合并：不跨 fact/thesis 边界（一方纯 transition 或 role 相容即可）。"""
    ra, rb = _beat_role(a), _beat_role(b)
    return not (("fact" in ra and "thesis" in rb) or ("thesis" in ra and "fact" in rb))


def _merge_underwindow(beats: list[dict], min_secs: float, max_secs: float) -> list[dict]:
    """把欠窗(<min)子拍就近并回相邻拍(合并后 ≤max)——拆分的对偶，保子拍落 [min,max]。
    同 root 优先；无同 root 可并时**跨 parent 就近合并**(N0-D-007 splitter 补)，
    但**不跨 fact/thesis 边界**(_can_merge)。"""
    out: list[dict] = []
    for b in beats:
        if out:
            prev = out[-1]
            underwin = _beat_secs(b) < min_secs or _beat_secs(prev) < min_secs
            fits = _beat_secs(prev) + _beat_secs(b) <= max_secs
            same_root = _root(prev) == _root(b)
            if underwin and fits and (same_root or _can_merge(prev, b)):
                out[-1] = {**prev, "sentences": prev["sentences"] + b["sentences"]}
                continue
        out.append(b)
    return out


def split_overlong(draft: dict, *, max_secs: float = _MAX_SECS, min_secs: float = 5.0) -> dict:
    """遍历各拍：超窗者拆分（子拍 beat_id 加 #k、parent_beat 回原拍），再并回欠窗子拍，
    使每子拍尽量落 [min,max]。仍越界者(如整句长引文不可拆)原样交 R-hard 判 FAIL，不掩盖。"""
    out: list[dict] = []
    for beat in draft.get("beats", []):
        root = beat.get("beat_id")
        for k, p in enumerate(_split_beat(beat, max_secs)):
            p = dict(p)
            if k > 0:
                p["beat_id"] = f"{root}#{k}"
                p["parent_beat"] = root
            out.append(p)
    out = _merge_underwindow(out, min_secs, max_secs)
    return {**draft, "beats": out}
