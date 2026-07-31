"""S7 立牌 T1 全家福 —— 袍色一律读勢力色注册表(裁决 2026-07-22)。

T1 判定规则(spec §7):具名且露脸 = T1。本集五人:智伯/赵襄子/韩康子/魏桓子/张孟谈。
产物 output/g0d_deterministic/s7_demo/s7_lineup_T1v2.png(v2 = 注册表取色 + 张孟谈补入)。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, ".")
from hevi.tongjian.force_colors import get_force_color
from hevi.tongjian.map_anim import _paper_bg, figure_sprite

# (tag, force_id, trim, 细节) —— trim/冠/须=身份细节,袍色出注册表
T1 = [
    ("zhibo", "zhi", (150, 30, 20), {"crown": True, "seed": 11}),
    ("zhaoxiangzi", "zhao", (30, 50, 110), {"elder": True, "seed": 22}),
    ("hankangzi", "han", (110, 30, 24), {"seed": 33}),
    ("weihuanzi", "wei", (120, 90, 20), {"seed": 44}),
    ("zhangmengtan", "zhao", (232, 224, 202), {"seed": 55}),  # 赵家臣:同袍异饰
]

W, H = 1168, 560
OUT = Path("output/g0d_deterministic/s7_demo/s7_lineup_T1v2.png")


def main():
    canvas = _paper_bg(W, H)
    slot = W // (len(T1) + 1)
    floor_y = int(H * 0.95)
    for i, (tag, force, trim, extra) in enumerate(T1):
        sp = figure_sprite(get_force_color(force).rgb, trim, **extra)
        sw, sh = sp.size
        x = slot * (i + 1) - sw // 2
        canvas.alpha_composite(sp, (x, floor_y - sh))
        print(f"{tag}: 袍色={get_force_color(force).hex}({force})")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(OUT)
    print(f"✅ {OUT}")


if __name__ == "__main__":
    main()
