"""R-hard 硬门（HEVI-N0-DUALAGENT-SPEC-001 §3）——全部确定性代码，禁用任何模型。

输入 ScriptDraft(§2 句级双轨 dict) + refs(KU/thesis/corpus/注册表) → HardReport
(每门 PASS/FAIL + 失败句 sid)。不可欺裁判原则：LLM 产出、代码审判。

ScriptDraft(§2)::
  {episode_ref, beats[{beat_id, sentences[{sid, type∈{fact|thesis|transition}, text,
   fact_refs[], thesis_refs[], quote{ulid,text}|[...], entities[], display{source_display,
   attribution}, e_banner?, conflict_callouts[], date_refs[], number_refs[]}]}], meta{...}}

refs::
  {episode_plan, ku_events{id:_}, ku_accounts{id:_}, theses{id:_}, corpus{ulid:白文},
   chronology{id:_}, number_claims{id:_}, name_registry{name,...}, pool_ids{id,...},
   e_tiers{ev:tier}}
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# 归一(H2/H4)：剥空白/标点；简繁归一(opencc 有则用，无则恒等——同script 比对不受影响)。
_PUNCT = set("，。、；：！？「」『』（）〔〕【】《》〈〉…—·.,:;!?\"'()<>[]{}　 \t\r\n")


def _norm(s: Any) -> str:
    t = "".join(ch for ch in str(s) if ch not in _PUNCT)
    try:  # 简繁归一(可选)
        import opencc  # type: ignore

        t = opencc.OpenCC("t2s").convert(t)
    except Exception:
        pass
    return t


# 数量/日期『声明』——只抓带单位或前/公元的数字（『围两年』『前745』『六十七年』），
# 不抓制度名内数字（六卿/三家/五霸/九鼎）——那些是名不是声明（H4 管名）。
_NUM = r"[0-9一二三四五六七八九十百千万亿零两廿卅]+"
# (?:前|公元)N = 纪年（前745/公元200）；N+单位 = 数量声明（三年/六十七年/千里/万人）
_CLAIM_RE = re.compile(
    rf"(?:前|公元)\s*{_NUM}|{_NUM}\s*(?:年|岁|歲|月|日|世|世纪|載|载|里|人|萬|万|億|亿|旬|秊)"
)


@dataclass
class Failure:
    gate: str
    sid: str | None
    reason: str


def _sentences(draft: dict) -> list[tuple[dict, dict]]:
    return [(b, s) for b in draft.get("beats", []) for s in b.get("sentences", [])]


def _quotes(s: dict) -> list[dict]:
    q = s.get("quote")
    if isinstance(q, dict):
        return [q]
    return list(q or [])


# ── H1 双溯源 ────────────────────────────────────────────────────────────────
def h1_dual_source(draft: dict, refs: dict) -> list[Failure]:
    ev, ac, th = refs.get("ku_events", {}), refs.get("ku_accounts", {}), refs.get("theses", {})
    out: list[Failure] = []
    for _b, s in _sentences(draft):
        sid, t = s.get("sid"), s.get("type")
        if t == "fact":
            fr = s.get("fact_refs") or []
            if not fr:
                out.append(Failure("H1", sid, "fact 句 fact_refs 必填 ≥1"))
            out.extend(
                Failure("H1", sid, f"fact_ref 不可解析到 KU 对象: {r}")
                for r in fr
                if r not in ev and r not in ac
            )
        elif t == "thesis":
            tr = s.get("thesis_refs") or []
            if len(tr) != 1:
                out.append(Failure("H1", sid, f"thesis 句 thesis_refs 必=1，实 {len(tr)}"))
            out.extend(Failure("H1", sid, f"thesis_ref 不可解析: {r}") for r in tr if r not in th)
            if not (s.get("display") or {}).get("attribution"):
                out.append(
                    Failure("H1", sid, "thesis 句缺 attribution 呈现(R8/R10，我方须显式『按』)")
                )
        elif t == "transition":
            continue
        else:
            out.append(Failure("H1", sid, f"未知句型: {t!r}(须 fact|thesis|transition)"))
    return out


# ── H2 引文保真 ──────────────────────────────────────────────────────────────
def h2_quote_fidelity(draft: dict, refs: dict) -> list[Failure]:
    corpus = refs.get("corpus", {})
    out: list[Failure] = []
    for _b, s in _sentences(draft):
        for qi in _quotes(s):
            u, txt = qi.get("ulid"), qi.get("text", "")
            if u not in corpus:
                out.append(Failure("H2", s.get("sid"), f"quote ulid 不在语料: {u}"))
                continue
            if _norm(txt) not in _norm(corpus[u]):
                out.append(Failure("H2", s.get("sid"), f"quote 未逐字命中语料 ULID 段: {u}"))
    return out


# ── H3 日期/数字（『围两年』事故的制度化根除）────────────────────────────────
def h3_dates_numbers(draft: dict, refs: dict) -> list[Failure]:
    chron, ncl = refs.get("chronology", {}), refs.get("number_claims", {})
    out: list[Failure] = []
    for _b, s in _sentences(draft):
        quoted = _norm("".join(q.get("text", "") for q in _quotes(s)))
        unquoted_nums = [n for n in _CLAIM_RE.findall(s.get("text", "")) if _norm(n) not in quoted]
        if not unquoted_nums:
            continue
        backed_refs = set(
            (s.get("date_refs") or []) + (s.get("number_refs") or []) + (s.get("fact_refs") or [])
        )
        if not any(r in chron or r in ncl for r in backed_refs):
            out.append(
                Failure("H3", s.get("sid"), f"非引文数字 {unquoted_nums} 无 chronology/number ref")
            )
    return out


# ── H4 名从注册表 + 原料池不可引(OP-D-054)────────────────────────────────────
def h4_names_registry(draft: dict, refs: dict) -> list[Failure]:
    pool, names = set(refs.get("pool_ids", ())), set(refs.get("name_registry", ()))
    out: list[Failure] = []
    for _b, s in _sentences(draft):
        allrefs = (s.get("fact_refs") or []) + (s.get("thesis_refs") or [])
        out.extend(
            Failure("H4", s.get("sid"), f"引用原料池 id(OP-D-054 不可引): {r}")
            for r in allrefs
            if r in pool
        )
        out.extend(
            Failure("H4", s.get("sid"), f"人名/地名不在注册表(R3 按代取名): {nm}")
            for nm in (s.get("entities") or [])
            if nm not in names
        )
    return out


# ── H5 冲突不抹平 ────────────────────────────────────────────────────────────
def h5_conflicts(draft: dict, refs: dict) -> list[Failure]:
    ep = refs.get("episode_plan", {})
    need = list(ep.get("s12_conflicts") or [])
    presented: set[str] = set()
    for _b, s in _sentences(draft):
        presented.update(s.get("conflict_callouts") or [])
    for b in draft.get("beats", []):
        presented.update((b.get("conflict_omit_reasons") or {}).keys())
    return [
        Failure("H5", None, f"S12 冲突未呈现且无不呈现理由: {cf}")
        for cf in need
        if cf not in presented
    ]


# ── H6 counterpoint 非装饰(OP-D-051)─────────────────────────────────────────
def h6_counterpoint(draft: dict, refs: dict) -> list[Failure]:
    ep = refs.get("episode_plan", {})
    cps = ep.get("counterpoint_theses") or []
    if cps:
        shown = any(r in cps for _b, s in _sentences(draft) for r in (s.get("thesis_refs") or []))
        return [] if shown else [Failure("H6", None, "counterpoint 非空但稿内未呈现(=装饰)")]
    if not ep.get("counterpoint_search_record"):
        return [Failure("H6", None, "counterpoint 空且 EpisodePlan 无检索记录(OP-D-045)")]
    return []


# ── H7 E-banner(R9)──────────────────────────────────────────────────────────
def h7_e_banner(draft: dict, refs: dict) -> list[Failure]:
    et, ep = refs.get("e_tiers", {}), refs.get("episode_plan", {})
    beat_events = ep.get("beat_events", {})
    out: list[Failure] = []
    for b in draft.get("beats", []):
        bid = b.get("beat_id")
        if any(et.get(e) in ("E3", "E4") for e in beat_events.get(bid, [])):
            has = b.get("e_banner") or any(s.get("e_banner") for s in b.get("sentences", []))
            if not has:
                out.append(Failure("H7", bid, "涉 E3/E4 事件的拍缺等级标注指令(R9)"))
    return out


# ── H8 结构 ──────────────────────────────────────────────────────────────────
def h8_structure(draft: dict, refs: dict) -> list[Failure]:
    ep = refs.get("episode_plan", {})
    out: list[Failure] = []
    sents = [s for _b, s in _sentences(draft)]
    if sents:
        tr = sum(1 for s in sents if s.get("type") == "transition")
        if tr / len(sents) > 0.20:
            out.append(
                Failure("H8", None, f"transition 占比 {tr}/{len(sents)}={tr / len(sents):.0%} >20%")
            )
    plan_beats = set(ep.get("beat_ids") or [])
    for b in draft.get("beats", []):
        bid = b.get("beat_id")
        if plan_beats and bid not in plan_beats:
            out.append(Failure("H8", bid, "beat 不对齐 EpisodePlan"))
        # VO 分段估时(N0-D-001,裁决见 DECISIONS-N0.md)：非引文口播 5 字/s +
        # H2 锁定的逐字引文按字幕呈现 2 字/s，拍级求和判 5–15s。
        secs = 0.0
        for s in b.get("sentences", []):
            tchars = len(s.get("text", ""))
            qchars = sum(len(q.get("text", "")) for q in _quotes(s))
            secs += max(0, tchars - qchars) / 5.0 + qchars / 2.0
        if not 5.0 <= secs <= 15.0:
            out.append(Failure("H8", bid, f"VO 分段估时 {secs:.1f}s 不在 5–15s/拍"))
    return out


_GATES = {
    "H1": h1_dual_source,
    "H2": h2_quote_fidelity,
    "H3": h3_dates_numbers,
    "H4": h4_names_registry,
    "H5": h5_conflicts,
    "H6": h6_counterpoint,
    "H7": h7_e_banner,
    "H8": h8_structure,
}


def run_rhard(draft: dict, refs: dict) -> dict[str, Any]:
    """跑全部 H1–H8，返回 HardReport。纯确定性，无模型。"""
    results = {g: fn(draft, refs) for g, fn in _GATES.items()}
    failures = [vars(f) for fs in results.values() for f in fs]
    return {
        "pass": not failures,
        "by_gate": {g: ("PASS" if not fs else "FAIL") for g, fs in results.items()},
        "failures": failures,
        "n_failures": len(failures),
    }
