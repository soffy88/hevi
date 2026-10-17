#!/usr/bin/env python3
"""G0 Task-1: 手绘两张 SVG 地图 (P0 精度)

ms_hua_453bc       — 453BC 周威烈王 23 年：晋完整版图 + 预置裂线层
ms_hua_453bc_split — 晋位换成韩赵魏三色块，其余底图完全相同

输出到 output/g0_sanjia_fenjin/maps/
工时记录写入 maps/timing.json
"""

from __future__ import annotations
import json
import time
from pathlib import Path

OUT = Path("output/g0_sanjia_fenjin/maps")
OUT.mkdir(parents=True, exist_ok=True)

# ─── 历史地理说明 ──────────────────────────────────────────────────────────
# 453BC 三家灭智伯之年，仍在晋国旗帜下。正式天子封侯在 403BC。
# 本图取 453BC 时点：晋国基本占据山西高原+河南北部，周天子在洛邑，
# 秦在关中，楚在江汉，燕在幽燕，齐在山东，郑韩（韩未独立）在中原南。
# 地图为示意性，不追求 GIS 级精度，仅满足 P0 要求。
#
# 坐标系: SVG 1200×800，东经 100–125，北纬 28–45 线性映射
# lon_min=100, lon_max=125 → x:  0–1200
# lat_min=28,  lat_max=45  → y: 800–0  (纬度高→y小)

W, H = 1200, 800
LON_MIN, LON_MAX = 100.0, 125.0
LAT_MIN, LAT_MAX = 28.0, 45.0


def ll(lon: float, lat: float) -> tuple[float, float]:
    x = (lon - LON_MIN) / (LON_MAX - LON_MIN) * W
    y = H - (lat - LAT_MIN) / (LAT_MAX - LAT_MIN) * H
    return round(x, 1), round(y, 1)


def pt(lon: float, lat: float) -> str:
    x, y = ll(lon, lat)
    return f"{x},{y}"


def pts(*pairs) -> str:
    return " ".join(pt(lo, la) for lo, la in pairs)


# ─── 势力多边形 ────────────────────────────────────────────────────────────
# 各势力用近似多边形描述占据区域（简化版，P0精度）

# 周（洛邑一带，极小）
ZHOU = [
    (112.0, 34.8), (113.2, 34.8), (113.2, 35.4), (112.0, 35.4),
]

# 晋（山西高原 + 河南北部，453BC 完整版）
JIN = [
    (110.0, 35.0), (114.5, 35.0), (114.5, 38.0), (113.0, 39.5),
    (111.5, 39.8), (110.0, 39.0), (109.0, 37.5), (109.5, 35.8),
]

# 韩（晋分裂后，今豫中/豫西一带）
HAN = [
    (110.0, 35.0), (113.2, 35.0), (113.2, 36.8), (111.5, 37.2), (110.5, 36.5),
]

# 赵（晋分裂后，今晋北+冀南）
ZHAO = [
    (112.5, 37.0), (114.5, 36.5), (114.5, 38.0), (113.0, 39.5),
    (111.5, 39.8), (110.0, 39.0), (111.0, 37.8),
]

# 魏（晋分裂后，今晋南+豫北）
WEI = [
    (110.0, 35.0), (110.5, 36.5), (111.5, 37.2), (112.5, 37.0),
    (111.0, 37.8), (110.0, 39.0), (109.0, 37.5), (109.5, 35.8),
]
# 注: 三家之和 = 晋原版图（近似拼合，允许 P0 误差）

# 秦（关中）
QIN = [
    (106.5, 33.5), (109.5, 33.5), (109.5, 35.8), (107.5, 36.5),
    (106.5, 35.0),
]

# 楚（江汉+淮河）
CHU = [
    (107.0, 29.5), (116.5, 29.5), (116.5, 33.5), (112.0, 34.5),
    (109.0, 34.0), (107.0, 32.5),
]

# 齐（山东）
QI = [
    (114.5, 35.0), (120.5, 35.0), (122.0, 37.5), (120.0, 38.5),
    (116.0, 38.0), (114.5, 37.5),
]

# 燕（幽燕）
YAN = [
    (114.0, 38.5), (121.0, 39.0), (122.0, 42.0), (118.0, 43.0),
    (115.0, 41.5), (113.0, 40.5),
]

# 郑（今郑州一带，已衰微）
ZHENG = [
    (113.2, 34.5), (114.5, 34.5), (114.5, 35.0), (113.2, 35.0),
]

# 宋（豫东）
SONG = [
    (114.5, 33.5), (117.0, 33.5), (117.0, 35.0), (114.5, 35.0),
]

# 鲁（山东南）
LU = [
    (116.5, 34.5), (120.5, 34.5), (120.5, 36.5), (116.5, 36.5),
]


def poly(pts_list, fill, stroke="#2b2014", sw=1.2, opacity=0.82) -> str:
    p = " ".join(pt(lo, la) for lo, la in pts_list)
    return (f'<polygon points="{p}" fill="{fill}" fill-opacity="{opacity}" '
            f'stroke="{stroke}" stroke-width="{sw}"/>')


# ─── 河流路径（黄河、长江简化） ────────────────────────────────────────────
# 黄河：从宁夏—陕—晋—豫—齐
HUANG_HE = [
    (105.5, 36.5), (107.0, 37.5), (108.5, 38.5), (110.5, 39.0),
    (111.5, 39.3), (113.5, 38.5), (114.0, 37.5), (114.8, 36.8),
    (115.5, 35.8), (115.8, 35.0), (117.0, 35.0), (118.5, 35.8),
    (120.0, 36.5),
]

# 长江：从宜宾—荆州—武汉—南京
CHANG_JIANG = [
    (104.0, 29.0), (106.5, 29.8), (109.0, 30.5), (111.5, 30.8),
    (114.5, 30.5), (116.5, 30.8), (117.5, 31.5), (118.5, 31.8),
    (120.5, 31.5),
]


def river(pts_list, color="#3b82c4", sw=2.5) -> str:
    d = "M " + " L ".join(pt(lo, la) for lo, la in pts_list)
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}" stroke-linecap="round"/>'


# ─── 海岸线（中国东海岸简化折线） ────────────────────────────────────────
COAST = [
    (121.0, 40.0), (121.5, 39.5), (121.5, 38.5), (120.5, 37.5),
    (120.0, 36.5), (119.5, 35.5), (119.0, 34.5), (120.5, 33.5),
    (121.5, 31.5), (122.0, 31.0), (121.5, 29.5), (122.0, 28.5),
]

# ─── 晋国内部裂线（预置，453BC 时点就藏在底下） ─────────────────────────
# 三条裂线预示韩赵魏分界
FISSURE_HAN_WEI = [  # 韩/魏分界（偏南）
    (110.0, 36.5), (111.5, 36.8), (112.5, 37.0),
]
FISSURE_WEI_ZHAO = [  # 魏/赵分界（偏北）
    (111.0, 37.8), (112.5, 37.5), (113.5, 37.2), (114.0, 36.5),
]
FISSURE_SOUTH = [  # 韩/赵东西分（简化）
    (112.5, 35.5), (113.0, 36.5), (113.2, 37.2),
]


def fissure(pts_list) -> str:
    d = "M " + " L ".join(pt(lo, la) for lo, la in pts_list)
    return (f'<path d="{d}" fill="none" stroke="#8b0000" stroke-width="1.8" '
            f'stroke-dasharray="6,4" opacity="0.55"/>')


# ─── 城邑标注 ────────────────────────────────────────────────────────────
CITIES = [
    # (lon, lat, name, offset_x, offset_y)
    (112.5, 37.9, "晋阳 (赵)", 6, -6),   # 赵都（已驻）
    (113.7, 35.5, "邺", 6, -6),
    (110.5, 35.2, "绛", 6, 8),            # 晋都
    (112.0, 35.0, "洛邑 (周)", 6, -8),
    (108.5, 34.2, "雍 (秦)", 6, -8),
    (112.5, 30.6, "郢 (楚)", 8, -8),
    (118.5, 36.5, "临淄 (齐)", 8, -8),
    (117.5, 40.5, "蓟 (燕)", 8, -8),
]


def city_mark(lon, lat, name, dx=6, dy=-8) -> str:
    x, y = ll(lon, lat)
    return (f'<circle cx="{x}" cy="{y}" r="4" fill="#e8d5a3" stroke="#2b2014" stroke-width="1"/>'
            f'<text x="{x+dx}" y="{y+dy}" font-size="10" fill="#1a0f00" '
            f'font-family="serif" font-style="italic">{name}</text>')


# ─── SVG 基础层生成 ─────────────────────────────────────────────────────────

def base_layers(jin_polygon_svg: str, jin_label: str | None = "晋") -> str:
    """生成地图主体 SVG 内容（不含 XML 头和 <svg> 标签）"""
    layers = []

    # 背景
    layers.append(f'<rect width="{W}" height="{H}" fill="#e8e0cc"/>')

    # 势力色块 — 外围势力先画
    layers.append(poly(YAN,   "#7ca6d8"))  # 燕：蓝灰
    layers.append(poly(QI,    "#8ab87a"))  # 齐：绿
    layers.append(poly(CHU,   "#c4844a"))  # 楚：橙棕
    layers.append(poly(QIN,   "#a07850"))  # 秦：赭石
    layers.append(poly(ZHENG, "#c8b080"))  # 郑：米黄
    layers.append(poly(SONG,  "#b8a060"))  # 宋：黄
    layers.append(poly(LU,    "#90b870"))  # 鲁：草绿
    layers.append(poly(ZHOU,  "#d0c0a0", sw=0.8, opacity=0.6))  # 周：极淡

    # 晋（或韩赵魏）— 最后画在外围之上
    layers.append(jin_polygon_svg)

    # 海岸线
    coast_d = "M " + " L ".join(pt(lo, la) for lo, la in COAST)
    layers.append(f'<path d="{coast_d}" fill="none" stroke="#3b82c4" stroke-width="2.5" opacity="0.7"/>')

    # 河流
    layers.append(river(HUANG_HE, "#4a90d9", sw=2.8))
    layers.append(river(CHANG_JIANG, "#4a90d9", sw=2.5))

    # 标注：河名
    hx, hy = ll(114.0, 36.2)
    layers.append(f'<text x="{hx}" y="{hy}" font-size="11" fill="#2456a0" font-family="serif" '
                  f'transform="rotate(-15,{hx},{hy})">黄 河</text>')
    cjx, cjy = ll(114.5, 30.8)
    layers.append(f'<text x="{cjx}" y="{cjy}" font-size="11" fill="#2456a0" font-family="serif" '
                  f'transform="rotate(-5,{cjx},{cjy})">长 江</text>')

    # 势力名称标注
    def label(lon, lat, name, fs=13, color="#1a0f00", bold=False):
        x, y = ll(lon, lat)
        fw = "bold" if bold else "normal"
        return (f'<text x="{x}" y="{y}" font-size="{fs}" fill="{color}" '
                f'font-family="serif" font-weight="{fw}" text-anchor="middle">{name}</text>')

    layers.append(label(119.0, 39.5, "燕", 15))
    layers.append(label(118.0, 36.0, "齐", 15))
    layers.append(label(111.0, 31.5, "楚", 16))
    layers.append(label(107.5, 34.5, "秦", 15))
    layers.append(label(116.0, 34.0, "宋", 12))
    layers.append(label(118.0, 35.5, "鲁", 12))
    layers.append(label(113.5, 35.0, "郑", 11))
    layers.append(label(112.3, 34.9, "周 (洛邑)", 10, "#555"))

    if jin_label:
        layers.append(label(111.5, 37.5, jin_label, 18, "#4a0000", bold=True))

    # 城邑
    for lo, la, name, dx, dy in CITIES:
        layers.append(city_mark(lo, la, name, dx, dy))

    # 图例
    legend_x, legend_y = 20, 20
    legend_items = [
        ("#7ca6d8", "燕"), ("#8ab87a", "齐"), ("#c4844a", "楚"),
        ("#a07850", "秦"), ("#90b870", "鲁/宋"),
    ]
    layers.append(f'<rect x="{legend_x-4}" y="{legend_y-4}" width="130" height="{len(legend_items)*20+8}" '
                  f'fill="white" fill-opacity="0.7" rx="4"/>')
    for i, (col, nm) in enumerate(legend_items):
        ry = legend_y + i * 20
        layers.append(f'<rect x="{legend_x}" y="{ry}" width="14" height="14" fill="{col}" rx="2"/>')
        layers.append(f'<text x="{legend_x+18}" y="{ry+11}" font-size="11" fill="#1a0f00" font-family="serif">{nm}</text>')

    return "\n  ".join(layers)


def make_svg(content: str, title: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <title>{title}</title>
  <desc>G0 三家分晋 — P0精度历史地图 © hevi.tongjian sandbox</desc>
  {content}
</svg>"""


# ─── 地图 1: ms_hua_453bc (晋整块 + 裂线预置层) ───────────────────────────
def build_ms_hua_453bc() -> str:
    jin_svg = poly(JIN, "#7a3030", sw=2.0, opacity=0.85)  # 晋：深红
    # 追加裂线层（隐藏预置，opacity 低）
    fissures = "\n  ".join([
        fissure(FISSURE_HAN_WEI),
        fissure(FISSURE_WEI_ZHAO),
        fissure(FISSURE_SOUTH),
    ])
    jin_block = jin_svg + "\n  <!-- fissure_layer: 预置裂线，453BC 隐含但未爆发 -->\n  " + fissures

    # 晋国专用图例
    jin_legend_x, jin_legend_y = W - 150, 20
    jin_legend = (
        f'<rect x="{jin_legend_x-4}" y="{jin_legend_y-4}" width="145" height="48" '
        f'fill="white" fill-opacity="0.75" rx="4"/>'
        f'<rect x="{jin_legend_x}" y="{jin_legend_y}" width="14" height="14" fill="#7a3030" rx="2"/>'
        f'<text x="{jin_legend_x+18}" y="{jin_legend_y+11}" font-size="11" fill="#1a0f00" font-family="serif">晋国</text>'
        f'<line x1="{jin_legend_x}" y1="{jin_legend_y+26}" x2="{jin_legend_x+40}" y2="{jin_legend_y+26}" '
        f'stroke="#8b0000" stroke-width="1.8" stroke-dasharray="5,3"/>'
        f'<text x="{jin_legend_x+44}" y="{jin_legend_y+30}" font-size="10" fill="#8b0000" font-family="serif">预置裂线</text>'
    )

    title_svg = (
        f'<text x="{W//2}" y="{H-28}" font-size="15" fill="#1a0f00" font-family="serif" '
        f'text-anchor="middle" font-weight="bold">453BC · 韩赵魏灭智伯 — 晋国完整版图（裂而未分）</text>'
    )

    content = base_layers(jin_block, "晋") + "\n  " + jin_legend + "\n  " + title_svg
    return make_svg(content, "ms_hua_453bc — 453BC晋国全图含预置裂线")


# ─── 地图 2: ms_hua_453bc_split (韩赵魏三块，底图同) ──────────────────────
def build_ms_hua_453bc_split() -> str:
    han_svg = poly(HAN,  "#e06040", sw=1.5, opacity=0.85)  # 韩：砖红
    zhao_svg = poly(ZHAO, "#5070c0", sw=1.5, opacity=0.85)  # 赵：蓝
    wei_svg  = poly(WEI,  "#4a8050", sw=1.5, opacity=0.85)  # 魏：绿

    # 韩赵魏分界线（非虚线，实线代表已成事实）
    def border(pts_list) -> str:
        d = "M " + " L ".join(pt(lo, la) for lo, la in pts_list)
        return f'<path d="{d}" fill="none" stroke="#1a0f00" stroke-width="2.0" opacity="0.8"/>'

    borders = "\n  ".join([
        border(FISSURE_HAN_WEI),
        border(FISSURE_WEI_ZHAO),
        border(FISSURE_SOUTH),
    ])

    three_blocks = han_svg + "\n  " + zhao_svg + "\n  " + wei_svg + "\n  " + borders

    # 三家专用标注（覆盖"晋"的位置）
    def label3(lon, lat, name, color):
        x, y = ll(lon, lat)
        return (f'<text x="{x}" y="{y}" font-size="15" fill="{color}" '
                f'font-family="serif" font-weight="bold" text-anchor="middle">{name}</text>')

    labels3 = "\n  ".join([
        label3(111.5, 36.0, "韩", "#8b2000"),
        label3(112.8, 38.5, "赵", "#1a3080"),
        label3(109.8, 37.5, "魏", "#1a5030"),
    ])

    # 三家图例
    legend_x, legend_y = W - 150, 20
    legend = (
        f'<rect x="{legend_x-4}" y="{legend_y-4}" width="145" height="72" '
        f'fill="white" fill-opacity="0.75" rx="4"/>'
        f'<rect x="{legend_x}" y="{legend_y}" width="14" height="14" fill="#e06040" rx="2"/>'
        f'<text x="{legend_x+18}" y="{legend_y+11}" font-size="11" fill="#1a0f00" font-family="serif">韩</text>'
        f'<rect x="{legend_x}" y="{legend_y+20}" width="14" height="14" fill="#5070c0" rx="2"/>'
        f'<text x="{legend_x+18}" y="{legend_y+31}" font-size="11" fill="#1a0f00" font-family="serif">赵</text>'
        f'<rect x="{legend_x}" y="{legend_y+40}" width="14" height="14" fill="#4a8050" rx="2"/>'
        f'<text x="{legend_x+18}" y="{legend_y+51}" font-size="11" fill="#1a0f00" font-family="serif">魏</text>'
    )

    title_svg = (
        f'<text x="{W//2}" y="{H-28}" font-size="15" fill="#1a0f00" font-family="serif" '
        f'text-anchor="middle" font-weight="bold">453BC → 三家分晋（韩·赵·魏 取代晋国版图）</text>'
    )

    content = base_layers(three_blocks, jin_label=None) + "\n  " + labels3 + "\n  " + legend + "\n  " + title_svg
    return make_svg(content, "ms_hua_453bc_split — 三家分晋版图")


# ─── 主逻辑 ─────────────────────────────────────────────────────────────────

def main():
    timing = {}

    t0 = time.perf_counter()
    svg1 = build_ms_hua_453bc()
    t1 = time.perf_counter()
    p1 = OUT / "ms_hua_453bc.svg"
    p1.write_text(svg1, encoding="utf-8")
    timing["ms_hua_453bc_seconds"] = round(t1 - t0, 3)
    print(f"✓ {p1}  ({timing['ms_hua_453bc_seconds']:.2f}s)")

    t2 = time.perf_counter()
    svg2 = build_ms_hua_453bc_split()
    t3 = time.perf_counter()
    p2 = OUT / "ms_hua_453bc_split.svg"
    p2.write_text(svg2, encoding="utf-8")
    timing["ms_hua_453bc_split_seconds"] = round(t3 - t2, 3)
    print(f"✓ {p2}  ({timing['ms_hua_453bc_split_seconds']:.2f}s)")

    timing["total_seconds"] = round(t3 - t0, 3)
    timing["note"] = "G0 Q5 工时参考：手绘 SVG 两张"
    tf = OUT / "timing.json"
    tf.write_text(json.dumps(timing, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"✓ 工时记录: {tf}")
    print(f"\n总工时: {timing['total_seconds']:.3f}s")


if __name__ == "__main__":
    main()
