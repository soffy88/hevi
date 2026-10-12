from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageChops, ImageFilter, ImageStat


class QualityGateError(ValueError):
    """Raised when one or more quality gates fail."""


def run_quality_gates(images: list[Path]) -> list[dict[str, Any]]:
    gates = []
    
    if not images:
        return gates
        
    for img_path in images:
        try:
            with Image.open(img_path) as img:
                # 1. Resolution (contact sheet does NOT participate in resolution gate)
                if "contact_sheet" not in img_path.name and "sample" not in img_path.name:
                    res_pass = img.height >= 720 or img.width >= 720
                    gates.append({
                        "name": "resolution",
                        "threshold": ">=720",
                        "passed": bool(res_pass),
                        "value": max(img.width, img.height),
                        "image": img_path.name,
                    })
                
                # 2. Blur (Laplacian variance approximation)
                gray = img.convert("L")
                stat = ImageStat.Stat(gray)
                stddev = stat.stddev[0]
                blur_pass = stddev > 20
                gates.append({
                    "name": "blur",
                    "threshold": ">20",
                    "passed": bool(blur_pass),
                    "value": round(stddev, 2),
                    "image": img_path.name,
                })
                
                # Subtitle analysis area (bottom half) - only for quote images, not contact sheet or samples
                if "contact_sheet" not in img_path.name and "sample" not in img_path.name:
                    bottom_part = gray.crop((0, int(gray.height * 0.45), gray.width, gray.height))
                    edges = ImageChops.subtract(bottom_part, bottom_part.filter(ImageFilter.MinFilter(3)))
                    edge_np = np.array(edges)
                    bottom_np = np.array(bottom_part)
                    overall_mean = float(np.mean(np.array(gray)))
                    
                    # 3. Subtitle completeness (Text pixel density)
                    edge_mean = np.mean(edge_np)
                    completeness_pass = edge_mean > 3.0
                    gates.append({
                        "name": "subtitle_completeness",
                        "threshold": ">3.0",
                        "passed": bool(completeness_pass),
                        "value": round(float(edge_mean), 2),
                        "image": img_path.name,
                    })
                    
                    # 4. Black bar / anomalous dark band detection (纯黑条/暗色带异常检测)
                    # If image overall is non-black (mean > 35), but has a contiguous block of rows
                    # in the subtitle area with mean brightness < 20 (or significantly darker than overall in bright videos, e.g. < 55 when overall > 150),
                    # it indicates an erroneous black bar or anomalous dark slide band.
                    row_means = np.mean(bottom_np, axis=1)
                    dark_rows = (row_means < 20.0) | ((overall_mean > 150.0) & (row_means < 55.0))
                    max_dark_block = 0
                    current_dark_block = 0
                    for is_dark in dark_rows:
                        if is_dark:
                            current_dark_block += 1
                            if current_dark_block > max_dark_block:
                                max_dark_block = current_dark_block
                        else:
                            current_dark_block = 0
                    
                    black_bar_pass = not (overall_mean > 35.0 and max_dark_block >= 12)
                    gates.append({
                        "name": "black_bar",
                        "threshold": "contiguous_dark_rows<12",
                        "passed": bool(black_bar_pass),
                        "value": max_dark_block,
                        "image": img_path.name,
                    })

                    # Subtitle text line extraction in bottom region
                    bw, bh = bottom_part.size
                    edge_binary = edge_np > 35
                    row_density = np.mean(edge_binary, axis=1)

                    in_block = False
                    blocks = []
                    start = 0
                    for y, d in enumerate(row_density):
                        if d > 0.015:
                            if not in_block:
                                in_block = True
                                start = y
                        else:
                            if in_block:
                                in_block = False
                                if y - start >= 6:
                                    blocks.append((start, y))
                    if in_block and bh - start >= 6:
                        blocks.append((start, bh))
                    strip_blocks = blocks[-4:] if len(blocks) >= 4 else blocks

                    # 5. Duplicate subtitles gate
                    duplicate_pass = True
                    min_diff = 999.0
                    max_iou = 0.0
                    if len(strip_blocks) >= 2:
                        for i in range(len(strip_blocks) - 1):
                            y0_a, y1_a = strip_blocks[i]
                            y0_b, y1_b = strip_blocks[i + 1]
                            b_a = np.array(bottom_part.crop((0, y0_a, bw, y1_a)), dtype=np.float32)
                            b_b = np.array(bottom_part.crop((0, y0_b, bw, y1_b)), dtype=np.float32)
                            min_h = min(b_a.shape[0], b_b.shape[0])
                            diff = float(np.mean(np.abs(b_a[:min_h, :] - b_b[:min_h, :])))
                            e_a = edge_binary[y0_a:y1_a, :]
                            e_b = edge_binary[y0_b:y1_b, :]
                            e_a_h = e_a[:min_h, :]
                            e_b_h = e_b[:min_h, :]
                            iou = float(np.sum(e_a_h & e_b_h) / max(1, np.sum(e_a_h | e_b_h)))

                            if diff < min_diff:
                                min_diff = diff
                            if iou > max_iou:
                                max_iou = iou
                            if diff < 4.0 or iou >= 0.55:
                                duplicate_pass = False
                    else:
                        slice_h = bh // 4
                        if slice_h > 10:
                            for i in range(3):
                                s_a = np.array(bottom_part.crop((0, i * slice_h, bw, (i + 1) * slice_h)), dtype=np.float32)
                                s_b = np.array(bottom_part.crop((0, (i + 1) * slice_h, bw, (i + 2) * slice_h)), dtype=np.float32)
                                diff = float(np.mean(np.abs(s_a - s_b)))
                                if diff < min_diff:
                                    min_diff = diff
                                if diff < 4.0:
                                    duplicate_pass = False

                    if min_diff == 999.0:
                        min_diff = 255.0

                    reported_dup_val = round(min_diff * (1.0 - max_iou), 2) if max_iou >= 0.55 else round(float(min_diff), 2)

                    gates.append({
                        "name": "subtitle_duplicate",
                        "threshold": "diff>4.0",
                        "passed": bool(duplicate_pass),
                        "value": reported_dup_val,
                        "image": img_path.name,
                    })

                    # 6. Font size / Text height gate
                    # Evaluates that rendered text glyph heights meet the readability threshold (>=18px at 720p width).
                    if "script" in img_path.name or "font" in img_path.name:
                        font_size_pass = True
                        min_text_h = 999.0
                        if strip_blocks:
                            norm_factor = 720.0 / float(gray.width)
                            for y0, y1 in strip_blocks:
                                h_line = (y1 - y0) * norm_factor
                                if h_line < min_text_h:
                                    min_text_h = h_line
                            if min_text_h < 18.0:
                                font_size_pass = False
                        else:
                            min_text_h = 0.0
                            font_size_pass = False

                        gates.append({
                            "name": "font_size",
                            "threshold": "text_height>=18",
                            "passed": bool(font_size_pass),
                            "value": round(float(min_text_h), 2),
                            "image": img_path.name,
                        })

                    # 7. Subtitle truncation detection (横向截断/裁字检测)
                    # Checks if subtitle text is cut off at the left or right margin of the frame.
                    # In properly laid out quote images, text has safe margins and does not touch border pixels (<1.0%).
                    text_edge = edge_np > 35
                    margin_x = max(8, int(bw * 0.015))
                    left_border = text_edge[:, :margin_x]
                    right_border = text_edge[:, -margin_x:]
                    left_density = float(np.mean(left_border) * 100)
                    right_density = float(np.mean(right_border) * 100)
                    max_border_density = max(left_density, right_density)
                    truncation_pass = max_border_density < 1.0
                    gates.append({
                        "name": "subtitle_truncation",
                        "threshold": "border_density<1.0%",
                        "passed": bool(truncation_pass),
                        "value": round(float(max_border_density), 2),
                        "image": img_path.name,
                    })

        except Exception as e:
            gates.append({"name": "image_error", "threshold": "none", "passed": False, "value": str(e), "image": img_path.name})
            
    return gates
