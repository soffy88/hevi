"""s3 晋作三军五军·六卿彊 MapState —— 晋文公霸业时晋国 + 城濮/御狄 context。

单态(文公时晋强):晋(jin,深红) + 秦(qin西)/齐(qi东);蒐地/城濮地走 CityMark
(被庐/清原/曹/卫/宋)。零 provider、零成本;blocking_clashes 须空(§6.2b)。
"""

from __future__ import annotations

from pathlib import Path

from hevi.tongjian.map_state import CityMark, ForcePolygon, MapState, Projection, River

OUT = Path("output/s3_liujing")
_PROJ = Projection(lon_min=108.0, lon_max=117.5, lat_min=33.0, lat_max=39.5)

JIN = [
    (110.2, 34.9),
    (113.0, 35.0),
    (113.4, 36.4),
    (112.4, 37.6),
    (111.0, 37.8),
    (109.9, 36.7),
    (109.5, 35.6),
]
QIN = [(107.5, 34.0), (109.9, 34.2), (109.5, 35.6), (108.2, 35.7), (107.5, 34.8)]
QI = [(114.6, 35.2), (117.4, 35.3), (117.2, 37.2), (115.0, 37.0), (114.4, 36.0)]

HE = River(
    name="黄河",
    width=2.8,
    points=[(110.3, 34.6), (109.9, 35.6), (109.8, 36.9), (111.5, 35.4), (114.0, 35.2)],
)
FEN = River(name="汾水", width=2.2, points=[(112.2, 37.4), (111.5, 36.2), (110.9, 35.2)])

CITIES = [
    CityMark(name="绛", lon=111.5, lat=35.9, force_id="jin"),
    CityMark(name="被庐", lon=111.2, lat=35.4, force_id="jin"),  # 蒐于被庐(作三军)
    CityMark(name="清原", lon=111.0, lat=36.3, force_id="jin"),  # 蒐于清原(作五军)
    CityMark(name="曹", lon=115.2, lat=35.0, force_id=None),  # 城濮伐曹
    CityMark(name="卫", lon=114.4, lat=35.6, force_id=None),  # 城濮伐卫
    CityMark(name="宋", lon=115.0, lat=34.4, force_id=None),  # 围宋告急
]


def ms_jin_wengong() -> MapState:
    return MapState(
        state_id="jin_liuqing_wengong",
        projection=_PROJ,
        era_label="前633–前526 晋文公霸业·军制屡扩",
        date=-633,
        forces=[
            ForcePolygon(force_id="qin", rings=[QIN]),
            ForcePolygon(force_id="jin", rings=[JIN]),
            ForcePolygon(force_id="qi", rings=[QI]),
        ],
        rivers=[HE, FEN],
        cities=CITIES,
        note="晋(深红,文公) + 秦/齐 context + 被庐/清原 蒐地 + 曹/卫/宋 城濮地。",
    )


def main():
    print("clashes:", ms_jin_wengong().blocking_clashes() or "无✓")


if __name__ == "__main__":
    main()
