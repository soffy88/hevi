"""s3 晋作三军五军·六卿彊 · N1 节拍切分(从 N0 7/9 净稿投影)。

净稿 output/n0_s3/s1_full_clean_script.json(5 叙事拍)。1 cf(上军主帅)→S12;多 onscreen→S13 竹简;
mainline=shuxiang-gongshi-jiang-bei,并陈 zhongni-shidu,counterpoint 显式无。
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

_NET = Path("output/n0_s3/s1_full_clean_script.json")
EPISODE = EpisodePlan(
    episode_id="ep_jin_decline_s3", dynasty_era="春秋中晚期(前633–前526)",
    narrative_frame="晋作三军五军、军制屡扩、诸卿掌军——叔向『公室将卑』、仲尼『失度则国亡』,六卿坐大之制度前提。",
    narration_script_ref=str(_NET),
)
# b0 establish(叔向设立+晋map) / b1 S12(cf上军) / b2·b3·b4 S13竹简 / b4 题字
_PLAN = [("s3-b0", "b0", "establish", -536), ("s3-b1", "b1", "dual_account", -633),
         ("s3-b2", "b2", "hold", -629), ("s3-b3", "b3", "hold", -526),
         ("s3-b4", "b4", "hold", -513)]
pb2bid = {p[0]: p[1] for p in _PLAN}
_VALID = {"establish", "dual_account", "hold"}


def build():
    net = json.loads(_NET.read_text())
    vo_by, onscreen_bid = {}, {}
    for b in net["beats"]:
        pb = b.get("parent_beat") or b["beat_id"]
        for s in b["sentences"]:
            if s.get("presentation") == "onscreen":
                q = s.get("quote")
                onscreen_bid[re.match(r"b\d+", s["sid"]).group()] = (
                    (q["text"] if isinstance(q, dict) else q[0]["text"]) if q else s["text"])
            else:
                vo_by.setdefault(pb, []).append(s["text"])
    beats, facts = [], []
    for i, (pb, bid, intent, date) in enumerate(_PLAN):
        vo = "".join(vo_by.get(pb, []))
        beats.append(NarrationBeat(beat_id=bid, order=i, visual_intent=intent, est_vo_seconds=max(3, round(len(vo) / 5)), vo_text=vo, fact_ref=f"vf_{bid}"))
        facts.append(VisualFact(beat_id=bid, date=date, scope="晋国(六卿时)", forces=["jin"], persons=[], markers=_MARKERS_OF.get(bid, []), evidence_tier="E1", confirmed_by="左传/史记(N0)"))
    duals = [DualAccountFact(beat_id="b1", conflict_ku_ref="cf:shangjun-jiangshuai-guishu", dimension="上军主帅归属", presentation_hint="S12 双半幅对勘",
             accounts=[Account(source_display="《左传》", summary="狐偃让于狐毛、狐毛为上军主帅"),
                       Account(source_display="《史记》", summary="狐偃径为上军主帅、未见让位")])]
    onscreen = {b: q for b, q in onscreen_bid.items() if b in {p[1] for p in _PLAN}}
    return beats, facts, duals, onscreen, {}


_MARKERS_OF = {"b0": ["绛"], "b1": ["被庐", "宋"], "b2": ["清原"], "b3": ["绛"]}


def main():
    beats, facts, duals, onscreen, _ = build()
    print(f"{EPISODE.episode_id}: {len(beats)} 拍 | S12 {[d.beat_id for d in duals]} | S13 onscreen {list(onscreen)}")
    for b in beats:
        tag = " S12" if b.beat_id in {d.beat_id for d in duals} else (" S13" if b.beat_id in onscreen else "")
        print(f"  {b.beat_id} [{b.visual_intent}]{tag} VO{b.est_vo_seconds}s «{b.vo_text[:24]}…»")


if __name__ == "__main__":
    main()
