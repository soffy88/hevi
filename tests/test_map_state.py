"""MapState 测试 —— SPEC §3/§4 + 色值来源纪律(色从注册表,不进 SVG 硬写)。"""

import colorsys

import numpy as np

from hevi.tongjian.force_colors import get_force_color
from hevi.tongjian.map_state import (
    ForcePolygon,
    MapState,
    Projection,
    render_map_state_png,
    render_map_state_svg,
)


def _hue_family(r, g, b):
    h, s, _v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    hd = h * 360
    if s < 0.12:
        return "gray"
    if hd < 25 or hd > 335:
        return "red"
    if 25 <= hd < 70:
        return "gold"
    if 70 <= hd < 170:
        return "green"
    return "blue"


def _tri_ms() -> MapState:
    # 一个最小三分治态(韩赵魏),坐标随意但可投影
    return MapState(
        state_id="test_split",
        era_label="test",
        date=-453,
        forces=[
            ForcePolygon(force_id="han", rings=[[(110.0, 35.0), (112.0, 35.0), (111.0, 37.0)]]),
            ForcePolygon(force_id="zhao", rings=[[(112.0, 38.0), (114.0, 38.0), (113.0, 40.0)]]),
            ForcePolygon(force_id="wei", rings=[[(108.0, 36.0), (110.0, 36.0), (109.0, 38.0)]]),
        ],
    )


def test_projection_roundtrip_and_centroid():
    p = Projection()
    x, y = p.ll(100.0, 45.0)
    assert (x, y) == (0.0, 0.0)  # 左上角 = (lon_min, lat_max)
    x, y = p.ll(125.0, 28.0)
    assert (x, y) == (1200.0, 800.0)  # 右下角
    cx, cy = p.centroid_px([(110.0, 35.0), (112.0, 35.0), (111.0, 37.0)])
    assert 0 < cx < 1200 and 0 < cy < 800


def test_render_reads_colors_from_registry_not_hardcoded():
    svg = render_map_state_svg(_tri_ms())
    # 色值来自注册表:韩/赵/魏 当前 hex 出现
    assert get_force_color("han").hex in svg
    assert get_force_color("zhao").hex in svg
    assert get_force_color("wei").hex in svg
    # G0 修正:旧的魏深绿绝不出现
    assert "#4a8050" not in svg


def test_render_labels_toggle_r7():
    ms = _tri_ms()
    with_labels = render_map_state_svg(ms, draw_labels=True)
    no_labels = render_map_state_svg(ms, draw_labels=False)
    assert "韩" in with_labels
    # R7:生产关键帧零文字 → draw_labels=False 不画势力名
    assert "韩" not in no_labels


def test_centroid_targets_expected_rgb_matches_registry():
    tgt = _tri_ms().centroid_targets()
    assert set(tgt) == {"han", "zhao", "wei"}
    assert tgt["han"]["expected_rgb"] == get_force_color("han").rgb
    assert 0.0 < tgt["han"]["frac"][0] < 1.0


def test_clean_split_map_no_clash():
    # 三分治色同屏不撞(§6.2b):无须解决的撞色
    assert _tri_ms().blocking_clashes() == []


def test_adjacency_and_dismiss_trace():
    # 邻接规则:相邻势力才 flag 撞色;非相邻色近 → dismiss 留痕(裁决 2026-07-21)
    ms = MapState(
        state_id="adj_test",
        forces=[
            # 两块同色(都取 chu 橙棕)但**远离** → 非相邻 → 应 dismiss
            ForcePolygon(force_id="chu", rings=[[(101.0, 29.0), (103.0, 29.0), (102.0, 31.0)]]),
            ForcePolygon(force_id="qin", rings=[[(122.0, 43.0), (124.0, 43.0), (123.0, 44.5)]]),
        ],
    )
    # qin/chu 色近(<60)但两块隔开半张图 → 非相邻
    assert frozenset(("qin", "chu")) not in ms.adjacency()
    trace = ms.clashes()
    assert trace and trace[0]["adjacent"] is False
    assert "dismiss" in trace[0]["verdict"]
    assert ms.blocking_clashes() == []  # 非相邻不阻塞


def test_b1a_by_construction_deterministic_backend():
    """G0-D 留证:deterministic_layers 后端下 B1a(质心呈注册色)构建期恒绿。
    对照 i2v(G0 S2/S3 把韩赵魏塌成单色红)——确定性渲染在质心采到的就是注册色族。"""
    ms = MapState(
        state_id="b1a_proof",
        forces=[
            ForcePolygon(force_id="han", rings=[[(110.5, 35.2), (113.0, 35.2), (111.7, 37.0)]]),
            ForcePolygon(force_id="zhao", rings=[[(112.6, 37.4), (114.6, 37.0), (113.3, 39.2)]]),
            ForcePolygon(force_id="wei", rings=[[(108.8, 36.0), (110.8, 36.4), (109.6, 38.2)]]),
        ],
    )
    img = np.asarray(render_map_state_png(ms, mark_battles=False).convert("RGB"), dtype=np.float64)
    expect = {"han": "red", "zhao": "blue", "wei": "gold"}
    for fid, tgt in ms.centroid_targets().items():
        cx, cy = int(tgt["px"][0]), int(tgt["px"][1])
        patch = img[cy - 5 : cy + 6, cx - 5 : cx + 6].reshape(-1, 3)
        rgb = np.median(patch, axis=0)
        assert _hue_family(*rgb) == expect[fid], f"{fid}: {rgb} 不在 {expect[fid]} 族"


def test_svg_is_wellformed_enough():
    svg = render_map_state_svg(_tri_ms())
    assert svg.startswith("<?xml")
    assert svg.count("<polygon") == 3
    assert svg.strip().endswith("</svg>")
