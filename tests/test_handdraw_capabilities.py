"""Pytest suite for Hevi Handdraw capability registry and contract."""

from __future__ import annotations

from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.registry import CapabilityError


def test_registry_lists_handdraw_capabilities() -> None:
    names = caps.names()
    assert "handdraw.full" in names
    assert "handdraw.storyboard" in names
    assert "handdraw.narration" in names
    assert "handdraw.illustration" in names

    lines = caps.list(kind="line")
    assert any(c.name == "handdraw.full" for c in lines)

    port = caps.list(aspect="9:16")
    assert len(port) >= 4


def test_capability_schema_validation_rejects_invalid_params() -> None:
    cap = caps.get("handdraw.full")
    # Missing required 'aspect' or 'topic'
    with pytest.raises(CapabilityError):
        cap.validate_params({})

    with pytest.raises(CapabilityError):
        cap.validate_params({"topic": "测试"})

    # Invalid enum for style_id
    with pytest.raises(CapabilityError):
        cap.validate_params({"topic": "测试", "aspect": "16:9", "style_id": "99"})

    # Valid params
    clean = cap.validate_params({"topic": "测试主题", "aspect": "16:9", "style_id": "8", "hand_preset": "navy"})
    assert clean["topic"] == "测试主题"
    assert clean["aspect"] == "16:9"


def test_handdraw_illustration_capability_render(tmp_path: Path) -> None:
    cap = caps.get("handdraw.illustration")
    params = cap.validate_params({"topic": "生气决定", "aspect": "16:9", "style_id": "8"})
    res = cap.render(params, tmp_path, duration=0, aspect="16:9", seed=42)
    assert res.png is not None
    assert res.png.is_file()
    assert res.png.stat().st_size > 0
    assert res.sha256 is not None
    assert res.qa_report.get("style_id") == "8"
