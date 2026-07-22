#!/usr/bin/env python3
"""G0 Task-2: 最小风格包 v0

1. 生成 5–10 张手撕纸材质参考图（Pillow 纯算法生成，无网络调用）
2. 跑一遍校准色卡：渲染 hex → 模拟 img2img 色偏 → 采样实际呈现色
   输出 style/color_calibration.json

输出到 output/g0_sanjia_fenjin/style/
"""

from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageEnhance

OUT = Path("output/g0_sanjia_fenjin/style")
OUT.mkdir(parents=True, exist_ok=True)

# ─── 目标调色板（来自宪法 §constitution.json 的 palette） ──────────────────
# 453BC 风格：水墨质感历史插画，低饱和，烛光/暮色主导
PALETTE_HEX = [
    "#2b2b2b",   # 墨黑（主轮廓）
    "#8b0000",   # 深红（晋/韩标识）
    "#d4c5a0",   # 皮纸米黄（底色）
    "#4a3820",   # 深棕（阴影）
    "#c8a060",   # 烛光金
    "#3a5070",   # 暮色深蓝
    "#7a9080",   # 苔绿（绿地）
    "#e8e0cc",   # 浅米（地图底）
    "#5070c0",   # 赵蓝
    "#4a8050",   # 魏绿
]


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


# ─── 手撕纸材质生成 ─────────────────────────────────────────────────────────

def make_torn_paper(
    idx: int,
    w: int = 512,
    h: int = 512,
    seed: int = 42,
) -> Image.Image:
    """生成一张手撕纸材质参考图。
    算法：
    1. 基底色（米黄/牛皮纸色段）
    2. Perlin-like 噪声（用 sin 叠加模拟）
    3. 随机划痕纹理
    4. 撕裂边缘（边缘不规则 mask）
    5. 轻微色彩偏移
    """
    rng = random.Random(seed + idx * 17)
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)

    # 基底色变化
    base_colors = [
        (215, 198, 158),  # 皮纸
        (200, 185, 140),  # 旧纸
        (230, 215, 175),  # 亮皮纸
        (185, 165, 120),  # 深棕纸
        (210, 200, 170),  # 灰皮纸
        (225, 210, 165),  # 宣纸白
        (195, 178, 132),  # 古书纸
        (240, 225, 185),  # 淡米纸
    ]
    base_r, base_g, base_b = base_colors[idx % len(base_colors)]

    # 逐像素绘制噪声
    pixels = []
    for y in range(h):
        row = []
        for x in range(w):
            # 多频叠加纹理噪声（伪 Perlin）
            n = (math.sin(x * 0.08 + y * 0.05 + idx) * 0.3
                 + math.sin(x * 0.25 + y * 0.15 + idx * 1.7) * 0.15
                 + math.sin(x * 0.4 + y * 0.3 + idx * 2.3) * 0.08)
            noise_val = int(n * 18)

            # 随机颗粒感
            grain = rng.randint(-12, 12)

            r = max(0, min(255, base_r + noise_val + grain))
            g = max(0, min(255, base_g + noise_val + grain - 3))
            b = max(0, min(255, base_b + noise_val + grain - 6))
            row.append((r, g, b))
        pixels.append(row)

    # 写入像素
    for y, row in enumerate(pixels):
        for x, pix in enumerate(row):
            img.putpixel((x, y), pix)

    # 随机划痕（细线条）
    n_scratches = rng.randint(3, 12)
    for _ in range(n_scratches):
        x0 = rng.randint(0, w)
        y0 = rng.randint(0, h)
        angle = rng.uniform(0, math.pi)
        length = rng.randint(20, 180)
        x1 = int(x0 + math.cos(angle) * length)
        y1 = int(y0 + math.sin(angle) * length)
        scratch_color = (
            max(0, base_r - rng.randint(20, 50)),
            max(0, base_g - rng.randint(20, 50)),
            max(0, base_b - rng.randint(25, 55)),
        )
        draw.line([(x0, y0), (x1, y1)], fill=scratch_color, width=1)

    # 水迹晕染（椭圆渐变斑）
    n_stains = rng.randint(1, 5)
    for _ in range(n_stains):
        sx = rng.randint(0, w)
        sy = rng.randint(0, h)
        sr = rng.randint(20, 80)
        stain_color = (
            max(0, base_r - rng.randint(8, 20)),
            max(0, base_g - rng.randint(8, 20)),
            max(0, base_b - rng.randint(5, 15)),
        )
        for dy in range(-sr, sr + 1):
            for dx in range(-sr, sr + 1):
                dist = math.sqrt(dx*dx + dy*dy)
                if dist <= sr:
                    px_, py_ = sx + dx, sy + dy
                    if 0 <= px_ < w and 0 <= py_ < h:
                        alpha = (1 - dist / sr) * 0.3
                        orig = img.getpixel((px_, py_))
                        nr = int(orig[0] * (1 - alpha) + stain_color[0] * alpha)
                        ng = int(orig[1] * (1 - alpha) + stain_color[1] * alpha)
                        nb = int(orig[2] * (1 - alpha) + stain_color[2] * alpha)
                        img.putpixel((px_, py_), (nr, ng, nb))

    # 撕裂边缘：不规则白边遮罩
    edge_mask = Image.new("L", (w, h), 255)
    mask_draw = ImageDraw.Draw(edge_mask)
    n_edge_pts = 40
    for edge in ["top", "bottom", "left", "right"]:
        pts_list = []
        if edge == "top":
            for i in range(n_edge_pts + 1):
                ex = int(i * w / n_edge_pts)
                ey = rng.randint(0, 18)
                pts_list.append((ex, ey))
            pts_list += [(w, 0), (0, 0)]
        elif edge == "bottom":
            for i in range(n_edge_pts + 1):
                ex = int(i * w / n_edge_pts)
                ey = h - rng.randint(0, 18)
                pts_list.append((ex, ey))
            pts_list += [(w, h), (0, h)]
        elif edge == "left":
            for i in range(n_edge_pts + 1):
                ey = int(i * h / n_edge_pts)
                ex = rng.randint(0, 18)
                pts_list.append((ex, ey))
            pts_list += [(0, h), (0, 0)]
        else:  # right
            for i in range(n_edge_pts + 1):
                ey = int(i * h / n_edge_pts)
                ex = w - rng.randint(0, 18)
                pts_list.append((ex, ey))
            pts_list += [(w, h), (w, 0)]
        mask_draw.polygon(pts_list, fill=0)

    # 应用撕裂遮罩（白边模拟撕痕）
    white_bg = Image.new("RGB", (w, h), (255, 255, 255))
    img = Image.composite(white_bg, img, edge_mask)

    # 轻微模糊（纸纹软化）
    img = img.filter(ImageFilter.GaussianBlur(radius=0.6))

    # 低饱和（历史感）
    img = ImageEnhance.Color(img).enhance(0.7)

    return img


# ─── 色卡校准 ────────────────────────────────────────────────────────────────

def simulate_img2img_color_shift(r: int, g: int, b: int, seed: int = 0) -> tuple[int, int, int]:
    """模拟 img2img 后的色偏（基于经验：SDXL img2img 低 denoising strength 下
    通常有 +3~8% 饱和度衰减，并带轻微暖偏或冷偏依风格而定）。
    这里用确定性算法模拟，供工具链知晓预期色偏区间。

    实际项目应将真实 hex 色块送入 SDXL img2img，采样输出颜色。
    G0 阶段：用算法给出合理的理论近似，记录为 A3 标定基准。
    """
    rng = random.Random(seed + r * 31 + g * 17 + b * 7)

    # 转 HSV 做饱和度衰减
    import colorsys
    h_f, s_f, v_f = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)

    # 饱和度衰减 (模拟 SDXL 水墨风格 LoRA 压低饱和)
    s_decay = rng.uniform(0.05, 0.15)
    s_new = max(0.0, s_f - s_decay)

    # 暖偏（烛光/皮纸环境）
    warm_shift = rng.uniform(0.01, 0.05)
    if h_f > 0.5:  # 冷色系反而有冷偏
        warm_shift *= -0.5

    # 亮度轻微压低（历史感）
    v_shift = rng.uniform(-0.03, 0.02)
    v_new = max(0.0, min(1.0, v_f + v_shift))

    r2, g2, b2 = colorsys.hsv_to_rgb(h_f + warm_shift, s_new, v_new)
    return (int(r2 * 255), int(g2 * 255), int(b2 * 255))


def sample_centroid_color(img: Image.Image, region: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """采样图像区域的质心色（平均 RGB）。"""
    x0, y0, x1, y1 = region
    crop = img.crop((x0, y0, x1, y1))
    arr = list(crop.getdata())
    n = len(arr)
    if n == 0:
        return (128, 128, 128)
    r = sum(p[0] for p in arr) // n
    g = sum(p[1] for p in arr) // n
    b = sum(p[2] for p in arr) // n
    return (r, g, b)


def run_color_calibration() -> dict:
    """渲染色卡 → 模拟 img2img → 采样实际呈现色。"""
    SWATCH_W, SWATCH_H = 64, 64
    N = len(PALETTE_HEX)
    card_w = N * SWATCH_W
    card_h = SWATCH_H * 3  # 行1: 原始; 行2: 渲染后; 行3: img2img 模拟

    card = Image.new("RGB", (card_w, card_h), (240, 235, 220))
    draw = ImageDraw.Draw(card)

    calibration = []

    for i, hex_col in enumerate(PALETTE_HEX):
        r, g, b = hex_to_rgb(hex_col)

        # 行1: 原始 hex 色块
        draw.rectangle(
            [i * SWATCH_W, 0, (i + 1) * SWATCH_W - 1, SWATCH_H - 1],
            fill=(r, g, b),
        )

        # 行2: 模拟在皮纸底上渲染（乘以纸质基底色=210,198,158）
        paper_r, paper_g, paper_b = 210, 198, 158
        alpha = 0.75
        rendered_r = int(r * alpha + paper_r * (1 - alpha))
        rendered_g = int(g * alpha + paper_g * (1 - alpha))
        rendered_b = int(b * alpha + paper_b * (1 - alpha))
        draw.rectangle(
            [i * SWATCH_W, SWATCH_H, (i + 1) * SWATCH_W - 1, SWATCH_H * 2 - 1],
            fill=(rendered_r, rendered_g, rendered_b),
        )

        # 行3: img2img 色偏模拟
        shifted_r, shifted_g, shifted_b = simulate_img2img_color_shift(
            rendered_r, rendered_g, rendered_b, seed=i
        )
        draw.rectangle(
            [i * SWATCH_W, SWATCH_H * 2, (i + 1) * SWATCH_W - 1, SWATCH_H * 3 - 1],
            fill=(shifted_r, shifted_g, shifted_b),
        )

        # 采样质心色
        sampled_original = sample_centroid_color(card, (i * SWATCH_W, 0, (i + 1) * SWATCH_W, SWATCH_H))
        sampled_rendered = sample_centroid_color(card, (i * SWATCH_W, SWATCH_H, (i + 1) * SWATCH_W, SWATCH_H * 2))
        sampled_shifted = sample_centroid_color(card, (i * SWATCH_W, SWATCH_H * 2, (i + 1) * SWATCH_W, SWATCH_H * 3))

        # 色差 ΔE 简化（欧氏距离）
        def delta_e(a, b_):
            return round(math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b_))), 2)

        calibration.append({
            "index": i,
            "hex_original": hex_col,
            "rgb_original": list(sampled_original),
            "hex_rendered": rgb_to_hex(*sampled_rendered),
            "rgb_rendered": list(sampled_rendered),
            "hex_img2img_simulated": rgb_to_hex(*sampled_shifted),
            "rgb_img2img_simulated": list(sampled_shifted),
            "delta_e_orig_to_rendered": delta_e(sampled_original, sampled_rendered),
            "delta_e_rendered_to_img2img": delta_e(sampled_rendered, sampled_shifted),
            "note": "G0标定基准；行1=原始hex，行2=皮纸底混合，行3=img2img色偏模拟"
        })

    # 存卡图
    card_path = OUT / "color_calibration_card.png"
    card.save(card_path)
    print(f"✓ 色卡图: {card_path}")

    return {"palette": calibration, "card_image": str(card_path)}


# ─── 主逻辑 ─────────────────────────────────────────────────────────────────

def main():
    timing = {}

    # 1. 生成手撕纸材质参考图 (8 张)
    t0 = time.perf_counter()
    n_textures = 8
    texture_paths = []
    for i in range(n_textures):
        img = make_torn_paper(i, seed=1000 + i * 31)
        p = OUT / f"torn_paper_{i+1:02d}.png"
        img.save(p)
        texture_paths.append(str(p))
        print(f"✓ 材质图 {i+1}/{n_textures}: {p}")
    t1 = time.perf_counter()
    timing["torn_paper_seconds"] = round(t1 - t0, 3)

    # 2. 色卡校准
    t2 = time.perf_counter()
    calib_result = run_color_calibration()
    t3 = time.perf_counter()
    timing["color_calibration_seconds"] = round(t3 - t2, 3)
    timing["total_seconds"] = round(t3 - t0, 3)

    # 写结果
    result = {
        "texture_paths": texture_paths,
        "n_textures": n_textures,
        "calibration": calib_result,
        "timing": timing,
        "note": "G0 最小风格包 v0 — 手撕纸材质 + 色卡校准",
    }
    out_json = OUT / "style_pack_v0.json"
    out_json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✓ 风格包摘要: {out_json}")
    print(f"工时: 材质 {timing['torn_paper_seconds']}s | 色卡 {timing['color_calibration_seconds']}s")


if __name__ == "__main__":
    main()
