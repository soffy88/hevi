import pytest
from pathlib import Path
from PIL import Image, ImageDraw
import json
import tempfile
from hevi.layer4_legacy.quoteimage.omodul_impl.quality_gates import run_quality_gates
from hevi.layer4_legacy.quoteimage.omodul_impl.produce import produce_quote_image

def test_quality_gates_bad_image(tmp_path):
    # Create a blurry/empty image simulating bad crop
    bad_img_path = tmp_path / "bad.jpg"
    img = Image.new("RGB", (720, 1280), (100, 100, 100))
    img.save(bad_img_path)
    
    gates = run_quality_gates([bad_img_path])
    
    completeness = next(g for g in gates if g["name"] == "subtitle_completeness")
    assert not completeness["passed"], "Empty/blurry image should fail completeness check"
    
def test_quality_gates_good_image(tmp_path):
    # Create an image with text simulating good crop
    good_img_path = tmp_path / "good.jpg"
    img = Image.new("RGB", (720, 1280), (100, 100, 100))
    draw = ImageDraw.Draw(img)
    # draw some sharp edges
    for i in range(100):
        draw.line((100, 1000+i, 600, 1000+i), fill=(255,255,255))
        draw.line((100+i, 1000, 100+i, 1200), fill=(255,255,255))
    img.save(good_img_path)
    
    gates = run_quality_gates([good_img_path])
    
    completeness = next(g for g in gates if g["name"] == "subtitle_completeness")
    assert completeness["passed"], "Image with text should pass completeness check"

# We can mock WhisperAligner to test time range strategy
class MockWhisperAligner:
    def transcribe_segments(self, path):
        return [
            {"t": 1.0, "text": "One"},
            {"t": 2.0, "text": "Two"},
            {"t": 3.0, "text": "Three"},
            {"t": 4.0, "text": "Four"},
            {"t": 5.0, "text": "Five"}
        ]

def test_produce_time_range(monkeypatch, tmp_path):
    import hevi.layer4_legacy.quoteimage.omodul_impl.produce as produce
    monkeypatch.setattr(produce, "WhisperAligner", MockWhisperAligner)
    monkeypatch.setattr(produce, "command_render", lambda x: None)
    monkeypatch.setattr(produce, "command_render_script", lambda x: None)
    monkeypatch.setattr(produce, "detect_subtitle_band", lambda x, y: (0.1, 0.2))
    
    # mock quality gates so it doesn't fail on missing images
    monkeypatch.setattr(produce, "run_quality_gates", lambda x: [])

    # test time range
    res = produce_quote_image(
        video_path=Path("dummy.mp4"),
        mode="native",
        strategy="time_range",
        output_dir=tmp_path,
        start_time=2.0,
        end_time=4.0
    )
    
    assert res["status"] == "succeeded"
    record = json.loads((tmp_path / "record.json").read_text())
    assert record["records"][0]["times"] == [2.0, 3.0, 4.0]
    
    # test dummy fallback removal (error when no sentences picked)
    res_fail = produce_quote_image(
        video_path=Path("dummy.mp4"),
        mode="native",
        strategy="time_range",
        output_dir=tmp_path,
        start_time=10.0,
        end_time=20.0
    )
    assert res_fail["status"] == "failed"

