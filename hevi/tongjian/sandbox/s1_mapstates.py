"""s1 曲沃代翼 MapState —— 晋国内部地理(临汾盆地:翼/曲沃/汾隰/陘庭/随)。

两态(§3 单态快照,S3 双态在 ShotSpec 层组合):
  ms_yi_independent 翼独立态(大宗翼 + 小宗曲沃,裂而未分预置线)——b0–b6 底图
  ms_quwo_absorbed  曲沃吞并态(曲沃并翼,大宗灭)——b7 撕裂/合并目标态

色一律注册表(force_colors);翼=赭红(大宗正统)/曲沃=青灰蓝(小宗);周=王畿淡米(context)。
郑不入多边形(郑人助战=route 细节、郑伯克段=counterpoint side-panel);规避 zhou/zheng tier1 撞色。
零 provider、零成本;blocking_clashes 须空(§6.2b)。
"""

from __future__ import annotations

from pathlib import Path

from hevi.tongjian.map_state import (
    CityMark,
    FissureLine,
    ForcePolygon,
    MapState,
    Projection,
    River,
)

OUT = Path("output/s1_quwo_daiyi")

# 焦点投影:缩放到晋国内部临汾盆地 + 周王畿(默认全国投影下 翼/曲沃 仅豆点)
_PROJ = Projection(lon_min=109.0, lon_max=114.5, lat_min=33.0, lat_max=37.5)

# ── 临汾盆地坐标(lon,lat) ──
# 翼(晋大宗,翼城 111.7,35.7 一带,偏东北)
YI = [(111.45, 35.42), (112.35, 35.5), (112.55, 36.25), (111.9, 36.55), (111.3, 36.1)]
# 曲沃(小宗,曲沃 111.5,35.55 一带,偏西南,与翼共 (111.45,35.42)-(111.3,36.1) 邻边)
QUWO = [(110.6, 35.0), (111.45, 35.42), (111.3, 36.1), (110.55, 35.9), (110.35, 35.3)]
# 曲沃吞并态:曲沃扩张覆盖翼故地(大宗灭,前678)
QUWO_BIG = [
    (110.6, 35.0),
    (112.35, 35.5),
    (112.55, 36.25),
    (111.9, 36.55),
    (110.55, 35.9),
    (110.35, 35.3),
]
# 周王畿(context,东南;命虢仲立缗/釐王册命的天子方)
ZHOU = [(112.2, 34.0), (113.6, 34.1), (113.5, 35.05), (112.1, 34.95)]

# 汾水(临汾盆地 N→S,下游入黄河);黄河(西/南界)
FEN = River(
    name="汾水", width=2.4, points=[(111.9, 36.6), (111.4, 35.8), (110.9, 35.2), (110.4, 34.6)]
)
HUANGHE = River(
    name="黄河", width=2.8, points=[(110.4, 34.6), (110.2, 35.4), (110.0, 36.2), (110.3, 37.0)]
)

# 城邑(名后期 R7 合成;force_id 决定归属色点)
CITIES = [
    CityMark(name="翼", lon=111.72, lat=35.72, force_id="yi"),
    CityMark(name="曲沃", lon=111.42, lat=35.5, force_id="quwo"),
    CityMark(name="陘庭", lon=111.82, lat=35.95, force_id="yi"),  # 武公次于陘庭
    CityMark(name="汾隰", lon=110.75, lat=35.15, force_id=None),  # 逐翼侯于汾隰(汾水下游隰地)
    CityMark(name="随", lon=110.32, lat=35.7, force_id=None),  # 翼侯奔随(西境避难)
]

# 翼/曲沃邻边预置裂线(裂而未分:大宗小宗同源,S3 沿此撕开)
_PRESET_FISSURE = FissureLine(
    between=("yi", "quwo"), preset=True, points=[(111.45, 35.42), (111.38, 35.76), (111.3, 36.1)]
)


def ms_yi_independent() -> MapState:
    return MapState(
        state_id="jin_quwo_daiyi_yi_independent",
        projection=_PROJ,
        era_label="前745–前709 翼(大宗)与曲沃(小宗)并立",
        date=-745,
        forces=[
            ForcePolygon(force_id="zhou", rings=[ZHOU]),  # 后层 context 先画
            ForcePolygon(force_id="yi", rings=[YI]),
            ForcePolygon(force_id="quwo", rings=[QUWO]),
        ],
        fissures=[_PRESET_FISSURE],
        rivers=[HUANGHE, FEN],
        cities=CITIES,
        note="b0–b6 底图:翼赭红(大宗)/曲沃青灰蓝(小宗),邻边裂而未分。",
    )


def ms_quwo_absorbed() -> MapState:
    return MapState(
        state_id="jin_quwo_daiyi_quwo_absorbed",
        projection=_PROJ,
        era_label="前678 曲沃并翼,列为诸侯",
        date=-678,
        forces=[
            ForcePolygon(force_id="zhou", rings=[ZHOU]),
            ForcePolygon(force_id="quwo", rings=[QUWO_BIG]),
        ],
        rivers=[HUANGHE, FEN],
        cities=[c for c in CITIES if c.name != "翼"]  # 翼灭,城点归曲沃
        + [CityMark(name="翼", lon=111.72, lat=35.72, force_id="quwo")],
        note="b7 撕裂/合并目标态:曲沃(青灰蓝)吞并翼故地,大宗灭。",
    )


def main():
    yi = ms_yi_independent()
    ab = ms_quwo_absorbed()
    print("翼独立态 blocking_clashes:", yi.blocking_clashes() or "无 ✓")
    print("曲沃吞并态 blocking_clashes:", ab.blocking_clashes() or "无 ✓")
    print("翼独立态 centroid_targets:", {k: v["px"] for k, v in yi.centroid_targets().items()})


if __name__ == "__main__":
    main()
