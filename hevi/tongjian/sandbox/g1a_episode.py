"""G1a · 三家分晋讲解段 N1 节拍切分 + N2 事实装配(手工)。

闸⓪ 已签(2026-07-21)。VisualFact 严格按 explainer_contract(§3 逐字投影)手工装配——
字段不自造,G1b 换 KU 拉取时逐字段对拍。讲解稿见 output/g1a_sanjia_fenjin/narration_script_v0.md。
"""

from __future__ import annotations

from hevi.tongjian.explainer_contract import (
    Account,
    DualAccountFact,
    EpisodePlan,
    NarrationBeat,
    Quantity,
    VisualFact,
)

EPISODE = EpisodePlan(
    episode_id="ep_sanjia_fenjin",
    dynasty_era="春秋战国之交(前456–前403)",
    narrative_frame="智伯之亡与晋之三分:索地→围晋阳→引水灌城→韩魏倒戈→智氏灭三家分晋→册封诸侯→臣光曰。",
    narration_script_ref="output/g1a_sanjia_fenjin/narration_script_v0.md",
)

# N1 节拍(vo_text 见讲解稿;此处装 order/intent/时长/fact_ref)
_BEATS = [
    ("B01", "establish", 9, "晋国曾是中原霸主,此时大权已旁落六卿,六卿之中,智氏最强。"),
    ("B02", "character", 9, "智氏之主智伯瑶,才勇冠绝一时,却贪而不仁,五贤一不肖,缺的那一样是仁。"),
    (
        "B03",
        "expand",
        11,
        "智伯向韩康子索地,不敢不给;向魏桓子索地,也给了——任章劝将欲取之必姑与之。",
    ),
    ("B04", "character", 8, "唯独赵襄子无恤一口回绝:土地先人所留不敢弃。智伯大怒。"),
    ("B05", "route", 9, "公元前455年,智伯胁迫韩魏,三家之兵合围赵氏的晋阳城。"),
    ("B06", "battle", 12, "城坚,围两年不下。智伯生一计,决水灌城,大水漫城,悬釜而炊易子而食。"),
    (
        "B07",
        "highlight",
        12,
        "赵襄子夜遣张孟谈潜出城游说韩魏:唇亡则齿寒,智伯灭赵下一个难道不是韩魏?",
    ),
    ("B08", "battle", 10, "约定之夜,赵襄子决水反灌智伯军营,韩魏两翼夹击,智伯瑶兵败被杀,智氏尽灭。"),
    ("B09", "split_merge", 9, "智氏之地韩赵魏三家瓜分,晋国名存实亡——这一年公元前453年。"),
    ("B10", "timeline", 10, "又五十年,到前403年,周威烈王正式册封韩赵魏为诸侯,名分一破再难收拾。"),
    (
        "B11",
        "hold",
        12,
        "司马光把此事放在资治通鉴开篇:天子之职莫大于礼,礼之大者莫大于分。三家分晋坏的是天下名分。",
    ),
]
BEATS = [
    NarrationBeat(
        beat_id=b, order=i, visual_intent=vi, est_vo_seconds=s, vo_text=vo, fact_ref=f"vf_{b}"
    )
    for i, (b, vi, s, vo) in enumerate(_BEATS)
]

# N2 VisualFact 手工装配(契约形状)
FACTS = [
    VisualFact(
        beat_id="B01",
        date=-456,
        scope="晋国全域",
        forces=["jin"],
        persons=[],
        evidence_tier="E1",
        confirmed_by="通鉴·周纪一",
    ),
    VisualFact(
        beat_id="B02",
        date=-456,
        scope="智氏",
        forces=["jin"],
        persons=["zhibo"],
        evidence_tier="E1",
        confirmed_by="通鉴(智果之论,R8 归智果/司马光)",
    ),
    VisualFact(
        beat_id="B03",
        date=-455,
        scope="晋地",
        forces=["jin"],
        persons=["hankangzi", "weihuanzi", "renzhang"],
        regions=["韩地", "魏地"],
        evidence_tier="E1",
        confirmed_by="战国策·魏策(任章语)",
    ),
    VisualFact(
        beat_id="B04",
        date=-455,
        scope="赵氏",
        forces=["jin"],
        persons=["zhaoxiangzi"],
        evidence_tier="E1",
        confirmed_by="通鉴(赵襄子=无恤=毋恤,异名归一)",
    ),
    VisualFact(
        beat_id="B05",
        date=-455,
        scope="晋阳",
        forces=["jin"],
        persons=["zhibo", "hankangzi", "weihuanzi", "zhaoxiangzi"],
        routes=["三家合围晋阳"],
        markers=["晋阳"],
        evidence_tier="E1",
        confirmed_by="通鉴",
    ),
    VisualFact(
        beat_id="B06",
        date=-453,
        scope="晋阳",
        routes=["引晋水灌晋阳"],
        markers=["晋阳"],
        quantities=[Quantity(value=2, unit="年", source_display="《通鉴》载围城", ku_ref="")],
        evidence_tier="E3",
        confirmed_by="战国策(悬釜易子=惨状语,夸张,标 E3)",
    ),
    VisualFact(
        beat_id="B07",
        date=-453,
        scope="晋阳",
        persons=["zhaoxiangzi", "zhangmengtan", "hankangzi", "weihuanzi"],
        evidence_tier="E2",
        confirmed_by="通鉴(游说细节史料略异)",
    ),
    VisualFact(
        beat_id="B08",
        date=-453,
        scope="晋阳",
        markers=["倒灌智营"],
        persons=["zhaoxiangzi", "zhibo"],
        evidence_tier="E1",
        confirmed_by="通鉴/史记·赵世家",
    ),
    VisualFact(
        beat_id="B09",
        date=-453,
        scope="晋故地",
        forces=["han", "zhao", "wei"],
        quantities=[Quantity(value=3, unit="家", source_display="《史记·赵世家》载", ku_ref="")],
        evidence_tier="E1",
        confirmed_by="通鉴/史记",
    ),
    VisualFact(
        beat_id="B10",
        date=-403,
        scope="时间轴",
        markers=["456索地", "455围城", "453灭智", "403册封"],
        evidence_tier="E1",
        confirmed_by="通鉴·周纪一",
    ),
    VisualFact(
        beat_id="B11",
        date=-403,
        scope="史评",
        evidence_tier="E1",
        confirmed_by="臣光曰(R8 观点归司马光)",
    ),
]

# 对勘拍(B06 灌城之水):标记,本集不建 S12(等 F2),presentation_hint=角标并陈
DUAL_ACCOUNTS = [
    DualAccountFact(
        beat_id="B06",
        conflict_ku_ref="h-conflict:guancheng-river",
        dimension="灌城之水",
        presentation_hint="角标并陈(本集不建 S12,等 F2)",
        accounts=[
            Account(source_display="《资治通鉴》", summary="决晋水灌晋阳"),
            Account(source_display="一说(汾水)", summary="决汾水灌晋阳"),
        ],
    ),
]


def main():
    print(f"EpisodePlan: {EPISODE.episode_id} / {EPISODE.dynasty_era}")
    print(f"N1 节拍: {len(BEATS)} 拍, 总时长估 {sum(b.est_vo_seconds for b in BEATS)}s")
    assert {b.beat_id for b in BEATS} == {f.beat_id for f in FACTS}, "拍与事实不齐"
    print(f"N2 VisualFact: {len(FACTS)} 条(契约校验通过=不自造字段)")
    print(f"对勘拍: {len(DUAL_ACCOUNTS)} 处(B06 晋水/汾水,{DUAL_ACCOUNTS[0].presentation_hint})")
    # 逐拍 fact 选用摘要(闸① 审)
    for b, f in zip(BEATS, FACTS, strict=True):
        extras = []
        if f.forces:
            extras.append(f"forces={f.forces}")
        if f.persons:
            extras.append(f"persons={f.persons}")
        if f.routes:
            extras.append(f"routes={f.routes}")
        if f.markers:
            extras.append(f"markers={f.markers}")
        if f.quantities:
            extras.append(f"qty={[(q.value, q.unit, q.source_display) for q in f.quantities]}")
        print(
            f"  {b.beat_id} [{b.visual_intent}] {f.evidence_tier} date={f.date} {' '.join(extras)}"
        )


if __name__ == "__main__":
    main()
