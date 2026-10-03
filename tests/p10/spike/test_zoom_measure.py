"""zoom_measure 校准:程序化合成已知尺度 fixture(构造即真值,无人工标注)。"""

import numpy as np
from PIL import Image

from hevi.verdict.zoom_measure import estimate_scale_change, load_gray


def _pattern(w: int = 640, h: int = 360, seed: int = 7) -> Image.Image:
    rng = np.random.default_rng(seed)
    noise = (rng.random((h, w)) * 255).astype("uint8")
    return Image.fromarray(noise).convert("RGB")


def test_calibration_known_zoom_out(tmp_path):
    base = _pattern()
    f0 = tmp_path / "cal_f0.png"
    base.save(f0)
    zw, zh = int(640 * 0.667), int(360 * 0.667)
    small = base.resize((zw, zh), Image.BILINEAR)
    canvas = Image.new("RGB", (640, 360), (0, 0, 0))
    canvas.paste(small, ((640 - zw) // 2, (360 - zh) // 2))
    f1 = tmp_path / "cal_f1.png"
    canvas.save(f1)
    s, conf = estimate_scale_change(load_gray(str(f0)), load_gray(str(f1)))
    assert abs(s - 0.667) <= 0.05, f"scale {s} off truth 0.667"
    assert conf >= 0.5, f"confidence {conf} too low"


def test_calibration_static_is_one(tmp_path):
    f0 = tmp_path / "static.png"
    _pattern().save(f0)
    s, conf = estimate_scale_change(load_gray(str(f0)), load_gray(str(f0)))
    assert s == 1.0 and conf > 0.99
