from __future__ import annotations

import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import pytest

from hevi.layer4_legacy.quoteimage.omodul_impl.quality_gates import (
    QualityGateError,
    run_quality_gates,
)
from hevi.layer4_legacy.quoteimage.omodul_impl.produce import produce_quote_image
from hevi.layer4_legacy.quoteimage.oprim_impl.detect_band import detect_subtitle_band


def _create_fixture_good_image(path: Path) -> Path:
    """Generate a realistic quote image with safe margins, crisp subtitles, and varying strips."""
    width, height = 1080, 1440
    img = Image.new("RGB", (width, height))

    # Upper hero section with realistic gradient/contrast
    import numpy as np
    hero_arr = np.linspace(30, 220, 900, dtype=np.uint8)[:, None]
    hero_arr = np.repeat(hero_arr, width, axis=1)
    img.paste(Image.fromarray(hero_arr).convert("RGB"), (0, 0))

    draw = ImageDraw.Draw(img)
    draw.text((200, 400), "HERO MAIN FRAME", fill=(255, 255, 255))

    # Lower section: 4 distinct subtitle strips (y: 900..1440, each 135px)
    subtitles = [
        "第一句台词：时间是最好的朋友",
        "第二句台词：复利让收益持续增长",
        "第三句台词：保持长期耐心与定投",
        "第四句台词：控制成本并避免中断",
    ]
    colors = [(35, 40, 50), (40, 45, 55), (32, 38, 48), (38, 42, 52)]

    # Try Noto Sans CJK or fallback
    try:
        font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 52)
    except Exception:
        font = ImageFont.load_default()

    for i, (text, bg_col) in enumerate(zip(subtitles, colors)):
        y0 = 900 + i * 135
        y1 = y0 + 135
        draw.rectangle([0, y0, width, y1], fill=bg_col)
        # Center text well within safe margins (margin > 100px from both sides)
        draw.text((120, y0 + 35), text, fill=(255, 255, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0))
        # Draw some subtle divider line
        draw.line([0, y0, width, y0], fill=(60, 68, 80), width=2)

    img.save(path, quality=95)
    return path


def _create_fixture_truncated_image(path: Path) -> Path:
    """Generate an image where subtitle text is truncated at the left edge."""
    width, height = 1080, 1440
    img = Image.new("RGB", (width, height), (30, 34, 42))
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, width, 900], fill=(45, 52, 64))

    try:
        font = ImageFont.truetype("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 52)
    except Exception:
        font = ImageFont.load_default()

    # Text starting right at x=0 (touching the border, creating high border edge density)
    for i in range(4):
        y0 = 900 + i * 135
        y1 = y0 + 135
        draw.rectangle([0, y0, width, y1], fill=(35, 40, 50))
        # Text starts at x=0 crossing border margin
        draw.text((0, y0 + 35), "截断台词测试文本跨界超长显示", fill=(255, 255, 255), font=font, stroke_width=2, stroke_fill=(0, 0, 0))

    img.save(path, quality=95)
    return path


def test_quality_gates_real_fixtures(tmp_path: Path):
    good_img_path = tmp_path / "01_quote_image.jpg"
    _create_fixture_good_image(good_img_path)

    gates = run_quality_gates([good_img_path])
    assert gates, "Quality gates should return evaluations"
    for g in gates:
        assert g["passed"], f"Gate '{g['name']}' failed on good fixture: {g}"

    # Verify contact sheet does not participate in resolution gate
    sheet_path = tmp_path / "final_contact_sheet.jpg"
    sheet_img = Image.new("RGB", (360, 270), (40, 40, 40))
    sheet_img.save(sheet_path)

    sheet_gates = run_quality_gates([sheet_path])
    res_gates = [g for g in sheet_gates if g["name"] == "resolution"]
    assert not res_gates, "final_contact_sheet should not participate in resolution gate"


def test_quality_gates_truncation_detection(tmp_path: Path):
    trunc_img_path = tmp_path / "truncated.jpg"
    _create_fixture_truncated_image(trunc_img_path)

    gates = run_quality_gates([trunc_img_path])
    trunc_gate = next(g for g in gates if g["name"] == "subtitle_truncation")
    assert not trunc_gate["passed"], "Truncated fixture must fail subtitle_truncation gate"


def test_quality_gates_empty_image(tmp_path: Path):
    bad_img_path = tmp_path / "empty.jpg"
    img = Image.new("RGB", (1080, 1440), (100, 100, 100))
    img.save(bad_img_path)

    gates = run_quality_gates([bad_img_path])
    completeness = next(g for g in gates if g["name"] == "subtitle_completeness")
    assert not completeness["passed"], "Solid gray image must fail completeness check"


def test_detect_subtitle_band_fallback():
    # Less than 2 times should fall back cleanly
    top, bottom = detect_subtitle_band(video_path="nonexistent.mp4", times=[1.0])
    assert top == 0.78
    assert bottom == 0.96


def test_produce_time_range_with_real_gates(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import hevi.layer4_legacy.quoteimage.omodul_impl.produce as produce_mod

    # Pre-populate a good image in output dir so quality gates run for real on it
    out_img = tmp_path / "quote_script.jpg"
    _create_fixture_good_image(out_img)

    # Monkeypatch only the ffmpeg render command, NOT quality gates!
    monkeypatch.setattr(produce_mod, "command_render_script", lambda args: None)

    script_lines = [
        {"t": 1.0, "text": "第一句台词"},
        {"t": 2.0, "text": "第二句台词"},
        {"t": 3.0, "text": "第三句台词"},
        {"t": 4.0, "text": "第四句台词"},
    ]

    res = produce_quote_image(
        video_path=Path("dummy.mp4"),
        mode="script",
        strategy="time_range",
        output_dir=tmp_path,
        script=script_lines,
        band_top=0.78,
        band_bottom=0.96,
        start_time=1.0,
        end_time=4.0,
    )

    assert res["status"] == "succeeded"
    record = json.loads((tmp_path / "record.json").read_text(encoding="utf-8"))
    assert record["status"] == "succeeded"
    assert record["records"][0]["times"] == [1.0, 2.0, 3.0, 4.0]
    # Verify gates were genuinely executed and passed
    gates = record["records"][0]["gates"]
    assert len(gates) > 0
    assert all(g["passed"] for g in gates)


def test_produce_gate_failure_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import hevi.layer4_legacy.quoteimage.omodul_impl.produce as produce_mod

    # Pre-populate a bad empty image so quality gates FAIL
    out_img = tmp_path / "quote_script.jpg"
    img = Image.new("RGB", (1080, 1440), (100, 100, 100))
    img.save(out_img)

    monkeypatch.setattr(produce_mod, "command_render_script", lambda args: None)

    script_lines = [
        {"t": 1.0, "text": "第一句台词"},
        {"t": 2.0, "text": "第二句台词"},
    ]

    with pytest.raises(QualityGateError):
        produce_quote_image(
            video_path=Path("dummy.mp4"),
            mode="script",
            strategy="time_range",
            output_dir=tmp_path,
            script=script_lines,
            band_top=0.78,
            band_bottom=0.96,
            start_time=1.0,
            end_time=2.0,
        )

    record = json.loads((tmp_path / "record.json").read_text(encoding="utf-8"))
    assert record["status"] == "failed"

