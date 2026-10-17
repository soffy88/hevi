"""G0-D · 453 三家分晋 MapState(用新 schema+注册表重建 g0_01 冻结坐标)。
S1 统一晋(全图铺陈对照基线)。S2/S3 split 与撕裂后续。"""

from __future__ import annotations

from pathlib import Path

from hevi.tongjian.map_anim import (
    animate_establish,
    animate_fissure_reveal,
    animate_tear,
)
from hevi.tongjian.map_state import CityMark, FissureLine, ForcePolygon, MapState, River

OUT = Path("/data/soffy/projects/hevi/output/g0d_deterministic")

# g0_01_draw_maps 冻结坐标(lon,lat)
JIN = [
    (110.0, 35.0),
    (114.5, 35.0),
    (114.5, 38.0),
    (113.0, 39.5),
    (111.5, 39.8),
    (110.0, 39.0),
    (109.0, 37.5),
    (109.5, 35.8),
]
HAN = [(110.0, 35.0), (113.2, 35.0), (113.2, 36.8), (111.5, 37.2), (110.5, 36.5)]
ZHAO = [
    (112.5, 37.0),
    (114.5, 36.5),
    (114.5, 38.0),
    (113.0, 39.5),
    (111.5, 39.8),
    (110.0, 39.0),
    (111.0, 37.8),
]
WEI = [
    (110.0, 35.0),
    (110.5, 36.5),
    (111.5, 37.2),
    (112.5, 37.0),
    (111.0, 37.8),
    (110.0, 39.0),
    (109.0, 37.5),
    (109.5, 35.8),
]
QIN = [(106.5, 33.5), (109.5, 33.5), (109.5, 35.8), (107.5, 36.5), (106.5, 35.0)]
CHU = [(107.0, 29.5), (116.5, 29.5), (116.5, 33.5), (112.0, 34.5), (109.0, 34.0), (107.0, 32.5)]
QI = [(114.5, 35.0), (120.5, 35.0), (122.0, 37.5), (120.0, 38.5), (116.0, 38.0), (114.5, 37.5)]
YAN = [(114.0, 38.5), (121.0, 39.0), (122.0, 42.0), (118.0, 43.0), (115.0, 41.5), (113.0, 40.5)]
LU = [(116.5, 34.5), (120.5, 34.5), (120.5, 36.5), (116.5, 36.5)]
SONG = [(114.5, 33.5), (117.0, 33.5), (117.0, 35.0), (114.5, 35.0)]

RIVERS = [
    River(
        name="黄河",
        width=2.8,
        points=[
            (106.0, 36.5),
            (109.0, 37.2),
            (111.0, 36.0),
            (113.0, 35.2),
            (116.0, 35.6),
            (119.0, 37.4),
        ],
    ),
    River(
        name="长江", width=2.5, points=[(107.0, 30.0), (111.0, 30.2), (115.0, 30.4), (118.0, 31.4)]
    ),
]
CITIES = [
    CityMark(name="绛", lon=111.0, lat=35.8, force_id="jin"),
    CityMark(name="临淄", lon=118.3, lat=36.8, force_id="qi"),
    CityMark(name="郢", lon=112.3, lat=30.6, force_id="chu"),
]


def _surround(front: list[ForcePolygon]) -> list[ForcePolygon]:
    """周边国(后层,先画) + 传入的中央块(前层,后画,最后滑入)。"""
    # 只保留有叙事意义的周边国;鲁/宋 tier1 小矩形去掉(廉价 + 撞色,不入焦点戏)
    back = [
        ForcePolygon(force_id="yan", rings=[YAN]),
        ForcePolygon(force_id="qi", rings=[QI]),
        ForcePolygon(force_id="chu", rings=[CHU]),
        ForcePolygon(force_id="qin", rings=[QIN]),
    ]
    return back + front


def ms_453_unified() -> MapState:
    return MapState(
        state_id="jin_453bc_unified",
        era_label="453BC 晋国完整版图(裂而未分)",
        date=-453,
        forces=_surround([ForcePolygon(force_id="jin", rings=[JIN])]),
        rivers=RIVERS,
        cities=CITIES,
        note="S1 全图铺陈基线:统一晋(深红) + 周边六国。",
    )


def ms_453_split() -> MapState:
    return MapState(
        state_id="jin_453bc_split",
        era_label="453BC 三家分晋",
        date=-453,
        forces=_surround(
            [
                ForcePolygon(force_id="han", rings=[HAN]),
                ForcePolygon(force_id="zhao", rings=[ZHAO]),
                ForcePolygon(force_id="wei", rings=[WEI]),
            ]
        ),
        fissures=[
            FissureLine(
                between=("han", "wei"),
                preset=True,
                points=[(110.0, 35.0), (110.5, 36.5), (111.5, 37.2)],
            ),
            FissureLine(
                between=("wei", "zhao"),
                preset=True,
                points=[(111.5, 37.2), (112.5, 37.0), (111.0, 37.8)],
            ),
        ],
        rivers=RIVERS,
        cities=CITIES,
        note="S3 撕裂目标态:韩红/赵蓝/魏赭黄。",
    )


def main():
    uni = ms_453_unified()
    split = ms_453_split()
    OUT.mkdir(parents=True, exist_ok=True)
    print("S1 铺陈 blocking_clashes:", uni.blocking_clashes() or "无 ✓")
    print("S3 撕裂目标 blocking_clashes:", split.blocking_clashes() or "无 ✓")
    print("S1 mp4 ->", animate_establish(uni, OUT, duration_s=4.0, fps=24))
    print("S2 mp4 ->", animate_fissure_reveal(uni, split.fissures, OUT, duration_s=4.0, fps=24))
    print("S3 mp4 ->", animate_tear(uni, split, OUT, duration_s=5.0, fps=24))


if __name__ == "__main__":
    main()
