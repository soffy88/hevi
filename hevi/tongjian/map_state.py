"""MapState —— HEVI-EXPLAINER-PIPELINE-SPEC-001 §3 数据模型 / §4 地图资产供应链 / R1 疆界确定性。

一个 MapState = 一张历史地图**单一时点快照**(势力矢量多边形 + 裂线层 + 河流 + 城邑),
按 §4.4 图层结构组织。S3(撕裂)/S4(扩张)的双态由**两个 MapState**(parent→children / msA→msB)
在 ShotSpec 层组合,MapState 自身只描述一个态。

R1:势力形状**必溯源本矢量**,模型不得发明疆界。
§6/裁决 2026-07-21:**色值不进本结构**——ForcePolygon 只记 force_id,渲染时经
`force_colors.get_force_color()` 取色。禁止把 hex 写进 MapState 或 SVG。

`render_map_state_svg()` 是确定性渲染(纯 Pillow/字符串,零 LLM 零图像模型),
产出可直接喂 keyframe 生产(N5)与坐标锚定断言(A1/B2/B3,质心坐标免费来自本矢量)。
"""

from __future__ import annotations

from PIL import Image, ImageDraw
from pydantic import BaseModel, Field

from hevi.tongjian.force_colors import check_same_screen_clash, get_force_color


class Projection(BaseModel):
    """经纬度 → SVG 线性投影(§4 坐标系)。lat 高 → y 小。"""

    lon_min: float = 100.0
    lon_max: float = 125.0
    lat_min: float = 28.0
    lat_max: float = 45.0
    svg_w: int = 1200
    svg_h: int = 800

    def ll(self, lon: float, lat: float) -> tuple[float, float]:
        x = (lon - self.lon_min) / (self.lon_max - self.lon_min) * self.svg_w
        y = self.svg_h - (lat - self.lat_min) / (self.lat_max - self.lat_min) * self.svg_h
        return round(x, 1), round(y, 1)

    def centroid_px(self, ring: list[tuple[float, float]]) -> tuple[float, float]:
        """多边形质心的 SVG 像素坐标(A1/B2/B3 断言采样点,坐标免费)。"""
        xs = [self.ll(lo, la)[0] for lo, la in ring]
        ys = [self.ll(lo, la)[1] for lo, la in ring]
        return round(sum(xs) / len(xs), 1), round(sum(ys) / len(ys), 1)


class ForcePolygon(BaseModel):
    """一个势力占据区(可多环)。**只记 force_id,不记色**——色由注册表定(§6/裁决)。"""

    force_id: str
    rings: list[list[tuple[float, float]]]  # 每环 [(lon,lat), ...]
    label_at: tuple[float, float] | None = None  # 势力名标注锚点(lon,lat);None → 用首环质心


class FissureLine(BaseModel):
    """裂线/分界(§4.4 裂线层)。preset=True 表示"裂而未分"的预置隐线(S3 沿此撕开)。"""

    between: tuple[str, str]  # (force_id_a, force_id_b) 或 ("jin","jin") 表内部预置
    points: list[tuple[float, float]]
    preset: bool = False


class River(BaseModel):
    name: str
    points: list[tuple[float, float]]
    width: float = 2.5


class CityMark(BaseModel):
    name: str
    lon: float
    lat: float
    force_id: str | None = None


class MapState(BaseModel):
    """地图单态快照。state_id 稳定(缓存键,§4.3 懒生长);date 负数=公元前。"""

    state_id: str
    era_label: str = ""
    date: int = 0  # 公元纪年,负=BC
    projection: Projection = Field(default_factory=Projection)
    forces: list[ForcePolygon] = Field(default_factory=list)
    fissures: list[FissureLine] = Field(default_factory=list)
    rivers: list[River] = Field(default_factory=list)
    cities: list[CityMark] = Field(default_factory=list)
    note: str = ""

    def on_screen_force_ids(self) -> list[str]:
        return [f.force_id for f in self.forces]

    def adjacency(self, threshold_deg: float = 1.0) -> set[frozenset[str]]:
        """邻接图(§6.2b 规则化):两势力多边形最小顶点距 < threshold_deg → 相邻。
        重叠多边形顶点距≈0 也算相邻。确定性,由矢量几何决定,不靠人判。"""
        verts = {f.force_id: [pt for ring in f.rings for pt in ring] for f in self.forces}
        adj: set[frozenset[str]] = set()
        fids = list(verts)
        for i in range(len(fids)):
            for j in range(i + 1, len(fids)):
                a, b = fids[i], fids[j]
                mind = min(
                    ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
                    for ax, ay in verts[a]
                    for bx, by in verts[b]
                )
                if mind < threshold_deg:
                    adj.add(frozenset((a, b)))
        return adj

    def clashes(self, min_dist: float = 60.0) -> list[dict]:
        """§6.2b 同屏不撞自检 + **邻接复判留痕**(裁决 2026-07-21:非相邻可接受升为规则)。
        返回每个"色近"对的判词:相邻→flag(真撞色须解决);非相邻→dismiss(可接受,留痕不隐藏)。"""
        adj = self.adjacency()
        out = []
        for a, b, d in check_same_screen_clash(self.on_screen_force_ids(), min_dist=min_dist):
            is_adj = frozenset((a, b)) in adj
            out.append(
                {
                    "pair": (a, b),
                    "color_dist": d,
                    "adjacent": is_adj,
                    "verdict": "flag" if is_adj else "dismiss(非相邻,可接受)",
                }
            )
        return out

    def blocking_clashes(self, min_dist: float = 60.0) -> list[dict]:
        """仅须解决的撞色(色近 且 相邻)。空 = §6.2b 通过。"""
        return [c for c in self.clashes(min_dist=min_dist) if c["adjacent"]]

    def centroid_targets(self) -> dict[str, dict]:
        """给 A1/B2/B3 坐标锚定断言:{force_id: {px, expected_rgb, frac}}。
        质心像素与预期注册色都由本矢量+注册表确定,断言零额外成本。"""
        out = {}
        for fp in self.forces:
            cx, cy = self.projection.centroid_px(fp.rings[0])
            fc = get_force_color(fp.force_id)
            out[fp.force_id] = {
                "px": (cx, cy),
                "frac": (
                    round(cx / self.projection.svg_w, 4),
                    round(cy / self.projection.svg_h, 4),
                ),
                "expected_rgb": fc.rgb,
                "name": fc.name,
            }
        return out


# ─── 确定性 SVG 渲染(色从注册表取) ─────────────────────────────────────────


def _poly_svg(proj: Projection, rings, fill_hex, sw=1.2, opacity=0.82) -> str:
    parts = []
    for ring in rings:
        pts = " ".join(f"{proj.ll(lo, la)[0]},{proj.ll(lo, la)[1]}" for lo, la in ring)
        parts.append(
            f'<polygon points="{pts}" fill="{fill_hex}" fill-opacity="{opacity}" '
            f'stroke="#2b2014" stroke-width="{sw}"/>'
        )
    return "\n  ".join(parts)


def _path_svg(proj: Projection, points, color, sw, dash=None) -> str:
    d = "M " + " L ".join(f"{proj.ll(lo, la)[0]},{proj.ll(lo, la)[1]}" for lo, la in points)
    da = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}"{da} opacity="0.8"/>'


def render_map_state_svg(ms: MapState, *, draw_labels: bool = True) -> str:
    """MapState → SVG 字符串(确定性)。色一律 get_force_color 取,不手写 hex。
    R7:势力名/城邑名后期合成——draw_labels 仅供内部校对图,生产关键帧渲染传 False。"""
    proj = ms.projection
    layers: list[str] = [f'<rect width="{proj.svg_w}" height="{proj.svg_h}" fill="#e8e0cc"/>']

    # 势力色块(色从注册表)
    for fp in ms.forces:
        fc = get_force_color(fp.force_id)
        op = 0.82 if fc.tier == 0 else 0.6
        sw = 1.5 if fc.successor_of else 1.2  # 继承者(分治块)描边略重
        layers.append(_poly_svg(proj, fp.rings, fc.hex, sw=sw, opacity=op))

    # 裂线层
    for f in ms.fissures:
        if f.preset:
            layers.append(_path_svg(proj, f.points, "#8b0000", 1.8, dash="5,3"))
        else:
            layers.append(_path_svg(proj, f.points, "#1a0f00", 2.0))

    # 河流
    layers.extend(_path_svg(proj, r.points, "#4a90d9", r.width) for r in ms.rivers)

    # 城邑(点;名后期合成,R7)
    for c in ms.cities:
        x, y = proj.ll(c.lon, c.lat)
        layers.append(
            f'<circle cx="{x}" cy="{y}" r="4" fill="#e8d5a3" stroke="#2b2014" stroke-width="1"/>'
        )

    if draw_labels:  # 仅校对图:势力名(生产关键帧 R7 不画)
        for fp in ms.forces:
            fc = get_force_color(fp.force_id)
            anchor = fp.label_at or fp.rings[0][0]
            x, y = proj.ll(*anchor)
            layers.append(
                f'<text x="{x}" y="{y}" font-size="15" fill="#1a0f00" font-family="serif" '
                f'font-weight="bold" text-anchor="middle">{fc.name}</text>'
            )

    body = "\n  ".join(layers)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{proj.svg_w}" height="{proj.svg_h}" '
        f'viewBox="0 0 {proj.svg_w} {proj.svg_h}">\n'
        f"  <title>{ms.state_id} — {ms.era_label}</title>\n  {body}\n</svg>\n"
    )


def render_map_state_png(ms: MapState, *, mark_battles: bool = True) -> Image.Image:
    """MapState → 确定性 PNG(Pillow,与 diagram_gen 同路子)。色从注册表取。
    R7:不画任何文字(势力名/地名后期合成)。mark_battles:城邑里 name 含'长平/之战'类战点画红环。
    生产关键帧底图与校对图共用此渲染。"""
    proj = ms.projection
    base = Image.new("RGBA", (proj.svg_w, proj.svg_h), (232, 224, 204, 255))
    for fp in ms.forces:
        fc = get_force_color(fp.force_id)
        r, g, b = fc.rgb
        alpha = int(255 * (0.82 if fc.tier == 0 else 0.6))
        overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for ring in fp.rings:
            od.polygon(
                [proj.ll(lo, la) for lo, la in ring],
                fill=(r, g, b, alpha),
                outline=(43, 32, 20, 255),
            )
        base = Image.alpha_composite(base, overlay)
    d = ImageDraw.Draw(base)
    for f in ms.fissures:
        pts = [proj.ll(lo, la) for lo, la in f.points]
        d.line(pts, fill=(139, 0, 0, 255) if f.preset else (26, 15, 0, 255), width=3)
    for rv in ms.rivers:
        d.line(
            [proj.ll(lo, la) for lo, la in rv.points],
            fill=(74, 144, 217, 255),
            width=int(rv.width) + 1,
        )
    for c in ms.cities:
        x, y = proj.ll(c.lon, c.lat)
        battle = mark_battles and ("长平" in c.name or "之战" in c.name)
        if battle:
            d.ellipse([x - 9, y - 9, x + 9, y + 9], outline=(200, 0, 0, 255), width=3)
        d.ellipse(
            [x - 4, y - 4, x + 4, y + 4], fill=(232, 213, 163, 255), outline=(43, 32, 20, 255)
        )
    return base.convert("RGB")
