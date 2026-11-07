"""Tests for design.cover_family: pinned spec plus 200px gate."""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from hevi.capabilities.cover_family import (
    check_readability,
    contrast_ratio,
    define_cover_spec,
    thumbnail_legibility_check,
)
from hevi.capabilities.errors import CapabilityError


def _spec(**overrides) -> dict:
    spec = {
        "primary_color": "#1a3a5c",
        "secondary_color": "#f2c14e",
        "title_color": "#ffffff",
        "background_color": "#111111",
        "font_family": "Noto Sans SC",
        "title_zone": {"x": 0.08, "y": 0.15, "w": 0.84, "h": 0.40},
        "brand_zone": {"x": 0.08, "y": 0.85, "w": 0.30, "h": 0.08},
    }
    spec.update(overrides)
    return define_cover_spec(**spec)


def test_black_on_white_contrast_is_21() -> None:
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)


def test_readable_cover_passes_200px_projection() -> None:
    report = check_readability(
        _spec(), title_text="三天练好一个曲子", title_font_size_px=90)
    assert report["verdict"] == "pass"
    assert report["scaled_title_px_at_200"] == pytest.approx(16.67, abs=0.01)
    assert report["visual_proof"] is False


def test_small_title_fails_at_200px() -> None:
    report = check_readability(
        _spec(), title_text="三天练好一个曲子", title_font_size_px=50)
    assert report["verdict"] == "fail"
    assert report["checks"]["scaled_title_size"]["pass"] is False


def test_low_contrast_fails() -> None:
    spec = _spec(title_color="#888888", background_color="#999999")
    report = check_readability(
        spec, title_text="三天练好一个曲子", title_font_size_px=90)
    assert report["verdict"] == "fail"
    assert report["checks"]["contrast"]["pass"] is False


def test_no_image_report_states_its_limitation_plainly() -> None:
    report = thumbnail_legibility_check(
        _spec(), title_text="三天练好一个曲子", title_font_size_px=90)
    assert report["image_check"]["performed"] is False
    assert "does NOT prove" in report["limitation"]
    assert report["visual_proof"] is False


def test_overlapping_zones_are_rejected() -> None:
    with pytest.raises(CapabilityError, match="overlap"):
        _spec(brand_zone={"x": 0.10, "y": 0.20, "w": 0.30, "h": 0.10})


def test_bad_hex_is_rejected() -> None:
    with pytest.raises(CapabilityError, match="hex"):
        _spec(primary_color="blue")


def test_image_zone_signal_distinguishes_blank_from_filled(
        tmp_path) -> None:
    spec = _spec()
    blank = tmp_path / "blank.png"
    Image.new("RGB", (1080, 1920), "white").save(blank)
    blank_report = thumbnail_legibility_check(
        spec, title_text="三天练好一个曲子", title_font_size_px=90,
        image_path=blank)
    assert blank_report["image_check"]["not_blank"] is False

    filled = tmp_path / "filled.png"
    image = Image.new("RGB", (1080, 1920), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([90, 300, 990, 1050], fill="black")
    image.save(filled)
    filled_report = thumbnail_legibility_check(
        spec, title_text="三天练好一个曲子", title_font_size_px=90,
        image_path=filled)
    assert filled_report["image_check"]["not_blank"] is True
    assert "not sufficient" in filled_report["image_check"]["note"]
