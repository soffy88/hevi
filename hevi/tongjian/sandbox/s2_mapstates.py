"""s2 骊姬之乱 MapState —— 晋献公时晋国 + 三公子分封地 + 出奔地。

单态(献公时晋已强,灭虢虞后横跨河东):晋(jin,主区,承 s1 晋大宗深红) + 秦(qin,context 西)。
分封/出奔点走 CityMark(不建新 force 色):绛(都)/曲沃-新城(申生宗庙,缢死)/蒲(重耳封)/
屈(夷吾封)/梁(夷吾奔近秦)/翟(重耳奔北狄)/卫(counterpoint,东)。零 provider、零成本;
blocking_clashes 须空(§6.2b);jin↔qin 色距 87>60、相邻不撞。
"""

from __future__ import annotations

from pathlib import Path

from hevi.tongjian.map_state import CityMark, ForcePolygon, MapState, Projection, River

OUT = Path("output/s2_liji")

# 焦点投影:晋国核心(河东+山西中南)+ 秦 context
_PROJ = Projection(lon_min=108.5, lon_max=115.5, lat_min=33.5, lat_max=39.0)

# 晋(献公时,都绛;灭虢虞后横跨河东)
JIN = [
    (110.0, 34.8),
    (112.6, 34.9),
    (113.0, 36.2),
    (112.2, 37.4),
    (111.0, 37.6),
    (109.8, 36.6),
    (109.4, 35.6),
]
QIN = [(107.0, 34.0), (109.6, 34.2), (109.4, 35.6), (108.0, 35.6), (107.0, 34.8)]

FEN = River(
    name="汾水", width=2.4, points=[(112.0, 37.4), (111.4, 36.2), (110.8, 35.2), (110.2, 34.6)]
)
HE = River(
    name="黄河", width=2.8, points=[(110.2, 34.6), (109.8, 35.6), (109.6, 36.8), (110.0, 37.8)]
)

# 城邑(名后期 R7;force_id=None 者为出奔地/counterpoint,中性色点)
CITIES = [
    CityMark(name="绛", lon=111.5, lat=35.9, force_id="jin"),  # 晋都(献公)
    CityMark(name="曲沃", lon=111.45, lat=35.5, force_id="jin"),  # 申生宗庙/新城(缢死)
    CityMark(name="蒲", lon=110.8, lat=36.9, force_id="jin"),  # 重耳封
    CityMark(name="屈", lon=110.9, lat=36.2, force_id="jin"),  # 夷吾封
    CityMark(name="梁", lon=109.7, lat=34.9, force_id=None),  # 夷吾奔(近秦)
    CityMark(name="翟", lon=111.6, lat=38.1, force_id=None),  # 重耳奔(北狄)
    CityMark(name="卫", lon=114.6, lat=35.4, force_id=None),  # counterpoint(东)
]


def ms_jin_xiangong() -> MapState:
    return MapState(
        state_id="jin_liji_xiangong",
        projection=_PROJ,
        era_label="前666–前654 晋献公时·骊姬乱嫡",
        date=-666,
        forces=[
            ForcePolygon(force_id="qin", rings=[QIN]),
            ForcePolygon(force_id="jin", rings=[JIN]),
        ],
        rivers=[HE, FEN],
        cities=CITIES,
        note="晋(深红,献公) + 三公子分封 蒲/屈/曲沃 + 梁/翟/卫 出奔地/counterpoint。",
    )


def main():
    a = ms_jin_xiangong()
    print("晋献公态 blocking_clashes:", a.blocking_clashes() or "无 ✓")
    print("centroid_targets:", {k: v["px"] for k, v in a.centroid_targets().items()})


if __name__ == "__main__":
    main()
