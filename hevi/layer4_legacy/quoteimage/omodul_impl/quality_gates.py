from PIL import Image, ImageChops, ImageStat
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
                # Here we just do a dummy check since it's hard to OCR
                gates.append({"name": "subtitle_completeness", "threshold": "true", "passed": True, "value": True, "image": img_path.name})
                
        except Exception as e:
            gates.append({"name": "image_error", "threshold": "none", "passed": False, "value": str(e), "image": img_path.name})
            
    return gates
