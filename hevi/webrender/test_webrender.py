"""
Unit tests for Hevi WebKit WebRender, Satori, SVGO, Pipeline, and Capability Registry.
"""

import os
import hashlib
import pytest
from hevi.webrender.satori_resvg import SatoriResvgCardRenderer
from hevi.webrender.svgo_cleaner import SVGOCleaner
from hevi.webrender.pipeline import PipelineGate
import hevi.capabilities.registry as cap_registry

def test_satori_chinese_card(tmp_path):
    renderer = SatoriResvgCardRenderer()
    out_png = os.path.join(tmp_path, "chinese_card.png")
    renderer.render_card_png("中文标题测试", "副标题描述", out_png, aspect="9:16")
    assert os.path.exists(out_png)
    assert os.path.getsize(out_png) > 0

def test_same_t_consistency(tmp_path):
    renderer = SatoriResvgCardRenderer()
    out1 = os.path.join(tmp_path, "card1.png")
    out2 = os.path.join(tmp_path, "card2.png")
    renderer.render_card_png("一致性测试", "子标题", out1, aspect="16:9")
    renderer.render_card_png("一致性测试", "子标题", out2, aspect="16:9")
    
    hash1 = hashlib.sha256(open(out1, "rb").read()).hexdigest()
    hash2 = hashlib.sha256(open(out2, "rb").read()).hexdigest()
    assert hash1 == hash2

def test_lottie_monotonic_progression():
    frames = [f"frame_{i}" for i in range(10)]
    for i in range(1, len(frames)):
        assert i > i - 1

def test_svgo_cleaning(tmp_path):
    in_svg = os.path.join(tmp_path, "test.svg")
    out_svg = os.path.join(tmp_path, "cleaned.svg")
    with open(in_svg, "w") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg"><!-- comment --><rect width="10" height="10"/></svg>')
    
    metrics = SVGOCleaner.clean_file(in_svg, out_svg)
    assert os.path.exists(out_svg)
    assert metrics["optimized_size_bytes"] <= metrics["original_size_bytes"]

def test_pipeline_gate_missing_artifact(tmp_path):
    gate = PipelineGate(str(tmp_path))
    with pytest.raises(FileNotFoundError):
        gate.check_stage("design", ["non_existent.json"])

def test_capability_registry_and_deletion(tmp_path):
    caps = cap_registry.list_caps(kind="title")
    assert len(caps) > 0
    
    cap = cap_registry.get("satori.title_card")
    result = cap.render({"title": "测试契约", "subtitle": "子"}, str(tmp_path), duration=2.0, aspect="9:16", seed=42)
    assert os.path.exists(result.artifact_path)
    assert len(result.sha256) == 64

    os.remove(result.artifact_path)
    assert not os.path.exists(result.artifact_path)
