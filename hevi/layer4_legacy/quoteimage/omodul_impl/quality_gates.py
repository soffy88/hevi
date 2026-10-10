from PIL import Image, ImageChops, ImageStat, ImageFilter
from pathlib import Path
from typing import Any

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
                # simple proxy for blur: stddev
                stddev = stat.stddev[0]
                blur_pass = stddev > 20
                gates.append({"name": "blur", "threshold": ">20", "passed": blur_pass, "value": round(stddev, 2), "image": img_path.name})
                
                # 3. Subtitle completeness
                # Check if bottom part of image has text or is cut off
                bottom_30 = gray.crop((0, int(gray.height * 0.7), gray.width, gray.height))
                edges = ImageChops.subtract(bottom_30, bottom_30.filter(ImageFilter.MinFilter(3)))
                edge_stat = ImageStat.Stat(edges)
                edge_mean = edge_stat.mean[0]
                
                # If edge mean is very low, it means there is no text in the subtitle bands (it's blurry background)
                completeness_pass = edge_mean > 0.5
                gates.append({"name": "subtitle_completeness", "threshold": "edge_mean>0.5", "passed": completeness_pass, "value": round(edge_mean, 2), "image": img_path.name})
                
        except Exception as e:
            gates.append({"name": "image_error", "threshold": "none", "passed": False, "value": str(e), "image": img_path.name})
            
    return gates
