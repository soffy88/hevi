"""多信号高光评分（思路：VideoHighlighter 多信号加权、ClipsAI 按转录找片段、hevi openshorts/virality 钩子词）。

纯函数：输入 cues（句级字幕，源时间轴）+ 可选逐窗信号，输出 top-N 片段（边界=整句）及每段入选理由。
信号（全部可缺省，缺的权重自动归零再归一）：
  loud    音量能量：窗口平均 dB 相对全片均值、峰值
  rate    语速：词/秒（拉丁）或字/秒（CJK）相对全片中位
  scene   场景切换密度：每分钟切点数
  motion  运动量：帧差均值相对全片
  keyword 转录关键词：用户关键词 + 钩子词（复用 openshorts.virality.score_text，缺则内置词表）
  complete 句子完整性：首句为句首（非小写/连接词开头）、末句以句末标点收
"""

from __future__ import annotations

import re
import statistics

DEFAULT_WEIGHTS = {"loud": 0.2, "rate": 0.15, "scene": 0.1, "motion": 0.15, "keyword": 0.25, "complete": 0.15}
_END = re.compile(r"[.!?。！？…]['\"”’)）]*\s*$")
_CJK = re.compile(r"[\u3400-\u9fff]")
_CONT_START = re.compile(r"^(and|but|or|so|because|which|who|that|to|of|in|at|on|with|for|from|"
                         r"而且|但是|所以|因为|并且|然后|和|的)\b", re.I)
_HOOK_FALLBACK = re.compile(
    r"secret|nobody|the truth|wrong|wait|why|how|never|first|surpris|amazing|million|thousand|\d{3,}|"
    r"秘密|没人|真相|其实|但是|千万|第一次|你不知道|揭秘|别再|竟然|为什么|怎么", re.I)


def _units(text: str) -> int:
    cjk = len(_CJK.findall(text))
    return cjk + len(re.findall(r"[A-Za-z0-9']+", text))


def _hook_score(text: str) -> tuple[float, list[str]]:
    try:  # 复用 hevi 现有 openshorts 钩子/情绪/金句打分
        from hevi.openshorts.virality import score_text

        sc, why = score_text(text)
        return max(0.0, min(1.0, (sc - 10) / 80.0)), [str(w) for w in why][:4]  # 0–100，基线 10
    except Exception:
        hits = sorted({m.group(0).lower() for m in _HOOK_FALLBACK.finditer(text)})
        return min(1.0, len(hits) / 3.0), hits[:3]


def _mean_in(series, a, b):
    v = [x for t, x in series if a <= t < b]
    return (sum(v) / len(v), max(v)) if v else (None, None)


def _norm(x, lo, hi):
    return 0.0 if x is None or hi <= lo else max(0.0, min(1.0, (x - lo) / (hi - lo)))


def candidate_windows(cues: list[dict], *, min_len: float = 15.0, max_len: float = 60.0) -> list[tuple[int, int]]:
    """所有“整句起止”的候选窗 (i,j)（含 cues[i..j]），时长在 [min_len,max_len]；不足 min_len 的短视频给整片。"""
    cs = [c for c in cues if not c.get("deleted")]
    out = []
    for i in range(len(cs)):
        for j in range(i, len(cs)):
            d = cs[j]["end"] - cs[i]["start"]
            if d > max_len:
                break
            if d >= min_len:
                out.append((i, j))
    if not out and cs:
        out = [(0, len(cs) - 1)]
    return out


def score_highlights(
    cues: list[dict],
    *,
    audio: list[tuple[float, float]] | None = None,
    motion: list[tuple[float, float]] | None = None,
    scenes: list[float] | None = None,
    keywords: list[str] | tuple = (),
    top_n: int = 3,
    min_len: float = 15.0,
    max_len: float = 60.0,
    weights: dict | None = None,
    max_overlap: float = 0.0,
) -> list[dict]:
    """返回 [{"rank","start","end","duration","cue_ids","score","features":{..0..1},"reasons":[..],"text"}]。

    边界永远对齐整句（cue 的 start/end）；入选片段两两重叠 ≤ max_overlap（秒）。
    """
    cs = [c for c in cues if not c.get("deleted")]
    if not cs:
        return []
    w = dict(DEFAULT_WEIGHTS, **(weights or {}))
    if not audio:
        w["loud"] = 0.0
    if not motion:
        w["motion"] = 0.0
    if scenes is None:
        w["scene"] = 0.0
    tot_w = sum(w.values()) or 1.0
    w = {k: v / tot_w for k, v in w.items()}
    # 全片基线
    rates = [_units(c["text"]) / max(0.3, c["end"] - c["start"]) for c in cs]
    med_rate = statistics.median(rates)
    a_mean = statistics.mean(x for _, x in audio) if audio else None
    m_vals = [x for _, x in motion] if motion else []
    m_mean = statistics.mean(m_vals) if m_vals else None
    m_p90 = sorted(m_vals)[int(0.9 * (len(m_vals) - 1))] if m_vals else None
    kws = [k.lower() for k in keywords if k]
    res = []
    for i, j in candidate_windows(cs, min_len=min_len, max_len=max_len):
        seg = cs[i:j + 1]
        a, b = seg[0]["start"], seg[-1]["end"]
        dur = b - a
        text = " ".join(c["text"].strip() for c in seg)
        f, why = {}, []
        if w["loud"]:
            am, ap = _mean_in(audio, a, b)
            f["loud"] = round(_norm((am or a_mean) - a_mean, -3.0, 6.0) * 0.7 + _norm((ap or a_mean) - a_mean, 0, 12) * 0.3, 3)
            if am is not None and am - a_mean >= 1.5:
                why.append(f"音量高于全片均值 {am - a_mean:+.1f} dB（峰 {ap:.1f} dBFS）")
        speech_t = sum(c["end"] - c["start"] for c in seg)
        rate = sum(_units(c["text"]) for c in seg) / max(0.5, speech_t)
        f["rate"] = round(_norm(rate / max(med_rate, 1e-6), 0.8, 1.4), 3)
        if rate >= med_rate * 1.15:
            why.append(f"语速 {rate:.2f} 单位/秒，快于全片中位 {100 * (rate / med_rate - 1):.0f}%")
        if w["scene"]:
            n_sc = sum(1 for t in scenes if a < t < b)
            per_min = n_sc / dur * 60
            f["scene"] = round(_norm(per_min, 0, 12), 3)
            if n_sc:
                why.append(f"场景切换 {n_sc} 次（{per_min:.1f}/分钟）")
        if w["motion"]:
            mm, _ = _mean_in(motion, a, b)
            f["motion"] = round(_norm(mm, m_mean * 0.8, max(m_p90, m_mean * 1.2 + 1e-6)), 3) if mm is not None else 0.0
            if mm is not None and m_mean and mm >= m_mean * 1.2:
                why.append(f"画面运动量为全片均值的 {mm / m_mean:.1f} 倍")
        hk, hk_why = _hook_score(text)
        low = text.lower()
        kw_hits = [k for k in kws if k in low]
        f["keyword"] = round(min(1.0, 0.5 * hk + 0.5 * min(1.0, len(kw_hits) / 2.0)) if kws else hk, 3)
        if kw_hits:
            why.append("命中关键词：" + "、".join(kw_hits[:4]))
        if hk_why and hk > 0:
            why.append("钩子/金句信号：" + "、".join(hk_why))
        head_ok = not _CONT_START.match(seg[0]["text"].strip()) and not seg[0]["text"].strip()[:1].islower()
        tail_ok = bool(_END.search(seg[-1]["text"]))
        f["complete"] = (0.5 if head_ok else 0.0) + (0.5 if tail_ok else 0.0)
        if head_ok and tail_ok:
            why.append("句子完整：以句首开始、以句末标点收尾")
        sc = sum(w[k] * f.get(k, 0.0) for k in w)
        res.append({"start": round(a, 3), "end": round(b, 3), "duration": round(dur, 3),
                    "cue_ids": [c.get("id") for c in seg], "score": round(sc, 4), "features": f,
                    "reasons": why or ["综合分最高的整句片段"], "text": text})
    res.sort(key=lambda r: (-r["score"], -r["features"].get("complete", 0), r["start"]))
    picked: list[dict] = []
    for r in res:
        if all(min(r["end"], p["end"]) - max(r["start"], p["start"]) <= max_overlap for p in picked):
            picked.append(r)
        if len(picked) >= top_n:
            break
    for k, r in enumerate(picked, 1):
        r["rank"] = k
    return picked


def highlights_to_timeline(tl: dict, highlights: list[dict], *, only: int | None = None) -> dict:
    """把高光写入 avcraft 时间线：markers(kind=highlight, 含 reasons)，并只保留所选片段（only=rank 仅保留一段）。

    tl 需为 timeline_from_cues 产物（含 cues）。保留区间外的 cues 标 deleted，导出字幕自动跟随。
    """
    from hevi.avcraft.oskill.timeline import set_region_keep

    hs = [h for h in highlights if only is None or h["rank"] == only]
    set_region_keep(tl, 0.0, tl["duration"], False, "not highlight")
    for h in hs:
        set_region_keep(tl, h["start"], h["end"], True, f"highlight #{h['rank']}")
    keep_ids = {cid for h in hs for cid in h["cue_ids"]}
    for c in tl.get("cues", []):
        c["deleted"] = c["id"] not in keep_ids
    tl["markers"] = sorted(
        [m for m in tl.get("markers", []) if m.get("kind") != "highlight"]
        + [{"t": h["start"], "end": h["end"], "kind": "highlight", "rank": h["rank"], "score": h["score"],
            "reasons": h["reasons"]} for h in highlights],
        key=lambda m: m["t"])
    tl.setdefault("params", {})["highlight"] = {"n": len(highlights), "only": only}
    return tl
