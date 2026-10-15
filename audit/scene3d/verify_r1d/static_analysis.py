"""R1D independent verifier: static pixel analysis of the SHIPPED 1080 frames.

Reads output/scene3d_r1d/<clip>/frames/*.png directly (no re-render, no chromium)
and measures the R3 C1/C2 acceptance criteria from real delivered pixels.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, label

ROOT = Path("/data/soffy/projects/hevi-scene3d")
OUT = ROOT / "output" / "scene3d_r1d"
A = ROOT / "audit" / "scene3d" / "verify_r1d"
A.mkdir(parents=True, exist_ok=True)

STAR_TIMES = {
    "9x16": {"1.3": 40, "6.5": 196, "11.7": 352},
    "16x9": {"1.3": 40, "6.5": 196, "11.7": 352},
}
FOX_TIMES = {
    "9x16": {"1.2": 37, "6.0": 181, "10.8": 325},
    "16x9": {"1.2": 37, "6.0": 181, "10.8": 325},
}


def luma_delta(image: np.ndarray) -> np.ndarray:
    rgb = image.astype(np.float32) / 255.0
    lum = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    return lum - gaussian_filter(lum, sigma=3.0)


def star_like_components(image: np.ndarray):
    """Count bright components whose size is star-like (excludes big planet disks)."""
    delta = luma_delta(image)
    mask = delta >= 0.25
    lab, n = label(mask, structure=np.ones((3, 3), dtype=np.uint8))
    sizes = np.bincount(lab.ravel())
    objs = __import__("scipy.ndimage", fromlist=["find_objects"]).find_objects(lab)
    small, large, max_delta = 0, 0, 0.0
    for i, sl in enumerate(objs, start=1):
        if sl is None:
            continue
        area = int(sizes[i])
        h = sl[0].stop - sl[0].start
        w = sl[1].stop - sl[1].start
        maxside = max(h, w)
        if area >= 3 and maxside <= 60 and area <= 3000:
            small += 1
            max_delta = max(max_delta, float(delta[sl].max()))
        elif area > 3000:
            large += 1
    return {
        "star_like": small,
        "big_blobs(planets)": large,
        "total_components": int(n),
        "max_delta": round(max_delta, 3),
    }


def hsv(image: np.ndarray):
    h = np.asarray(Image.fromarray(image).convert("HSV"), dtype=np.float32)
    return h[:, :, 0] * (360.0 / 255.0), h[:, :, 1] / 255.0, h[:, :, 2] / 255.0


def sample_px(image, x, y, r=3):
    h, w = image.shape[:2]
    x0, x1 = max(0, x - r), min(w, x + r + 1)
    y0, y1 = max(0, y - r), min(h, y + r + 1)
    patch = image[y0:y1, x0:x1].reshape(-1, 3).mean(axis=0)
    return patch


report = {"star_sea": {}, "fox_wheat": {}}

# ---- C1 star sea: shipped 1080 frames ----
for aspect, times in STAR_TIMES.items():
    rows = {}
    for t, frame in times.items():
        p = OUT / f"star_sea_{aspect}" / "frames" / f"frame_{frame:05d}.png"
        img = np.asarray(Image.open(p).convert("RGB"))
        comp = star_like_components(img)
        rows[t] = {"path": str(p.relative_to(ROOT)), "shape": list(img.shape[:2]), **comp}
    report["star_sea"][aspect] = rows

# motion check: bright blob count / centroid shifts between t=1.3 and t=6.5
for aspect in STAR_TIMES:
    f1 = np.asarray(
        Image.open(OUT / f"star_sea_{aspect}" / "frames" / "frame_00040.png").convert("RGB")
    )
    f2 = np.asarray(
        Image.open(OUT / f"star_sea_{aspect}" / "frames" / "frame_00196.png").convert("RGB")
    )
    d1, d2 = luma_delta(f1), luma_delta(f2)
    m1, m2 = d1 >= 0.25, d2 >= 0.25
    # fraction of bright pixels that changed location (frame-to-frame difference of masks)
    inter = np.logical_and(m1, m2).sum()
    union = np.logical_or(m1, m2).sum()
    report["star_sea"][aspect]["mask_iou_t1.3_vs_t6.5"] = round(float(inter) / max(1, union), 3)
    report["star_sea"][aspect]["bright_px_t1.3"] = int(m1.sum())
    report["star_sea"][aspect]["bright_px_t6.5"] = int(m2.sum())

# ---- C2 fox color: shipped 1080 frames ----
for aspect, times in FOX_TIMES.items():
    rows = {}
    for t, frame in times.items():
        p = OUT / f"fox_wheat_{aspect}" / "frames" / f"frame_{frame:05d}.png"
        img = np.asarray(Image.open(p).convert("RGB"))
        h, s, v = hsv(img)
        H, W = img.shape[:2]
        # 540-frame coords (270,440)/(270,250)/(270,80) doubled for 1080
        fx, fy = int(0.5 * W), int((440 / 960) * H)  # forehead approx
        wx, wy = int(0.5 * W), int((250 / 960) * H)
        sx, sy = int(0.5 * W), int((80 / 960) * H)

        def px_stats(x, y):
            r = 3
            patch_h = h[y - r : y + r + 1, x - r : x + r + 1]
            patch_s = s[y - r : y + r + 1, x - r : x + r + 1]
            rgb = sample_px(img, x, y, r)
            return {
                "rgb": [round(float(c)) for c in rgb],
                "hue": round(float(np.median(patch_h)), 1),
                "sat": round(float(patch_s.mean()), 3),
            }

        # fox body: saturated orange pixels in the central 40% box
        y0b, y1b = int(0.30 * H), int(0.85 * H)
        x0b, x1b = int(0.30 * W), int(0.70 * W)
        box_h, box_s = h[y0b:y1b, x0b:x1b], s[y0b:y1b, x0b:x1b]
        orange = (box_s >= 0.55) & (box_h >= 15) & (box_h <= 35)
        top_h, top_s = h[: int(0.15 * H), :], s[: int(0.15 * H), :]
        colored_sky = top_s >= 0.20
        rows[t] = {
            "path": str(p.relative_to(ROOT)),
            "forehead": px_stats(fx, fy),
            "wheat": px_stats(wx, wy),
            "sky": px_stats(sx, sy),
            "orange_px_center": int(orange.sum()),
            "orange_hue_median": round(float(np.median(box_h[orange])), 1)
            if orange.sum()
            else None,
            "orange_sat_mean": round(float(box_s[orange].mean()), 3) if orange.sum() else None,
            "top_sky_sat_mean": round(float(top_s.mean()), 3),
            "top_sky_hue_median": round(float(np.median(top_h[colored_sky])), 1)
            if colored_sky.sum()
            else None,
        }
    report["fox_wheat"][aspect] = rows

(A / "static_analysis.json").write_text(json.dumps(report, indent=1))
print(json.dumps(report, indent=1))
print("STATICDONE")
