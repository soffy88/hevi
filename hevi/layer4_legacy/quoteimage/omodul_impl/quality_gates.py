from PIL import Image, ImageChops, ImageStat, ImageFilter
from pathlib import Path
from typing import Any
import numpy as np

class QualityGateError(ValueError):
    """Raised when one or more quality gates fail."""
    pass


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
                    bottom_part = gray.crop((0, int(gray.height * 0.5), gray.width, gray.height))
                    edges = ImageChops.subtract(bottom_part, bottom_part.filter(ImageFilter.MinFilter(3)))
                    edge_np = np.array(edges)
                    
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
                    
                    # 4. Duplicate strips
                    h = bottom_part.height
                    slice_h = h // 4
                    duplicate_pass = True
                    max_sim = 0.0
                    if slice_h > 10:
                        slices = [np.array(bottom_part.crop((0, i * slice_h, gray.width, (i + 1) * slice_h))) for i in range(4)]
                        for i in range(3):
                            diff = np.mean(np.abs(slices[i].astype(np.float32) - slices[i + 1].astype(np.float32)))
                            sim = 255.0 - diff
                            if sim > max_sim:
                                max_sim = sim
                            if diff < 2.0:
                                duplicate_pass = False
                                break
                    gates.append({
                        "name": "subtitle_duplicate",
                        "threshold": "diff>2.0",
                        "passed": bool(duplicate_pass),
                        "value": round(float(max_sim), 2),
                        "image": img_path.name,
                    })

                    # 5. Subtitle truncation detection (横向截断/裁字检测)
                    # Checks if subtitle text is cut off at the left or right margin of the frame.
                    # In properly laid out quote images, text has safe margins and does not touch border pixels (<1.0%).
                    bw, bh = bottom_part.size
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
