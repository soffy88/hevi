"""Pixel-grounded acceptance tests for the R1D star-sea and fox/wheat fixes."""
from __future__ import annotations

import base64
import io
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, label

from hevi.capabilities.scene3d import _build_spec
from hevi.layer4_legacy.scene3d.renderer import SceneRenderer

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "hevi" / "layer4_legacy" / "scene3d" / "examples"
TEST_OUTPUT = ROOT / ".tmp" / "test_scene3d_r1d_visual"
SEED = 1234
RESOLUTION = 540
STAR_TIMES = (1.3, 6.5, 11.7)
FOX_TIMES = (1.2, 6.0, 10.8)


def _build(capability: str, aspect: str, preset_name: str, *, star_size: float | None = None):
    preset = json.loads((EXAMPLES / preset_name).read_text(encoding="utf-8"))
    spec = _build_spec(
        capability,
        {"resolution": RESOLUTION, "fps": 30, "seed": SEED},
        duration=float(preset["duration_s"]),
        aspect=aspect,
        seed=SEED,
    )
    if star_size is not None:
        spec.weather.star_size = star_size
    return spec


def _capture(spec: Any, label_name: str, times: tuple[float, ...], kind: str) -> list[dict[str, Any]]:
    renderer = SceneRenderer(spec, TEST_OUTPUT / label_name)

    def collect(page):
        rows = []
        for timestamp in times:
            if kind == "stars":
                page.evaluate("(t) => window.__setTime(t)", timestamp)
                png = page.evaluate("() => document.getElementById('c').toDataURL('image/png')")
                diag = page.evaluate("(t) => window.__starScreenSamples([t])[0]", timestamp)
                payload = {
                    "png": png,
                    "stars": [
                        {"i": star["i"], "x": star["x"], "y": star["y"],
                         "radius": star["radius"], "visible": star["visible"]}
                        for star in diag["stars"]
                    ],
                    "planets": diag["planets"],
                }
            else:
                payload = page.evaluate(
                    """(t) => {
                      window.__setTime(t);
                      const face = window.__foxFaceStats([t])[0];
                      return {
                        png: document.getElementById('c').toDataURL('image/png'),
                        headBBox: face.headBBox,
                        subjectBBox: window.__subjectScreenBBox()
                      };
                    }""",
                    timestamp,
                )
            payload["time"] = timestamp
            payload["image"] = np.asarray(
                Image.open(io.BytesIO(base64.b64decode(payload.pop("png").split(",", 1)[1])))
                .convert("RGB")
            )
            if kind == "stars":
                payload["bright_components"] = _star_component_count(payload["image"], payload["planets"])
            rows.append(payload)
        return rows

    return renderer._with_page(collect)


def _luma_delta(image: np.ndarray) -> np.ndarray:
    rgb = image.astype(np.float32) / 255.0
    luminance = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    return luminance - gaussian_filter(luminance, sigma=3.0)


def _star_component_count(image: np.ndarray, planets: list[dict[str, float]]) -> int:
    """Count connected pixels at least 0.25 above their local luminance background."""
    delta = _luma_delta(image)
    mask = delta >= 0.25
    height, width = mask.shape
    pad_x, pad_y = 0.012, 0.012
    for planet in planets:
        x0 = max(0, int((planet["x0"] - pad_x) * width))
        x1 = min(width, int((planet["x1"] + pad_x) * width) + 1)
        y0 = max(0, int((planet["y0"] - pad_y) * height))
        y1 = min(height, int((planet["y1"] + pad_y) * height) + 1)
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = False
    _, components = label(mask, structure=np.ones((3, 3), dtype=np.uint8))
    return int(components)


def _pixel_near(image: np.ndarray, x: float, y: float, radius: int = 2) -> float:
    """Peak local-background contrast around a normalized projected screen point."""
    delta = _luma_delta(image)
    height, width = delta.shape
    px = int(x * width)
    py = int(y * height)
    x0, x1 = max(0, px - radius), min(width, px + radius + 1)
    y0, y1 = max(0, py - radius), min(height, py + radius + 1)
    if x0 >= x1 or y0 >= y1:
        return 0.0
    return float(delta[y0:y1, x0:x1].max())


@lru_cache(maxsize=2)
def _star_samples(aspect: str) -> tuple[dict[str, Any], ...]:
    spec = _build("scene3d.star_sea", aspect, "through_star_sea.json")
    return tuple(_capture(spec, f"stars-{aspect.replace(':', 'x')}", STAR_TIMES, "stars"))


@lru_cache(maxsize=2)
def _fox_samples(aspect: str) -> tuple[dict[str, Any], ...]:
    spec = _build("scene3d.fox_wheat", aspect, "fox_in_wheat.json")
    return tuple(_capture(spec, f"fox-{aspect.replace(':', 'x')}", FOX_TIMES, "fox"))


def test_star_sea_has_pixel_visible_stars_in_both_aspects_at_all_acceptance_times():
    for aspect in ("9:16", "16:9"):
        samples = _star_samples(aspect)
        assert tuple(row["time"] for row in samples) == STAR_TIMES
        for row in samples:
            assert row["bright_components"] >= 40, (
                f"{aspect} t={row['time']}: found only {row['bright_components']} bright star-like components"
            )


def test_star_sea_has_pixel_confirmed_foreground_star_and_a_center_to_offscreen_flyby():
    samples = _star_samples("9:16")
    foreground_found = False
    for row in samples:
        height, width = row["image"].shape[:2]
        for star in row["stars"]:
            if not star["visible"] or star["radius"] < 6.0:
                continue
            if not (0.08 < star["x"] < 0.92 and 0.08 < star["y"] < 0.92):
                continue
            if _pixel_near(row["image"], star["x"], star["y"]) >= 0.08:
                foreground_found = True
                break
        if foreground_found:
            break
    assert foreground_found, "no projected radius>=6px foreground star has a matching bright pixel footprint"

    first, second = samples[0], samples[1]
    second_by_id = {star["i"]: star for star in second["stars"]}
    flyby_found = False
    for star in first["stars"]:
        if not star["visible"] or not (0.20 <= star["x"] <= 0.80 and 0.20 <= star["y"] <= 0.80):
            continue
        later = second_by_id.get(star["i"])
        if later is None:
            continue
        left_frame = later["x"] < 0.0 or later["x"] > 1.0 or later["y"] < 0.0 or later["y"] > 1.0
        if left_frame and _pixel_near(first["image"], star["x"], star["y"]) >= 0.08:
            flyby_found = True
            break
    assert flyby_found, "no pixel-confirmed star travels from the center area off the frame between t=1.3s and t=6.5s"


def test_increasing_star_size_increases_real_pixel_component_count():
    baseline = next(row for row in _star_samples("9:16") if row["time"] == 6.5)
    larger_spec = _build("scene3d.star_sea", "9:16", "through_star_sea.json", star_size=1.5)
    larger = _capture(larger_spec, "stars-9x16-size-1_5", (6.5,), "stars")[0]
    assert larger["bright_components"] > baseline["bright_components"], (
        f"star_size 0.85 -> 1.5 did not increase bright components: "
        f"{baseline['bright_components']} -> {larger['bright_components']}"
    )


def _hsv_fields(image: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    hsv = np.asarray(Image.fromarray(image).convert("HSV"), dtype=np.float32)
    return hsv[:, :, 0] * (360.0 / 255.0), hsv[:, :, 1] / 255.0


def _bbox_pixels(field: np.ndarray, bbox: dict[str, float]) -> np.ndarray:
    height, width = field.shape
    x0 = max(0, int(bbox["x0"] * width))
    x1 = min(width, int(np.ceil(bbox["x1"] * width)))
    y0 = max(0, int(bbox["y0"] * height))
    y1 = min(height, int(np.ceil(bbox["y1"] * height)))
    return field[y0:y1, x0:x1]


def test_fox_is_orange_separated_from_wheat_and_sky_is_blue_in_both_aspects():
    for aspect in ("9:16", "16:9"):
        for row in _fox_samples(aspect):
            image = row["image"]
            hue, saturation = _hsv_fields(image)
            head_hue = _bbox_pixels(hue, row["headBBox"])
            head_sat = _bbox_pixels(saturation, row["headBBox"])
            orange = (head_sat >= 0.55) & (head_hue >= 18.0) & (head_hue <= 32.0)
            assert int(orange.sum()) >= 100, f"{aspect} t={row['time']}: no stable orange head/body pixels"
            assert 18.0 <= float(np.median(head_hue[orange])) <= 32.0
            assert float(head_sat[orange].mean()) >= 0.60

            bbox = row["headBBox"]
            height, width = hue.shape
            x0 = max(0, int(bbox["x0"] * width))
            x1 = min(width, int(np.ceil(bbox["x1"] * width)))
            y0 = max(0, int(bbox["y0"] * height))
            y1 = min(height, int(np.ceil(bbox["y1"] * height)))
            margin = 30
            outer = np.zeros((height, width), dtype=bool)
            outer[max(0, y0-margin):min(height, y1+margin),
                  max(0, x0-margin):min(width, x1+margin)] = True
            outer[y0:y1, x0:x1] = False
            gold_wheat = outer & (saturation >= 0.35) & (hue >= 33.0) & (hue <= 65.0)
            assert int(gold_wheat.sum()) >= 100, f"{aspect} t={row['time']}: surrounding wheat ring was not measurable"
            gold_hue = float(np.median(hue[gold_wheat]))
            orange_hue = float(np.median(head_hue[orange]))
            assert abs(gold_hue - orange_hue) >= 10.0, (
                f"{aspect} t={row['time']}: fox/wheat hue separation only {abs(gold_hue-orange_hue):.1f} degrees"
            )

            top_hue = hue[: int(height * 0.15), :]
            top_sat = saturation[: int(height * 0.15), :]
            colored_sky = top_sat >= 0.20
            assert float(top_sat.mean()) >= 0.25, f"{aspect} t={row['time']}: sky saturation too low"
            assert int(colored_sky.sum()) >= 100
            sky_hue = float(np.median(top_hue[colored_sky]))
            assert 190.0 <= sky_hue <= 230.0, f"{aspect} t={row['time']}: sky hue {sky_hue:.1f} is not blue"
