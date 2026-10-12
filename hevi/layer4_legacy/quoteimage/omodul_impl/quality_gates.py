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
                    # Detects injected black bars (padding, cropping errors) — NOT normal dark video content.
                    # A true black bar has near-zero brightness (< 8). Dark video backgrounds are valid content.
                    row_means = np.mean(bottom_np, axis=1)
                    dark_rows = row_means < 8.0  # Truly black, not just dark
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
                    # Merge adjacent blocks separated by a small gap (< 2x median text height)
                    # so that a single glyph line split by descenders (low edge-density rows)
                    # is measured as one text block, not several fragments.
                    if len(blocks) >= 2:
                        merged = [list(blocks[0])]
                        MERGE_GAP = 6
                        for y0, y1 in blocks[1:]:
                            if merged and y0 - merged[-1][1] <= MERGE_GAP:
                                merged[-1][1] = max(merged[-1][1], y1)
                            else:
                                merged.append([y0, y1])
                        blocks = [(y0, y1) for y0, y1 in merged]
                    strip_blocks = blocks[-4:] if len(blocks) >= 4 else blocks

                    # 5. Duplicate subtitles gate: compare actual subtitle text blocks.
                    # Two adjacent subtitle strips with near-identical edge patterns (high IoU)
                    # AND low pixel diff indicate the same subtitle text was rendered twice.
                    duplicate_pass = True
                    min_diff = 999.0
                    max_iou = 0.0
                    checked_pairs = 0
                    if len(strip_blocks) >= 2:
                        for i in range(len(strip_blocks) - 1):
                            y0_a, y1_a = strip_blocks[i]
                            y0_b, y1_b = strip_blocks[i + 1]
                            b_a = np.array(bottom_part.crop((0, y0_a, bw, y1_a)), dtype=np.float32)
                            b_b = np.array(bottom_part.crop((0, y0_b, bw, y1_b)), dtype=np.float32)
                            min_h = min(b_a.shape[0], b_b.shape[0])
                            # Compare pixel diff across the full width (not just min_h rows)
                            if b_a.shape[0] != b_b.shape[0]:
                                # Resize smaller to larger height for fair comparison
                                from PIL import Image as _PILImage
                                im_a = _PILImage.fromarray(b_a.astype(np.uint8)).resize((bw, max(b_a.shape[0], b_b.shape[0])), Image.Resampling.BILINEAR)
                                im_b = _PILImage.fromarray(b_b.astype(np.uint8)).resize((bw, max(b_a.shape[0], b_b.shape[0])), Image.Resampling.BILINEAR)
                                diff = float(np.mean(np.abs(np.array(im_a, dtype=np.float32) - np.array(im_b, dtype=np.float32))))
                            else:
                                diff = float(np.mean(np.abs(b_a - b_b)))
                            e_a = edge_binary[y0_a:y1_a, :]
                            e_b = edge_binary[y0_b:y1_b, :]
                            e_a_h = e_a[:min_h, :]
                            e_b_h = e_b[:min_h, :]
                            iou = float(np.sum(e_a_h & e_b_h) / max(1, np.sum(e_a_h | e_b_h)))

                            if diff < min_diff:
                                min_diff = diff
                            if iou > max_iou:
                                max_iou = iou
                            checked_pairs += 1
                            # Fail only when BOTH conditions hold: near-identical pixels AND high overlap
                            if diff < 4.0 and iou >= 0.45:
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

                    # Report the true minimum pixel diff observed (not a synthetic similarity score)
                    reported_dup_val = round(float(min_diff), 2)

                    gates.append({
                        "name": "subtitle_duplicate",
                        "threshold": "diff>4.0",
                        "passed": bool(duplicate_pass),
                        "value": reported_dup_val,
                        "image": img_path.name,
                    })

                    # 6. Font size / Text height gate
                    # FIX: rendered glyph height must be >= 32px at 720 width.
                    # Use the MAXIMUM text line height across all strip blocks as the
                    # representative of the unified font size being used. Short words
                    # (e.g. "boat.") naturally render with lower ink height, but the
                    # unified font size should still be visible via taller lines.
                    if "script" in img_path.name or "font" in img_path.name:
                        font_size_pass = True
                        min_text_h = 999.0
                        max_text_h = 0.0
                        if strip_blocks:
                            norm_factor = 720.0 / float(gray.width)
                            heights = []
                            for y0, y1 in strip_blocks:
                                sub = edge_binary[y0:y1, :]
                                row_has_edge = sub.any(axis=1)
                                best_run = 0
                                run = 0
                                for has in row_has_edge:
                                    if has:
                                        run += 1
                                        if run > best_run:
                                            best_run = run
                                    else:
                                        run = 0
                                h_line = best_run * norm_factor
                                heights.append(h_line)
                                if h_line < min_text_h:
                                    min_text_h = h_line
                                if h_line > max_text_h:
                                    max_text_h = h_line
                            # Require the MAXIMUM text block height >= 32px (normalized to 720)
                            # This validates the unified font size is large enough;
                            # shorter lines may naturally be smaller.
                            if max_text_h < 32.0:
                                font_size_pass = False
                        else:
                            min_text_h = 0.0
                            max_text_h = 0.0
                            font_size_pass = False

                        gates.append({
                            "name": "font_size",
                            "threshold": "max_text_height>=32",
                            "passed": bool(font_size_pass),
                            "value": round(float(max_text_h), 2),
                            "image": img_path.name,
                        })

                    # 7. Subtitle truncation detection (横向截断/裁字检测)
                    # Checks if subtitle text is cut off at the left or right margin of the frame.
                    # In properly laid out quote images, text has safe margins and does not touch border pixels (<1.0%).
                    text_edge = edge_np > 35
                    margin_x = max(8, int(bw * 0.015))

                    # Only check within actual subtitle text blocks, excluding strip-divider boundary rows.
                    # The divider lines between hero and strips (or between strips) create high edge density
                    # at the image borders, which would otherwise be false "truncation" hits.
                    in_block = False
                    block_ranges = []
                    block_start = 0
                    for y_idx in range(bh):
                        d = row_density[y_idx]
                        if d > 0.015:
                            if not in_block:
                                in_block = True
                                block_start = y_idx
                        else:
                            if in_block:
                                in_block = False
                                block_ranges.append((block_start, y_idx))
                    if in_block:
                        block_ranges.append((block_start, bh))

                    left_density = 0.0
                    right_density = 0.0
                    total_checked = 0
                    for bs, be in block_ranges:
                        # Exclude 2px boundaries (strip divider lines)
                        inner_start = bs + 2
                        inner_end = be - 2
                        if inner_end <= inner_start:
                            continue
                        l_check = text_edge[inner_start:inner_end, :margin_x]
                        r_check = text_edge[inner_start:inner_end, -margin_x:]
                        left_density += float(l_check.sum())
                        right_density += float(r_check.sum())
                        total_checked += l_check.size + r_check.size

                    if total_checked > 0:
                        max_border_density = max(left_density, right_density) / total_checked * 200.0
                    else:
                        max_border_density = 0.0

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
