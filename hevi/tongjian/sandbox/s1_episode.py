"""s1 曲沃代翼 · N1 节拍切分 + N2 事实装配(从 N0 9/9 净稿投影)。

N0 閘⓪ 已过(GATE0-N0-s1-quwo-9of9)。净稿(output/n0_s1/s1_full_clean_script.json)13 拍(含
splitter 子拍)聚合为 10 叙事拍;vo_text=拍内 vo 句(onscreen 引文不口播、走 S13 竹简);
cf→S12 双半幅(egou-di-vs-zi/cebming-fanwei);onscreen 引文→S13。VisualFact 逐字投影不自造。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from hevi.tongjian.explainer_contract import (
    Account,
    DualAccountFact,
    EpisodePlan,
    NarrationBeat,
    VisualFact,
)

_NET = Path("output/n0_s1/s1_full_clean_script.json")

EPISODE = EpisodePlan(
    episode_id="ep_jin_decline_s1",
    dynasty_era="春秋早期(前745–前678)",
    narrative_frame="曲沃代翼:小宗曲沃历三世六十七年并吞晋大宗——师服『本大而末小』之应验。",
    narration_script_ref=str(_NET),
)

# 净稿 plan 拍(parent) → (叙事拍序, visual_intent, shot). onscreen/cf 由净稿字段驱动。
# shot: establish/character/dual_account(S12)/route/quote_slip(S13)/battle/split_merge(tear)/hold
_PLAN = [
    ("s1-b0", "b0", "establish", -745),
    ("s1-b1", "b1", "character", -745),
    ("s1-b2", "b2", "dual_account", -725),  # S12 egou-di-vs-zi
    ("s1-b3", "b3", "route", -718),
    ("s1-b4", "b4", "battle", -709),  # 武公伐翼;onscreen 引文『三年春…』→ S13 竹简
    ("s1-b5", "b5", "battle", -705),
    ("s1-b6", "b6", "split_merge", -704),  # tear:曲沃吞并翼
    ("s1-b7", "b7", "dual_account", -678),  # S12 cebming-fanwei
    ("s1-b8", "b8", "hold", -678),
    ("s1-b9", "b9", "hold", -679),
]


def _load_net() -> dict:
    return json.loads(_NET.read_text())


def _plan_beat_of(sub_beat: dict) -> str:
    return sub_beat.get("parent_beat") or sub_beat["beat_id"]


def build():
    """净稿 → (BEATS, FACTS, DUAL_ACCOUNTS, ONSCREEN_QUOTES, CF_OF_BEAT)。"""
    net = _load_net()
    # 聚合每 plan 拍的 vo 句文字 + onscreen 引文 + cf。onscreen 引文按 W 原句 sid 前缀(b4-1→b4)
    # 归叙事拍——splitter 可能把 onscreen 句并进邻 plan 拍(如 b4-1 落 s1-b3#1),但引文与其白话
    # 转述同属该事件,须归本叙事拍(b4)不随 splitter 窗口漂。
    vo_by, onscreen_bid, cf_by = {}, {}, {}
    for b in net["beats"]:
        pb = _plan_beat_of(b)
        for s in b["sentences"]:
            if s.get("presentation") == "onscreen":
                q = s.get("quote")
                qtext = (q["text"] if isinstance(q, dict) else q[0]["text"]) if q else s["text"]
                m = re.match(r"b\d+", s.get("sid", ""))
                onscreen_bid[m.group() if m else pb] = qtext  # 键=叙事 bid(逐字引文)
            else:
                vo_by.setdefault(pb, []).append(s["text"])
            for cf in s.get("conflict_callouts") or []:
                cf_by.setdefault(pb, set()).add(cf)

    beats, facts = [], []
    for i, (pb, bid, intent, date) in enumerate(_PLAN):
        vo = "".join(vo_by.get(pb, []))
        beats.append(
            NarrationBeat(
                beat_id=bid,
                order=i,
                visual_intent=intent if intent in _VALID else "hold",
                est_vo_seconds=max(3, round(len(vo) / 5)),
                vo_text=vo,
                fact_ref=f"vf_{bid}",
            )
        )
        facts.append(
            VisualFact(
                beat_id=bid,
                date=date,
                scope="晋国内部(临汾盆地)",
                forces=_FORCES_OF.get(bid, ["yi", "quwo"]),
                persons=_PERSONS_OF.get(bid, []),
                markers=_MARKERS_OF.get(bid, []),
                evidence_tier="E1",
                confirmed_by="左传/史记(N0 H1 双溯源过)",
            )
        )
    # S12 对勘(两 cf,清 G1a 数据有画面无欠账)
    duals = [
        DualAccountFact(
            beat_id="b2",
            conflict_ku_ref="cf:egou-di-vs-zi",
            dimension="继位者:弟/子",
            presentation_hint="S12 双半幅对勘",
            accounts=[
                Account(source_display="《左传》", summary="翼人立其弟鄂侯"),
                Account(source_display="一说", summary="立孝侯之子郄为君"),
            ],
        ),
        DualAccountFact(
            beat_id="b7",
            conflict_ku_ref="cf:cebming-fanwei",
            dimension="册命范围:全晋/一军",
            presentation_hint="S12 双半幅对勘",
            accounts=[
                Account(source_display="《史记》", summary="尽併晋地而有之"),
                Account(source_display="《左传》", summary="王命曲沃伯以一军为晋侯"),
            ],
        ),
    ]
    onscreen = {bid: q for bid, q in onscreen_bid.items() if bid in {p[1] for p in _PLAN}}
    cf_of = {pb2bid[pb]: sorted(v) for pb, v in cf_by.items() if pb in pb2bid}
    return beats, facts, duals, onscreen, cf_of


_VALID = {
    "establish",
    "character",
    "dual_account",
    "route",
    "battle",
    "split_merge",
    "hold",
    "highlight",
    "expand",
    "city",
    "timeline",
}
pb2bid = {p[0]: p[1] for p in _PLAN}
_FORCES_OF = {
    "b0": ["zhou", "yi", "quwo"],
    "b6": ["yi", "quwo"],
    "b7": ["quwo"],
    "b9": ["quwo"],
}
_PERSONS_OF = {"b1": ["huanshu"]}  # 封桓叔于曲沃(S7 立牌)
_MARKERS_OF = {
    "b3": ["翼", "随"],
    "b4": ["陘庭", "汾隰"],
    "b5": ["曲沃"],
    "b6": ["翼"],
}


def main():
    beats, facts, duals, onscreen, cf_of = build()
    print(f"EpisodePlan: {EPISODE.episode_id} / {EPISODE.dynasty_era}")
    print(f"N1 节拍: {len(beats)} 叙事拍, VO 总估 {sum(b.est_vo_seconds for b in beats)}s")
    assert {b.beat_id for b in beats} == {f.beat_id for f in facts}, "拍↔事实不齐"
    print(f"S13 onscreen 引文: {list(onscreen)} → 竹简")
    print(f"S12 对勘: {[d.beat_id + ':' + d.dimension for d in duals]}")
    print(f"cf 归拍: {cf_of}")
    for b, f in zip(beats, facts, strict=True):
        extra = " S13引文" if b.beat_id in onscreen else ""
        extra += f" S12={cf_of[b.beat_id]}" if b.beat_id in cf_of else ""
        print(
            f"  {b.beat_id} [{b.visual_intent}] {f.date} {f.forces}{extra}"
            f"  VO{b.est_vo_seconds}s «{b.vo_text[:24]}…»"
        )


if __name__ == "__main__":
    main()
