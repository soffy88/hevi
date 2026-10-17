"""s2 骊姬之乱 · N1 节拍切分 + N2 事实装配(从 N0 9/9 净稿投影)。

N0 閘⓪ 待送(GATE0-N0-s2)。净稿 output/n0_s2/s1_full_clean_script.json(6 叙事拍)聚合;
三 cf → S12 双半幅(sanzi-fenju/liji-zenci/erzi-chuben);counterpoint=weixuangong-goujizi。
b2 onscreen 史记谮词折入其 cf 的 S12 右 panel(谮词对勘)。VisualFact 逐字投影不自造。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from hevi.tongjian.explainer_contract import (
    Account,
    DualAccountFact,
    EpisodePlan,
    NarrationBeat,
    VisualFact,
)

# S2_NET 环境变量可覆写净稿路径(白话样片对比用，默认旧 s2 净稿)。
_NET = Path(os.environ.get("S2_NET", "output/n0_s2/s1_full_clean_script.json"))

EPISODE = EpisodePlan(
    episode_id="ep_jin_decline_s2",
    dynasty_era="春秋早期(前696–前654)",
    narrative_frame="骊姬之乱:献公嬖宠乱嫡、谮杀申生、逐重耳夷吾——晋无公族屏藩、卿族坐大之远因。",
    narration_script_ref=str(_NET),
)

# 净稿 plan 拍 → (叙事拍序, visual_intent, date)。cf→S12 由净稿 conflict_callouts 驱动。
_PLAN = [
    ("s2-b0", "b0", "establish", -666),  # throughline 设立 + 晋绛/三子分封地图
    ("s2-b1", "b1", "dual_account", -666),  # S12 sanzi-fenju(三子分居缘起)
    ("s2-b2", "b2", "dual_account", -656),  # S12 liji-zenci(谮词内容;onscreen 史记谮词=右panel)
    ("s2-b3", "b3", "dual_account", -655),  # S12 erzi-chuben(出奔缘由)
    ("s2-b4", "b4", "hold", -656),  # throughline 应验(士蒍歌 狐裘尨茸一国三公)
    ("s2-b5", "b5", "hold", -696),  # counterpoint 卫宣公朝嫡庶相残
]
pb2bid = {p[0]: p[1] for p in _PLAN}
_VALID = {"establish", "dual_account", "hold", "character", "route", "battle", "split_merge"}


def build():
    net = json.loads(_NET.read_text())
    vo_by, onscreen_bid, cf_by = {}, {}, {}
    import re

    for b in net["beats"]:
        pb = b.get("parent_beat") or b["beat_id"]
        for s in b["sentences"]:
            # 按 sid 编码的 plan 显示拍路由(sid 前缀 bN → 显示拍 s2-bN)——W 可能把某 plan 拍的句
            # 并进别的 beat 容器(如谮词句 sid=b2-1 落在 beat s2-b1),按 sid 归位才对齐 _PLAN。
            bid = re.match(r"b\d+", s["sid"]).group()
            sid_pb = "s2-" + bid
            if s.get("presentation") == "onscreen":
                q = s.get("quote")
                qtext = (q["text"] if isinstance(q, dict) else q[0]["text"]) if q else s["text"]
                onscreen_bid[bid] = qtext
                # 白话优先:onscreen 句 text 若是白话转述(不含引文本体)→ 白话入该显示拍 vo 口播;
                # 文言风(text 即引文本体、含 quote)→ 不入 vo(文言只呈现不口播)。
                if qtext not in s["text"]:
                    vo_by.setdefault(sid_pb, []).append(s["text"])
            else:
                vo_by.setdefault(sid_pb, []).append(s["text"])
            for cf in s.get("conflict_callouts") or []:
                cf_by.setdefault(sid_pb, set()).add(cf)

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
                scope="晋国(献公时)",
                forces=["jin"],
                persons=_PERSONS_OF.get(bid, []),
                markers=_MARKERS_OF.get(bid, []),
                evidence_tier="E1",
                confirmed_by="左传/史记(N0 9/9 双溯源过)",
            )
        )
    # 三 cf → S12 双半幅(两说并陈,清欠账);内容取 ADJUDICATION-s2-liji 的两源之说
    duals = [
        DualAccountFact(
            beat_id="b1",
            conflict_ku_ref="cf:sanzi-fenju-yuanqi",
            dimension="三子分居缘起",
            presentation_hint="S12 双半幅对勘",
            accounts=[
                Account(source_display="《左传》", summary="骊姬贿二五进言、分置三公子"),
                Account(source_display="《史记》", summary="献公以边防理由径出、分置三公子"),
            ],
        ),
        DualAccountFact(
            beat_id="b2",
            conflict_ku_ref="cf:liji-zenci-neirong",
            dimension="谮词内容",
            presentation_hint="S12 双半幅对勘",
            accounts=[
                Account(source_display="《左传》", summary="谮辞极简『贼由大子』"),
                Account(source_display="《史记》", summary="详载多层谮语+废立铺垫"),
            ],
        ),
        DualAccountFact(
            beat_id="b3",
            conflict_ku_ref="cf:erzi-chuben-yuanyou",
            dimension="出奔缘由",
            presentation_hint="S12 双半幅对勘",
            accounts=[
                Account(source_display="《左传》", summary="骊姬『皆知之』直接触发出奔"),
                Account(source_display="《史记》", summary="多一层告发→骊姬反谮环节"),
            ],
        ),
    ]
    onscreen = {b: q for b, q in onscreen_bid.items() if b in {p[1] for p in _PLAN}}
    cf_of = {pb2bid[pb]: sorted(v) for pb, v in cf_by.items() if pb in pb2bid}
    return beats, facts, duals, onscreen, cf_of


_PERSONS_OF = {"b1": ["jin-xiangong"]}
_MARKERS_OF = {"b0": ["绛", "蒲", "屈"], "b2": ["曲沃"], "b3": ["梁", "翟"]}


def main():
    beats, facts, duals, onscreen, cf_of = build()
    print(f"EpisodePlan: {EPISODE.episode_id} / {EPISODE.dynasty_era}")
    print(f"N1 节拍: {len(beats)} 叙事拍, VO 总估 {sum(b.est_vo_seconds for b in beats)}s")
    assert {b.beat_id for b in beats} == {f.beat_id for f in facts}
    print(f"S12 三对勘: {[d.beat_id + ':' + d.dimension for d in duals]}")
    print(f"onscreen(折入S12): {list(onscreen)}  cf归拍: {cf_of}")
    for b in beats:
        s12 = " S12" if b.beat_id in {d.beat_id for d in duals} else ""
        print(f"  {b.beat_id} [{b.visual_intent}]{s12}  VO{b.est_vo_seconds}s «{b.vo_text[:26]}…»")


if __name__ == "__main__":
    main()
