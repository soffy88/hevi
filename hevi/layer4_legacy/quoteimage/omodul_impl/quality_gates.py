from PIL import Image, ImageChops, ImageStat, ImageFilter
from pathlib import Path
from typing import Any
import numpy as np

def run_quality_gates(images: list[Path]) -> list[dict[str, Any]]:
    gates = []
    
    if not images:
        return gates
        
    for img_path in images:
        try:
            with Image.open(img_path) as img:
                # 1. Resolution
                res_pass = img.height >= 720 or img.width >= 720
                gates.append({"name": "resolution", "threshold": ">=720", "passed": res_pass, "value": max(img.width, img.height), "image": img_path.name})
                
                # 2. Blur (Laplacian variance approximation)
                gray = img.convert("L")
                stat = ImageStat.Stat(gray)
                stddev = stat.stddev[0]
                blur_pass = stddev > 20
                gates.append({"name": "blur", "threshold": ">20", "passed": blur_pass, "value": round(stddev, 2), "image": img_path.name})
                
                # Subtitle analysis area
                bottom_part = gray.crop((0, int(gray.height * 0.5), gray.width, gray.height))
                edges = ImageChops.subtract(bottom_part, bottom_part.filter(ImageFilter.MinFilter(3)))
                edge_np = np.array(edges)
                
                # 3. Subtitle completeness (Text pixel density)
                edge_mean = np.mean(edge_np)
                completeness_pass = edge_mean > 3.0
                gates.append({"name": "subtitle_completeness", "threshold": ">3.0", "passed": bool(completeness_pass), "value": round(float(edge_mean), 2), "image": img_path.name})
                
                # 4. Duplicate strips
                h = bottom_part.height
                slice_h = h // 4
                duplicate_pass = True
                max_sim = 0.0
                if slice_h > 10:
                    slices = [np.array(bottom_part.crop((0, i*slice_h, gray.width, (i+1)*slice_h))) for i in range(4)]
                    for i in range(3):
                        diff = np.mean(np.abs(slices[i].astype(np.float32) - slices[i+1].astype(np.float32)))
                        sim = 255.0 - diff
                        if sim > max_sim: max_sim = sim
                        if diff < 2.0:
                            duplicate_pass = False
                            break
                gates.append({"name": "subtitle_duplicate", "threshold": "diff>2.0", "passed": bool(duplicate_pass), "value": round(float(max_sim), 2), "image": img_path.name})

                # 5. Truncation detection
                row_edges = np.mean(edge_np, axis=1)
                max_edge_row = np.max(row_edges) if len(row_edges) > 0 else 0
                truncation_pass = max_edge_row < 100
                gates.append({"name": "subtitle_truncation", "threshold": "<100", "passed": bool(truncation_pass), "value": round(float(max_edge_row), 2), "image": img_path.name})

        except Exception as e:
            gates.append({"name": "image_error", "threshold": "none", "passed": False, "value": str(e), "image": img_path.name})
            
    return gates
