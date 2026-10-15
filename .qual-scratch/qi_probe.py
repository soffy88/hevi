"""Objective image quality probes for QUOTEIMAGE outputs (no mocks; measurements only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageFilter


def analyze(path: Path) -> dict:
    with Image.open(path) as im:
        im = im.convert("RGB")
    w, h = im.size
    gray = np.array(im.convert("L"), dtype=np.float32)
    rgb = np.array(im, dtype=np.float32)

    # edge map (like gates use)
    g_pil = im.convert("L")
    edges = np.array(ImageChops.subtract(g_pil, g_pil.filter(ImageFilter.MinFilter(3))), dtype=np.uint8)
    edge_bin = edges > 35

    # row-wise edge density to find text blocks
    row_density = np.mean(edge_bin, axis=1)
    blocks = []
    in_block = False
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
    if in_block and h - start >= 6:
        blocks.append((start, h))

    strips = []
    for (y0, y1) in blocks[-8:]:
        seg = rgb[y0:y1, :, :]
        seg_g = gray[y0:y1, :]
        seg_e = edge_bin[y0:y1, :]
        # saturation
        mx = seg.max(axis=2)
        mn = seg.min(axis=2)
        sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
        strips.append(
            {
                "y": [int(y0), int(y1)],
                "h": int(y1 - y0),
                "mean": round(float(seg.mean()), 2),
                "std": round(float(seg.std()), 2),
                "sat_mean": round(float(sat.mean()), 4),
                "sat_std": round(float(sat.std()), 4),
                "edge_density": round(float(seg_e.mean()), 4),
                "uniqueness": round(float(len(np.unique(seg.reshape(-1, 3), axis=0))), 1),
            }
        )

    # horizontal extent of text per strip: which columns have edge energy
    extents = []
    for (y0, y1) in blocks[-8:]:
        seg_e = edge_bin[y0:y1, :]
        col_has = np.where(seg_e.any(axis=0))[0]
        if len(col_has):
            extents.append([int(col_has[0]), int(col_has[-1])])
        else:
            extents.append(None)

    # pairwise strip diffs (adjacent)
    diffs = []
    for i in range(len(blocks) - 1):
        a = blocks[i]
        b = blocks[i + 1]
        ha = a[1] - a[0]
        hb = b[1] - b[0]
        mh = min(ha, hb)
        sa = rgb[a[0] : a[0] + mh, :, :]
        sb = rgb[b[0] : b[0] + mh, :, :]
        d = float(np.mean(np.abs(sa - sb)))
        ea = edge_bin[a[0] : a[0] + mh, :]
        eb = edge_bin[b[0] : b[0] + mh, :]
        iou = float(np.sum(ea & eb) / max(1, np.sum(ea | eb)))
        diffs.append({"pair": [i, i + 1], "diff": round(d, 2), "iou": round(iou, 4)})

    # dark row runs in bottom 45%
    b0 = int(h * 0.45)
    bottom = gray[b0:, :]
    row_means = bottom.mean(axis=1)
    overall = float(gray.mean())
    dark = (row_means < 20.0) | ((overall > 150.0) & (row_means < 55.0))
    max_dark = 0
    cur = 0
    for dd in dark:
        if dd:
            cur += 1
            max_dark = max(max_dark, cur)
        else:
            cur = 0

    # border edge density
    bw = w
    margin_x = max(8, int(bw * 0.015))
    left_d = float(edge_bin[b0:, :margin_x].mean() * 100)
    right_d = float(edge_bin[b0:, -margin_x:].mean() * 100)

    return {
        "path": str(path),
        "size": [w, h],
        "overall_mean": round(overall, 2),
        "overall_std": round(float(gray.std()), 2),
        "blocks": blocks[-8:],
        "strips": strips,
        "extents": extents,
        "adjacent_diffs": diffs,
        "max_dark_rows_bottom": int(max_dark),
        "border_density_pct": round(max(left_d, right_d), 3),
    }


def main() -> int:
    out = []
    for p in sys.argv[1:]:
        out.append(analyze(Path(p)))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
