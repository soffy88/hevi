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
    fix: str = ""  # N0-D-011：可执行修法(门不仅判定、还给修法)，W 循环首要输入


def _sentences(draft: dict) -> list[tuple[dict, dict]]:
    return [(b, s) for b in draft.get("beats", []) for s in b.get("sentences", [])]


def _quotes(s: dict) -> list[dict]:
    q = s.get("quote")
    qs = [q] if isinstance(q, dict) else list(q or [])
    # 过滤空占位 quote(ulid/text 空)——空 quote 非引文，H2 不验它(不掩盖真引文)。
    return [x for x in qs if x.get("ulid") and x.get("text")]


def _sent_vo_secs(s: dict) -> float:
    """句 VO 实念时长(N0-D-010 引文呈现分离)：presentation=onscreen 的引文句画面呈现
    (竹简/字幕卡)、本体不口播计 0；vo 句非引文 5 字/s + 逐字短引按字幕 2 字/s。"""
    if s.get("presentation") == "onscreen":
        return 0.0
    tchars = len(s.get("text", ""))
    qchars = sum(len(q.get("text", "")) for q in _quotes(s))
    return max(0, tchars - qchars) / 5.0 + qchars / 2.0


_OPEN, _CLOSE = "『「“‘", "』」”’"


def _mark_ranges(text: str) -> list[tuple[int, int]]:
    """引号 span（含引号）——『』「」""''。用于 H2 扩门：引号内容必须挂 quote 对象。"""
    r, stack = [], []
    for i, ch in enumerate(text):
        if ch in _OPEN:
            stack.append(i)
        elif ch in _CLOSE and stack:
            r.append((stack.pop(), i + 1))
    return r


def _attach_quote(s: dict, q: dict) -> None:
    """把 quote 挂到句上（支持 dict/list/None 三态），不动其余字段。"""
    existing = s.get("quote")
    if not (isinstance(existing, dict) and existing.get("ulid")) and not existing:
        s["quote"] = q
    elif isinstance(existing, dict):
        s["quote"] = [existing, q]
    else:
        s["quote"] = [*list(existing), q]


def anchor_quotes(draft: dict, refs: dict) -> tuple[dict, list[dict]]:
    """R-hard 前置确定性预处理（N0-D-015）——引文自动锚定：句中未挂 quote 的引号内容
    在 corpus 逐字子串匹配（简繁归一后）；**唯一命中**→自动挂 quote{ulid,text,auto_anchored}
    （text 用原引号内容一字不改）；**零命中**→不挂（交 H2 判 FAIL）；**多处命中**→报回不猜。
    只锚定不改字、一字不增删。锚定=字符串匹配（机械），非截取原文（史学判断，N0-D-009 禁）。
    返回 (锚定后 draft, 报告[{sid,span,status∈{anchored,none,ambiguous},ulid?/ulids?}])。"""
    corpus = refs.get("corpus", {})
    norm_corpus = {u: _norm(t) for u, t in corpus.items()}
    reports: list[dict] = []
    out_beats = []
    for b in draft.get("beats", []):
        sents = []
        for s0 in b.get("sentences", []):
            s = dict(s0)
            text = s.get("text", "")
            marked = {_norm(q.get("text", "")) for q in _quotes(s)}
            for a, bnd in _mark_ranges(text):
                inner = text[a + 1 : bnd - 1]
                ninner = _norm(inner)
                if not ninner or any(ninner == m or ninner in m or m in ninner for m in marked):
                    continue  # 空引号或已挂 quote 覆盖
                hits = [u for u, nt in norm_corpus.items() if ninner in nt]
                if len(hits) == 1:
                    _attach_quote(s, {"ulid": hits[0], "text": inner, "auto_anchored": True})
                    marked.add(ninner)
                    reports.append(
                        {
                            "sid": s.get("sid"),
                            "span": inner[:20],
                            "status": "anchored",
                            "ulid": hits[0],
                        }
                    )
                elif not hits:
                    reports.append({"sid": s.get("sid"), "span": inner[:20], "status": "none"})
                else:
                    reports.append(
                        {
                            "sid": s.get("sid"),
                            "span": inner[:20],
                            "status": "ambiguous",
                            "ulids": hits,
                        }
                    )
            sents.append(s)
        out_beats.append({**b, "sentences": sents})
    return {**draft, "beats": out_beats}, reports


# ── H1 双溯源 ────────────────────────────────────────────────────────────────
def h1_dual_source(draft: dict, refs: dict) -> list[Failure]:
    ev, ac, th = refs.get("ku_events", {}), refs.get("ku_accounts", {}), refs.get("theses", {})
    out: list[Failure] = []
    for _b, s in _sentences(draft):
        sid, t = s.get("sid"), s.get("type")
        if t == "fact":
            fr = s.get("fact_refs") or []
            if not fr:
                out.append(
                    Failure(
                        "H1",
                        sid,
                        "fact 句 fact_refs 必填 ≥1",
                        "给此 fact 句挂 ≥1 个 fact_refs=[事件 id]（取自可用 KU events/accounts）",
                    )
                )
            out.extend(
                Failure(
                    "H1",
                    sid,
                    f"fact_ref 不可解析到 KU 对象: {r}",
                    f"fact_ref『{r}』不在 KU；换用可用 KU events/accounts 中的 id",
                )
                for r in fr
                if r not in ev and r not in ac
            )
        elif t == "thesis":
            tr = s.get("thesis_refs") or []
            if len(tr) != 1:
                out.append(
                    Failure(
                        "H1",
                        sid,
                        f"thesis 句 thesis_refs 必=1，实 {len(tr)}",
                        "thesis 句 thesis_refs 恰填 1 个 thesis id（多删、少补）",
                    )
                )
            out.extend(
                Failure(
                    "H1",
                    sid,
                    f"thesis_ref 不可解析: {r}",
                    f"thesis_ref『{r}』不在给定 theses；换用可用 theses 中的 id",
                )
                for r in tr
                if r not in th
            )
            if not (s.get("display") or {}).get("attribution"):
                out.append(
                    Failure(
                        "H1",
                        sid,
                        "thesis 句缺 attribution 呈现(R8/R10，我方须显式『按』)",
                        "补 display.attribution=『按…(论者·出处)』，显式署我方论断",
                    )
                )
        elif t == "transition":
            continue
        else:
            out.append(
                Failure(
                    "H1",
                    sid,
                    f"未知句型: {t!r}(须 fact|thesis|transition)",
                    "把 type 改为 fact|thesis|transition 之一",
                )
            )
    return out


# ── H2 引文保真 ──────────────────────────────────────────────────────────────
def h2_quote_fidelity(draft: dict, refs: dict) -> list[Failure]:
    corpus = refs.get("corpus", {})
    out: list[Failure] = []
    for _b, s in _sentences(draft):
        for qi in _quotes(s):
            u, txt = qi.get("ulid"), qi.get("text", "")
            if u not in corpus:
                out.append(
                    Failure(
                        "H2",
                        s.get("sid"),
                        f"quote ulid 不在语料: {u}",
                        f"quote.ulid『{u}』不在语料；换用给定 corpus_白文 中的 ulid",
                    )
                )
                continue
            if _norm(txt) not in _norm(corpus[u]):
                out.append(
                    Failure(
                        "H2",
                        s.get("sid"),
                        f"quote 未逐字命中语料 ULID 段: {u}",
                        f"quote.text 须是 corpus[{u}] 的逐字子串（繁体一字不改）："
                        f"『{corpus[u][:40]}…』",
                    )
                )
        # 扩门(N0-D-006)：句中引号 span 必须挂 quote 对象并过逐字机核——堵未标引文绕行。
        text = s.get("text", "")
        marked = [_norm(q.get("text", "")) for q in _quotes(s)]
        for a, b in _mark_ranges(text):
            inner = _norm(text[a + 1 : b - 1])
            if inner and not any(inner == m or inner in m or m in inner for m in marked):
                out.append(
                    Failure(
                        "H2",
                        s.get("sid"),
                        f"引号 span『{text[a + 1 : b - 1][:12]}…』未挂 quote(未标引文绕行)",
                        f"sid={s.get('sid')} 引号内容须挂 quote{{ulid,text}} 锚到语料 ULID，"
                        "或去掉引号改白话叙述（勿用引号包非逐字内容）",
                    )
                )
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
                Failure(
                    "H3",
                    s.get("sid"),
                    f"非引文数字 {unquoted_nums} 无 chronology/number ref",
                    f"数字 {unquoted_nums} 挂 number_refs/date_refs=[chronology 或 number id]，"
                    "否则删除该数字（无据不出数）",
                )
            )
    return out


# ── H4 名从注册表 + 原料池不可引(OP-D-054)────────────────────────────────────
def h4_names_registry(draft: dict, refs: dict) -> list[Failure]:
    pool, names = set(refs.get("pool_ids", ())), set(refs.get("name_registry", ()))
    # N0-D-013：注册表名简繁归一后比对——韓萬/韩万等异体不再误判缺口(同 H2/H4 归一族)。
    names_norm = {_norm(n) for n in names}
    out: list[Failure] = []
    for _b, s in _sentences(draft):
        allrefs = (s.get("fact_refs") or []) + (s.get("thesis_refs") or [])
        out.extend(
            Failure(
                "H4",
                s.get("sid"),
                f"引用原料池 id(OP-D-054 不可引): {r}",
                f"ref『{r}』是原料池 id（不可引）；换 KU events/accounts 中的正式 id",
            )
            for r in allrefs
            if r in pool
        )
        # H4 精化(N0-D-007)：quote span 内的名字豁免注册表(源内逐字、H2 已保真、R5 忠实)；
        # 引文外叙述句维持严格(注册表约束叙述、不约束原文，H3 豁免引文内数字同族)。
        quoted = _norm("".join(q.get("text", "") for q in _quotes(s)))
        for nm in s.get("entities") or []:
            if _norm(nm) in names_norm or _norm(nm) in quoted:
                continue  # 简繁归一后命中注册表(N0-D-013)或在引文内(N0-D-007)→ 豁免
            out.append(
                Failure(
                    "H4",
                    s.get("sid"),
                    f"叙述句人名/地名不在注册表(R3 按代取名): {nm}",
                    f"名『{nm}』未注册(registry 缺口)；若为引文内容则标 quote 豁免，否则改述回避",
                )
            )
    return out


# ── H5 冲突不抹平 ────────────────────────────────────────────────────────────
def h5_conflicts(draft: dict, refs: dict) -> list[Failure]:
    ep = refs.get("episode_plan", {})
    need = list(ep.get("s12_conflicts") or [])
    hints = ep.get("s12_conflict_hints") or {}  # {cf: "维度/拍提示"}（可选，供修法）
    presented: set[str] = set()
    for _b, s in _sentences(draft):
        presented.update(s.get("conflict_callouts") or [])
    for b in draft.get("beats", []):
        presented.update((b.get("conflict_omit_reasons") or {}).keys())
    out = []
    for cf in need:
        if cf in presented:
            continue
        loc = f"（{hints[cf]}）" if hints.get(cf) else ""
        out.append(
            Failure(
                "H5",
                None,
                f"S12 冲突未呈现且无不呈现理由: {cf}",
                f"在涉此冲突的拍{loc}补 conflict_callouts=[{cf!r}]，两说并陈（不择一坐实）；"
                "确不呈现则在该拍 conflict_omit_reasons 记理由",
            )
        )
    return out


# ── H6 counterpoint 非装饰(OP-D-051)─────────────────────────────────────────
def h6_counterpoint(draft: dict, refs: dict) -> list[Failure]:
    ep = refs.get("episode_plan", {})
    cps = ep.get("counterpoint_theses") or []
    if cps:
        shown = any(r in cps for _b, s in _sentences(draft) for r in (s.get("thesis_refs") or []))
        return (
            []
            if shown
            else [
                Failure(
                    "H6",
                    None,
                    "counterpoint 非空但稿内未呈现(=装饰)",
                    f"在 side-panel 拍呈现 counterpoint 论点（thesis_refs 取 {cps} 之一）≥1 次",
                )
            ]
        )
    if not ep.get("counterpoint_search_record"):
        return [
            Failure(
                "H6",
                None,
                "counterpoint 空且 EpisodePlan 无检索记录(OP-D-045)",
                "EpisodePlan 补 counterpoint_search_record（显式无须附检索证据）——W 侧不可自决",
            )
        ]
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
                out.append(
                    Failure(
                        "H7",
                        bid,
                        "涉 E3/E4 事件的拍缺等级标注指令(R9)",
                        f"拍 {bid} 涉 E3/E4 事件，补 e_banner 等级标注指令（拍级或句级）",
                    )
                )
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
                Failure(
                    "H8",
                    None,
                    f"transition 占比 {tr}/{len(sents)}={tr / len(sents):.0%} >20%",
                    "删减/合并 transition 句，或改写为 fact/thesis（带 ref），使占比 ≤20%",
                )
            )
    plan_beats = set(ep.get("beat_ids") or [])
    for b in draft.get("beats", []):
        bid = b.get("beat_id")
        # splitter 拆出的子拍带 parent_beat 回原拍——认 parent 即对齐(N0-D-003 确定性收尾)。
        if plan_beats and bid not in plan_beats and b.get("parent_beat") not in plan_beats:
            out.append(
                Failure(
                    "H8",
                    bid,
                    "beat 不对齐 EpisodePlan",
                    f"beat_id『{bid}』不在 EpisodePlan.beat_ids；对齐到 plan 拍 id",
                )
            )
        # VO 分段估时(N0-D-001/010,裁决见 DECISIONS-N0.md)：按 VO 实念求和——非引文
        # 口播 5 字/s、逐字短引按字幕 2 字/s；onscreen 引文句本体不口播计 0(呈现分离)。
        bsents = b.get("sentences", [])
        secs = sum(_sent_vo_secs(s) for s in bsents)
        if not 5.0 <= secs <= 15.0:
            # 超窗：若拍内有非 onscreen 长引文，首选标 onscreen + 补转述；否则拆句/重述。
            long_q = [
                s.get("sid")
                for s in bsents
                if s.get("presentation") != "onscreen"
                and sum(len(q.get("text", "")) for q in _quotes(s)) >= 15
            ]
            if secs > 15.0 and long_q:
                fix = (
                    f"此拍 {secs:.1f}s 超窗；把长引文句 {long_q} 标 presentation=onscreen"
                    "（画面呈现、不计 VO），并在同拍补一句 vo 白话转述句"
                )
            elif secs > 15.0:
                fix = f"此拍 {secs:.1f}s 超窗；按分句边界拆为两拍，或改述缩短口播文字"
            else:
                fix = f"此拍仅 {secs:.1f}s 欠窗；扩写口播内容或与相邻同 role 拍合并至 5–15s"
            out.append(Failure("H8", bid, f"VO 分段估时 {secs:.1f}s 不在 5–15s/拍", fix))
        # onscreen 引文必配同拍白话转述(N0-D-010)：含 onscreen 句的拍须有 ≥1 个
        # 非 onscreen 的 fact/thesis 口播句(转述),否则画面有引文而无人念 → FAIL。
        if any(s.get("presentation") == "onscreen" for s in bsents) and not any(
            s.get("presentation") != "onscreen" and s.get("type") in ("fact", "thesis")
            for s in bsents
        ):
            out.append(
                Failure(
                    "H8",
                    bid,
                    "onscreen 引文缺同拍白话转述(vo)",
                    f"拍 {bid} 有 onscreen 引文但无口播转述；补一句 vo fact/thesis 白话转述该引文",
                )
            )
    return out


# ── H9 拍-role 一致性(N0-D-005)────────────────────────────────────────────────
def h9_beat_role(draft: dict, refs: dict) -> list[Failure]:
    ep = refs.get("episode_plan", {})
    roles = ep.get("beat_roles", {})  # plan beat_id → "fact" | "thesis"（未声明则跳过 role 检）
    allow_repeat = set(ep.get("allow_thesis_repeat", ()))
    out: list[Failure] = []
    # ① 拍-role：净稿拍(经 parent 回原 plan 拍)的 fact/thesis 句分布须合声明。
    for b in draft.get("beats", []):
        role = roles.get(b.get("parent_beat") or b.get("beat_id"))
        if role not in ("fact", "thesis"):
            continue
        content = {
            s.get("type") for s in b.get("sentences", []) if s.get("type") in ("fact", "thesis")
        }
        if role == "fact" and "thesis" in content:
            out.append(
                Failure(
                    "H9",
                    b.get("beat_id"),
                    "fact 拍出现 thesis 句(拍-role 不一致)",
                    f"拍 {b.get('beat_id')} 声明为 fact 拍；移走 thesis 句或改 plan role",
                )
            )
        if role == "thesis" and "fact" in content:
            out.append(
                Failure(
                    "H9",
                    b.get("beat_id"),
                    "thesis 拍出现 fact 句(拍-role 不一致)",
                    f"拍 {b.get('beat_id')} 声明为 thesis 拍；移走 fact 句或改 plan role",
                )
            )
    # ② 同一 thesis_ref 全稿呈现 >1 次须 EpisodePlan 显式允许(allow_thesis_repeat)。
    counts: dict[str, int] = {}
    for _b, s in _sentences(draft):
        if s.get("type") == "thesis":
            for r in s.get("thesis_refs") or []:
                counts[r] = counts.get(r, 0) + 1
    for ref, n in counts.items():
        if n > 1 and ref not in allow_repeat:
            out.append(
                Failure(
                    "H9",
                    None,
                    f"thesis_ref {ref} 全稿呈现 {n} 次 >1，EpisodePlan 未显式允许",
                    f"论点『{ref}』重复 {n} 次；收敛为 1 次呈现，或（若确需贯串）"
                    "请 EpisodePlan.allow_thesis_repeat 显式允许——W 侧不可自决",
                )
            )
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
    "H9": h9_beat_role,
}


def run_rhard(draft: dict, refs: dict) -> dict[str, Any]:
    """跑全部 H1–H9，返回 HardReport。纯确定性，无模型。"""
    results = {g: fn(draft, refs) for g, fn in _GATES.items()}
    failures = [vars(f) for fs in results.values() for f in fs]
    return {
        "pass": not failures,
        "by_gate": {g: ("PASS" if not fs else "FAIL") for g, fs in results.items()},
        "failures": failures,
        "n_failures": len(failures),
    }
