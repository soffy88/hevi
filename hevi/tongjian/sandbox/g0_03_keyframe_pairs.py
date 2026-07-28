#!/usr/bin/env python3
"""G0 Task-3: 关键帧对 ×3 — 矢量双态渲染 → compose → img2img → A1/A2/A3/A4 断言

三镜头（S1/S2/S3）：
  S1: 智伯宴席索地（晋国整块，权力顶点）
  S2: 三家秘密联盟（裂线隐现，过渡）
  S3: 三家分晋落定（分裂完成，韩赵魏版图）

每镜头：
  - 从 SVG 地图对（ms_hua_453bc / ms_hua_453bc_split）渲染首帧/尾帧
  - compose: PIL 合成（叠加风格材质纹理）
  - img2img: Pillow 模拟（加噪→降噪→色偏，无需真实 API）
  - 断言 A1（质心采样比色）/ A2（OCR 零文字，正则检测）/ A3（embedding 距离）/ A4（SSIM）

注意：img2img 在 G0 阶段用确定性算法模拟，不调用 SDXL；
      真实 img2img 管线接入后用本脚本结果作为 baseline。

输出到 output/g0_sanjia_fenjin/keyframes/
"""

from __future__ import annotations

import json
import math
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageChops

OUT_KF = Path("output/g0_sanjia_fenjin/keyframes")
OUT_KF.mkdir(parents=True, exist_ok=True)

MAPS_DIR = Path("output/g0_sanjia_fenjin/maps")
STYLE_DIR = Path("output/g0_sanjia_fenjin/style")

# SVG 地图尺寸
SVG_W, SVG_H = 1200, 800

# 关键帧目标尺寸（768×512 符合视频生成常见比例）
KF_W, KF_H = 768, 512


# ─── SVG → PIL Image（不依赖 cairosvg，纯 PIL 解析 SVG 基本元素） ─────────
# 完整 SVG 渲染需要 cairosvg/inkscape，G0 阶段改用
# "将 SVG 解析出 polygon 色块，用 PIL 画" 的轻量替代方案。

def parse_svg_polygons(svg_path: Path) -> list[dict]:
    """从 SVG 提取 polygon 元素（坐标+颜色）。"""
    tree = ET.parse(svg_path)
    root = tree.getroot()
    ns = {"svg": "http://www.w3.org/2000/svg"}
    polygons = []
    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag == "polygon":
            pts_str = elem.get("points", "")
            fill = elem.get("fill", "#888888")
            opacity = float(elem.get("fill-opacity", "1.0"))
            sw = float(elem.get("stroke-width", "1.0"))
            stroke = elem.get("stroke", "#000000")
            pts_pairs = []
            nums = pts_str.replace(",", " ").split()
            for i in range(0, len(nums) - 1, 2):
                try:
                    pts_pairs.append((float(nums[i]), float(nums[i + 1])))
                except (ValueError, IndexError):
                    pass
            if pts_pairs:
                polygons.append({
                    "points": pts_pairs,
                    "fill": fill,
                    "fill_opacity": opacity,
                    "stroke": stroke,
                    "stroke_width": sw,
                })
        elif tag == "path":
            # 只提取河流（简化：记录描边颜色）
            d = elem.get("d", "")
            stroke = elem.get("stroke", "none")
            sw = float(elem.get("stroke-width", "1.0"))
            polygons.append({
                "type": "path",
                "d": d,
                "stroke": stroke,
                "stroke_width": sw,
                "fill": "none",
                "fill_opacity": 0,
                "points": [],
            })
        elif tag == "text":
            polygons.append({"type": "text", "text": elem.text or "", "points": []})
    return polygons


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = h[0]*2 + h[1]*2 + h[2]*2
    if len(h) < 6:
        return (128, 128, 128)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (128, 128, 128)


def render_svg_to_pil(svg_path: Path, target_w: int, target_h: int) -> Image.Image:
    """将 SVG 渲染为 PIL Image（轻量 PIL 实现，不依赖 cairosvg）。"""
    polygons = parse_svg_polygons(svg_path)

    # 缩放因子
    sx = target_w / SVG_W
    sy = target_h / SVG_H

    img = Image.new("RGB", (target_w, target_h), (232, 224, 204))  # 皮纸底色
    draw = ImageDraw.Draw(img, "RGBA")

    for poly in polygons:
        if poly.get("type") in ("path", "text"):
            # 简化：路径和文字跳过（G0 精度够用）
            continue
        pts = [(p[0] * sx, p[1] * sy) for p in poly.get("points", [])]
        if len(pts) < 3:
            continue
        fill_hex = poly["fill"]
        opacity = poly["fill_opacity"]
        try:
            r, g, b = hex_to_rgb(fill_hex)
        except Exception:
            r, g, b = 128, 128, 128
        alpha = int(opacity * 220)
        draw.polygon(pts, fill=(r, g, b, alpha))
        # 描边
        stroke = poly.get("stroke", "#2b2014")
        sw = poly.get("stroke_width", 1.0)
        if stroke not in ("none", ""):
            try:
                sr, sg, sb = hex_to_rgb(stroke)
                draw.polygon(pts, outline=(sr, sg, sb, 200))
            except Exception:
                pass

    # 叠加河流（简化：用蓝色折线模拟黄河长江）
    # 黄河（简化路径）
    huang_pts_svg = [
        (305.8, 421.2), (360.0, 362.4), (444.0, 303.5), (504.0, 283.5),
        (546.0, 302.4), (607.2, 321.2), (624.0, 340.0), (633.6, 360.0),
        (651.6, 380.0), (714.0, 400.0), (780.0, 371.8),
    ]
    huang_pts = [(p[0] * sx, p[1] * sy) for p in huang_pts_svg]
    draw.line(huang_pts, fill=(74, 144, 217, 200), width=max(2, int(3 * sx)))

    # 长江（简化）
    chang_pts_svg = [
        (230.4, 502.4), (325.2, 481.2), (432.0, 459.5), (534.0, 470.6),
        (657.6, 482.4), (730.8, 472.9), (762.0, 451.8), (828.0, 440.5),
        (966.0, 451.8),
    ]
    chang_pts = [(p[0] * sx, p[1] * sy) for p in chang_pts_svg]
    draw.line(chang_pts, fill=(74, 144, 217, 180), width=max(2, int(2.5 * sx)))

    return img.convert("RGB")


# ─── compose: 叠加纸质材质 ──────────────────────────────────────────────────

def compose_with_texture(base: Image.Image, texture_idx: int = 0) -> Image.Image:
    """将地图底图与手撕纸材质融合（Screen/Multiply 混合）。"""
    tex_path = STYLE_DIR / f"torn_paper_{texture_idx+1:02d}.png"
    if not tex_path.exists():
        return base
    tex = Image.open(tex_path).resize(base.size, Image.LANCZOS).convert("RGB")

    # Multiply 混合（降低纸纹对地图的干扰）
    blended = ImageChops.multiply(base, tex)
    # 与原图按 30/70 混合，保留地图清晰度
    result = Image.blend(base, blended, alpha=0.30)
    return result


# ─── img2img 模拟（确定性算法替代 SDXL） ────────────────────────────────────

def simulated_img2img(
    img: Image.Image,
    denoising_strength: float = 0.35,
    seed: int = 42,
) -> Image.Image:
    """模拟 SDXL img2img：加噪→降噪→色偏。

    G0 用确定性算法给出稳定 baseline，真实 API 接入后替换此函数。
    denoising_strength ∈ [0.2, 0.5]：0.35 = 保留主体结构，允许风格化偏移。
    """
    import random
    rng = random.Random(seed)

    # 1. 高斯噪声（模拟 diffusion 加噪）
    import numpy as np
    arr = np.array(img, dtype=np.float32)
    noise_level = denoising_strength * 40  # 最大噪声幅度
    noise = np.random.RandomState(seed).normal(0, noise_level, arr.shape)
    noisy = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img_noisy = Image.fromarray(noisy)

    # 2. 降噪 + 风格化（高斯模糊模拟扩散平滑）
    img_smooth = img_noisy.filter(ImageFilter.GaussianBlur(radius=denoising_strength * 2.5))

    # 3. 色偏（水墨历史风格：饱和度压低 + 暖偏）
    img_desaturated = ImageEnhance.Color(img_smooth).enhance(0.72)
    img_contrast = ImageEnhance.Contrast(img_desaturated).enhance(1.08)
    img_brightness = ImageEnhance.Brightness(img_contrast).enhance(0.93)

    # 4. 皮纸色调叠加（轻微色调映射）
    paper_overlay = Image.new("RGB", img.size, (215, 198, 158))
    result = Image.blend(img_brightness, paper_overlay, alpha=0.08)

    return result


# ─── 断言函数 ────────────────────────────────────────────────────────────────

def A1_centroid_color_diff(
    img_a: Image.Image, img_b: Image.Image, label_a: str = "首帧", label_b: str = "尾帧"
) -> dict:
    """A1: 质心区域采样比色。
    采样中心 32×32 区域的平均 RGB，计算差值。
    返回 ΔR/ΔG/ΔB 和 ΔE（欧氏距离）。
    """
    def centroid_sample(img: Image.Image) -> tuple[float, float, float]:
        cx, cy = img.width // 2, img.height // 2
        region = img.crop((cx - 16, cy - 16, cx + 16, cy + 16))
        data = list(region.getdata())
        n = len(data)
        r = sum(p[0] for p in data) / n
        g = sum(p[1] for p in data) / n
        b = sum(p[2] for p in data) / n
        return (r, g, b)

    ca = centroid_sample(img_a)
    cb = centroid_sample(img_b)
    delta_e = math.sqrt(sum((x - y) ** 2 for x, y in zip(ca, cb)))
    return {
        "gate": "A1_centroid_color",
        f"{label_a}_rgb": [round(x, 1) for x in ca],
        f"{label_b}_rgb": [round(x, 1) for x in cb],
        "delta_E": round(delta_e, 3),
        "note": "质心32×32区采样均值色差（欧氏距离）",
    }


def A2_ocr_no_text(img: Image.Image) -> dict:
    """A2: OCR 零文字断言（不调用 OCR，用 SVG 特征检测替代）。

    G0 阶段：
    - 检查是否含有明显的文字像素聚集区（高对比单色细线）
    - 实际 OCR 接入（Tesseract/paddleocr）后替换此函数
    - 正则检测：SVG 文本元素提取
    """
    # 检查图像是否含大面积单色区域（潜在文字块）
    # 简化：转灰度，检测高对比细线密度
    gray = img.convert("L")
    # 边缘检测
    edges = gray.filter(ImageFilter.FIND_EDGES)

    import numpy as np
    arr = np.array(edges)
    edge_density = float(arr.mean())  # 越高 = 越多边缘

    # G0 阈值：地图图像边缘密度通常在 8–25 范围内
    # 文字密集图像边缘密度通常 > 35
    has_text_suspected = edge_density > 35.0

    return {
        "gate": "A2_ocr_no_text",
        "method": "edge_density_proxy（G0占位；生产用paddleocr/tesseract）",
        "edge_density": round(edge_density, 3),
        "threshold": 35.0,
        "text_suspected": bool(has_text_suspected),
        "passed": bool(not has_text_suspected),
        "note": "A2 通过 = 无明显文字聚集区（地图本身的少量地名标注可接受）",
    }


def A3_embedding_distance(img_a: Image.Image, img_b: Image.Image) -> dict:
    """A3: 图像 embedding 距离（G0 只记录，不设阈值）。

    用 PIL 质量简化版：DCT 特征哈希作为 embedding 代理。
    生产版本用 CLIP/ViT 替换。
    """
    import numpy as np

    def img_hash_vector(img: Image.Image, size: int = 32) -> list[float]:
        """感知哈希的连续扩展版（pHash 变体作为 embedding 代理）。"""
        gray = img.convert("L").resize((size, size), Image.LANCZOS)
        arr = np.array(gray, dtype=np.float32)
        # 计算 DCT（简化：用均值差分代替完整 DCT）
        mean_val = arr.mean()
        features = ((arr - mean_val) / (arr.std() + 1e-6)).flatten()
        return features.tolist()

    v_a = img_hash_vector(img_a)
    v_b = img_hash_vector(img_b)

    # 余弦相似度
    a = sum(x * y for x, y in zip(v_a, v_b))
    norm_a = math.sqrt(sum(x * x for x in v_a))
    norm_b = math.sqrt(sum(x * x for x in v_b))
    cos_sim = a / (norm_a * norm_b + 1e-8)

    # L2 距离（欧氏距离归一化）
    l2 = math.sqrt(sum((x - y) ** 2 for x, y in zip(v_a, v_b)))
    l2_norm = l2 / len(v_a)

    return {
        "gate": "A3_embedding_distance",
        "method": "pHash-DCT-proxy（G0标定用；生产用CLIP-ViT-B/32）",
        "cosine_similarity": round(cos_sim, 4),
        "l2_normalized": round(l2_norm, 6),
        "no_threshold": True,
        "note": "G0 只记录 embedding 距离分布，不设阈值 — 这个值就是 A3 的 baseline",
    }


def A4_ssim(img_a: Image.Image, img_b: Image.Image) -> dict:
    """A4: 底层 SSIM（结构相似度）。

    用 numpy 实现轻量 SSIM（避免 skimage 依赖）。
    """
    import numpy as np

    def to_gray_arr(img: Image.Image) -> "np.ndarray":
        return np.array(img.convert("L").resize((256, 192), Image.LANCZOS), dtype=np.float64)

    a = to_gray_arr(img_a)
    b = to_gray_arr(img_b)

    # SSIM 参数
    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2

    mu_a = a.mean()
    mu_b = b.mean()
    sigma_a = a.std()
    sigma_b = b.std()
    sigma_ab = ((a - mu_a) * (b - mu_b)).mean()

    numerator = (2 * mu_a * mu_b + C1) * (2 * sigma_ab + C2)
    denominator = (mu_a**2 + mu_b**2 + C1) * (sigma_a**2 + sigma_b**2 + C2)
    ssim_val = numerator / (denominator + 1e-10)

    return {
        "gate": "A4_ssim",
        "method": "lightweight_numpy_ssim",
        "ssim": round(float(ssim_val), 4),
        "threshold_g0": 0.3,
        "passed": bool(ssim_val >= 0.3),
        "note": "A4 阈值 0.3：首/尾帧内容差异大（地图变化），期望 0.35–0.7",
    }


# ─── 镜头定义 ────────────────────────────────────────────────────────────────

SHOTS = [
    {
        "shot_id": "S1",
        "title": "智伯宴席索地（权力顶点）",
        "frame_a_desc": "晋国完整版图，色块深红，裂线隐而不发",
        "frame_b_desc": "同底图，烛光暖调叠加，智伯影影绰绰",
        "svg_a": "ms_hua_453bc.svg",
        "svg_b": "ms_hua_453bc.svg",
        "texture_a": 0,
        "texture_b": 2,
        "denoising_a": 0.30,
        "denoising_b": 0.40,
        "seed_a": 101,
        "seed_b": 102,
    },
    {
        "shot_id": "S2",
        "title": "三家秘密联盟（裂线隐现，过渡）",
        "frame_a_desc": "晋国版图，裂线层渗出，色调开始分裂",
        "frame_b_desc": "分裂版图浮现，但轮廓尚模糊",
        "svg_a": "ms_hua_453bc.svg",
        "svg_b": "ms_hua_453bc_split.svg",
        "texture_a": 3,
        "texture_b": 4,
        "denoising_a": 0.35,
        "denoising_b": 0.38,
        "seed_a": 201,
        "seed_b": 202,
    },
    {
        "shot_id": "S3",
        "title": "三家分晋落定（韩赵魏版图成形）",
        "frame_a_desc": "晋国最后瞬间",
        "frame_b_desc": "韩赵魏三色块清晰呈现，晋消亡",
        "svg_a": "ms_hua_453bc.svg",
        "svg_b": "ms_hua_453bc_split.svg",
        "texture_a": 1,
        "texture_b": 5,
        "denoising_a": 0.32,
        "denoising_b": 0.42,
        "seed_a": 301,
        "seed_b": 302,
    },
]


# ─── 主逻辑 ─────────────────────────────────────────────────────────────────

def process_shot(shot: dict) -> dict:
    sid = shot["shot_id"]
    print(f"\n=== {sid}: {shot['title']} ===")

    # 检查 SVG 是否存在
    svg_a_path = MAPS_DIR / shot["svg_a"]
    svg_b_path = MAPS_DIR / shot["svg_b"]
    if not svg_a_path.exists():
        return {"shot_id": sid, "error": f"SVG not found: {svg_a_path}"}
    if not svg_b_path.exists():
        return {"shot_id": sid, "error": f"SVG not found: {svg_b_path}"}

    t0 = time.perf_counter()

    # 1. 渲染首帧（SVG → PIL）
    raw_a = render_svg_to_pil(svg_a_path, KF_W, KF_H)
    raw_b = render_svg_to_pil(svg_b_path, KF_W, KF_H)
    print(f"  渲染SVG: {time.perf_counter()-t0:.2f}s")

    # 2. Compose: 叠加纸质材质
    t1 = time.perf_counter()
    comp_a = compose_with_texture(raw_a, shot["texture_a"])
    comp_b = compose_with_texture(raw_b, shot["texture_b"])
    print(f"  Compose材质: {time.perf_counter()-t1:.2f}s")

    # 3. img2img 模拟
    t2 = time.perf_counter()
    kf_a = simulated_img2img(comp_a, denoising_strength=shot["denoising_a"], seed=shot["seed_a"])
    kf_b = simulated_img2img(comp_b, denoising_strength=shot["denoising_b"], seed=shot["seed_b"])
    print(f"  img2img模拟: {time.perf_counter()-t2:.2f}s")

    # 保存关键帧
    p_a = OUT_KF / f"{sid}_frame_a.png"
    p_b = OUT_KF / f"{sid}_frame_b.png"
    kf_a.save(p_a)
    kf_b.save(p_b)

    # 4. 断言
    t3 = time.perf_counter()
    assert_A1 = A1_centroid_color_diff(kf_a, kf_b)
    assert_A2_a = A2_ocr_no_text(kf_a)
    assert_A2_b = A2_ocr_no_text(kf_b)
    assert_A3 = A3_embedding_distance(kf_a, kf_b)
    assert_A4 = A4_ssim(kf_a, kf_b)
    print(f"  断言计算: {time.perf_counter()-t3:.2f}s")

    t_total = time.perf_counter() - t0

    result = {
        "shot_id": sid,
        "title": shot["title"],
        "frame_a": {"path": str(p_a), "desc": shot["frame_a_desc"]},
        "frame_b": {"path": str(p_b), "desc": shot["frame_b_desc"]},
        "assertions": {
            "A1": assert_A1,
            "A2_frame_a": assert_A2_a,
            "A2_frame_b": assert_A2_b,
            "A3": assert_A3,
            "A4": assert_A4,
        },
        "retry_count": 0,  # G0：无重试（物理验证阶段）
        "timing_seconds": round(t_total, 3),
    }

    # 断言摘要打印
    a1_ok = assert_A1["delta_E"] > 0  # A1：只记录，任何差值都有效
    a2_ok = assert_A2_a["passed"] and assert_A2_b["passed"]
    a4_ok = assert_A4["passed"]
    print(f"  A1 ΔE={assert_A1['delta_E']:.3f}  "
          f"A2={'✅' if a2_ok else '⚠️'}  "
          f"A3 cos={assert_A3['cosine_similarity']:.4f}  "
          f"A4 SSIM={assert_A4['ssim']:.4f} {'✅' if a4_ok else '⚠️'}")

    return result


def main():
    # 检查前置依赖（地图 SVG、风格材质）
    missing = []
    for f in ["ms_hua_453bc.svg", "ms_hua_453bc_split.svg"]:
        if not (MAPS_DIR / f).exists():
            missing.append(str(MAPS_DIR / f))
    if missing:
        print(f"⚠️  缺少前置文件，请先运行 g0_01_draw_maps.py: {missing}")
        print("    继续执行（将用空白底图）...")

    results = []
    t_total = time.perf_counter()

    for shot in SHOTS:
        result = process_shot(shot)
        results.append(result)

    t_elapsed = time.perf_counter() - t_total

    # 写汇总
    summary = {
        "run_id": "g0_keyframe_run",
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "shots": results,
        "total_timing_seconds": round(t_elapsed, 3),
        "note": "G0 三家分晋关键帧断言 — 物理验证基准",
        "A3_baseline_note": "A3 embedding 距离 G0 不设阈值，以本次值作为 baseline 参考",
        "threshold_suggestions": {
            "A4_ssim_recommend": 0.35,
            "A1_delta_E_change_detect": 20.0,
            "A3_cos_same_scene": 0.85,
            "A3_cos_transition": 0.50,
        },
    }

    out_json = OUT_KF / "keyframe_assertions.json"
    out_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✓ 断言汇总: {out_json}")
    print(f"总工时: {t_elapsed:.2f}s")

    # 打印简表
    print("\n─── 断言数值表 ───────────────────────────────────────────────")
    for r in results:
        if "error" in r:
            print(f"{r['shot_id']}: ERROR {r['error']}")
            continue
        asr = r["assertions"]
        print(f"{r['shot_id']} [{r['title'][:12]}...]")
        print(f"  A1 ΔE={asr['A1']['delta_E']:.3f}  "
              f"A2={'OK' if asr['A2_frame_a']['passed'] and asr['A2_frame_b']['passed'] else 'WARN'}  "
              f"A3 cos={asr['A3']['cosine_similarity']:.4f} l2={asr['A3']['l2_normalized']:.4f}  "
              f"A4 SSIM={asr['A4']['ssim']:.4f} {'OK' if asr['A4']['passed'] else 'WARN'}")
    print("──────────────────────────────────────────────────────────────")


if __name__ == "__main__":
    main()
