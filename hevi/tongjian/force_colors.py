"""勢力色注册表 —— HEVI-EXPLAINER-PIPELINE-SPEC-001 §6.2 / L2 注册表优先。

**色值以本文件为唯一来源**(裁决 2026-07-21):地图脚本/渲染器一律 `get_force_color(force_id)`
取色,禁止把 hex 手写进 SVG。§13:勢力实体 id 主权在 AII 侧,但**色**的分配归本侧(视觉资产)。

§6.2 五规则:
  a 终身一色      —— 一个勢力跨集同色(本表即那唯一登记)
  b 同屏不撞      —— 同一画面出现的勢力色须可区分(check_same_screen_clash)
  c 继承显式      —— 分裂/继承关系用 successor_of 显式记(晋→韩赵魏)
  d 主色 ≤6–8     —— 高饱和主色预算有限,超出走灰阶 tier(tier>=1)
  e 回收间隔 ≥一代 —— (登记纪律,本表不自动回收)

★ G0 修正(裁决 6.2b):归档地图脚本硬写 韩红/赵蓝/**魏深绿**,魏深绿与齐绿同屏撞色。
  按裁决"注册表示例红/蓝/**赭黄**",魏改赭黄,与齐绿分离。
"""

from __future__ import annotations

from pydantic import BaseModel


class ForceColor(BaseModel):
    force_id: str
    name: str
    hex: str  # 唯一色值来源
    tier: int = 0  # 0=高饱和主色(预算≤6–8);>=1=灰阶/低饱和 tier(§6.2d)
    successor_of: str | None = None  # §6.2c 继承显式(如 韩/赵/魏 successor_of 晋)
    note: str = ""

    @property
    def rgb(self) -> tuple[int, int, int]:
        h = self.hex.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# ─── 战国主色登记(首发断代压力位见 spec §6【Δ】) ───────────────────────────
# 韩红 / 赵蓝 / 魏赭黄(G0 修正) 三分治色最大区分度;周边国各自锁一色。
_REGISTRY: dict[str, ForceColor] = {
    f.force_id: f
    for f in [
        # 三家分晋(晋的继承者,§6.2c 显式)
        ForceColor(force_id="han", name="韩", hex="#e06040", successor_of="jin", note="砖红"),
        ForceColor(force_id="zhao", name="赵", hex="#5070c0", successor_of="jin", note="蓝"),
        ForceColor(
            force_id="wei",
            name="魏",
            hex="#d8b020",
            successor_of="jin",
            note="赭黄/金(G0 修正:原深绿#4a8050 与齐绿撞;裁决 6.2b 改赭黄,取亮金避开楚橙棕)",
        ),
        # 原晋(裂前)
        ForceColor(force_id="jin", name="晋", hex="#7a3030", note="深红(统一态)"),
        # 周边诸侯
        ForceColor(force_id="qin", name="秦", hex="#a07850", note="赭石棕"),
        ForceColor(force_id="chu", name="楚", hex="#c4844a", note="橙棕"),
        ForceColor(force_id="qi", name="齐", hex="#8ab87a", note="草绿"),
        ForceColor(force_id="yan", name="燕", hex="#7ca6d8", note="蓝灰"),
        # 次要国走灰阶 tier(§6.2d,不占高饱和主色预算)
        ForceColor(force_id="lu", name="鲁", hex="#b8a060", tier=1, note="黄(次)"),
        ForceColor(force_id="song", name="宋", hex="#c8b080", tier=1, note="米黄(次)"),
        ForceColor(force_id="zheng", name="郑", hex="#d0c0a0", tier=1, note="淡米(次)"),
        ForceColor(force_id="zhou", name="周", hex="#d8cca8", tier=1, note="极淡(王畿)"),
    ]
}


def get_force_color(force_id: str) -> ForceColor:
    """取勢力色(唯一来源)。未登记 → KeyError(禁止静默兜底一个色,那会绕过注册表纪律)。"""
    if force_id not in _REGISTRY:
        raise KeyError(f"勢力色未登记: {force_id!r}(§6.2a 要求登记后使用,不许即兴造色)")
    return _REGISTRY[force_id]


def all_force_ids() -> list[str]:
    return list(_REGISTRY)


def _rgb_dist(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b, strict=True)) ** 0.5


def check_same_screen_clash(
    force_ids: list[str], min_dist: float = 60.0
) -> list[tuple[str, str, float]]:
    """§6.2b 同屏不撞:返回同屏勢力两两 RGB 距 < min_dist 的撞色对(空=无撞色)。
    min_dist=60 ≈ 肉眼可辨的保守下界(RGB 欧氏)。"""
    cols = [(fid, get_force_color(fid).rgb) for fid in force_ids]
    clashes = []
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            d = _rgb_dist(cols[i][1], cols[j][1])
            if d < min_dist:
                clashes.append((cols[i][0], cols[j][0], round(d, 1)))
    return clashes
