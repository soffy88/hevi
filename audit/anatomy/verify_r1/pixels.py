"""Anatomy R1 verifier: quantify the shipped sample frames (no re-render)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

base = Path("audit/anatomy/samples")
BG = np.array([37, 99, 235])  # #2563eb body background


def stats(sample: str) -> dict:
    fs = sorted((base / sample / "frames").glob("*.png"))
    if len(fs) < 3:
        return {"sample": sample, "frames": len(fs)}
    im0 = np.asarray(Image.open(fs[0]).convert("RGB"), dtype=np.int16)
    immid = np.asarray(Image.open(fs[len(fs) // 2]).convert("RGB"), dtype=np.int16)
    imend = np.asarray(Image.open(fs[-1]).convert("RGB"), dtype=np.int16)
    fg = np.abs(im0 - BG).max(axis=2) > 30
    d0 = np.abs(im0 - immid).max(axis=2)
    return {
        "sample": sample,
        "frames": len(fs),
        "size": list(im0.shape[:2]),
        "fg_frac": round(float(fg.mean()), 3),
        "fg_frac_excl_top220": round(float(fg[220:, :].mean()), 3),
        "meanΔ_0_mid": round(float(np.abs(im0 - immid).mean()), 3),
        "px_moved_0_mid(>12)": int((d0 > 12).sum()),
        "meanΔ_mid_end": round(float(np.abs(immid - imend).mean()), 3),
    }


for s in [
    "windmill_16_9",
    "windmill_9_16",
    "waterwheel_16_9",
    "soap_pump_16_9",
    "soap_pump_9_16",
    "clock_gear_16_9",
]:
    print(stats(s))
