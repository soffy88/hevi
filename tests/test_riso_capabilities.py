"""Capability contract tests for RISO templates (CAPABILITY_CONTRACT.md).

Covers:
- All 10 templates discoverable via list_capabilities().
- Parameter schema validation failure on invalid input.
- 2-second video render passes ffprobe checks.
- Output deletion causes validation to fail.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from hevi.capabilities.registry import (
    CapabilityError,
    compute_sha256,
    get,
    list_capabilities,
)
from hevi.riso.constants import TEMPLATE_NAMES
from hevi.riso.render import probe_video


def test_capabilities_registered_and_listable() -> None:
    """All 10 templates must be registered and searchable."""
    all_caps = list_capabilities()
    cap_names = [c.name for c in all_caps]

    for tmpl in TEMPLATE_NAMES:
        expected = f"riso.{tmpl}"
        assert expected in cap_names
        cap = get(expected)
        assert "9:16" in cap.aspects
        assert cap.kind in ("overlay", "shot")


def test_schema_rejects_invalid_params() -> None:
    """Invalid or missing required parameters must raise CapabilityError."""
    versus_cap = get("riso.versus")
    # Missing required 'reality'
    with pytest.raises(CapabilityError, match="Missing required parameter"):
        versus_cap.render(
            {"myth": "某某误区"},
            out_dir="/tmp/dummy",
            duration=2.0,
            aspect="9:16",
            seed=42,
        )

    # Invalid aspect
    with pytest.raises(CapabilityError, match="aspect"):
        versus_cap.render(
            {"myth": "某某误区", "reality": "真相在此"},
            out_dir="/tmp/dummy",
            duration=2.0,
            aspect="16:9",
            seed=42,
        )


def test_render_2s_passes_ffprobe(tmp_path: Path) -> None:
    """Render a 2-second capability video and verify with ffprobe."""
    title_cap = get("riso.title")
    res = title_cap.render(
        {
            "title": "复利的核心积累期",
            "subtitle": "前三年基数奠定终局",
            "number": "01",
        },
        out_dir=tmp_path / "cap_render",
        duration=2.0,
        aspect="9:16",
        seed=123,
    )

    assert res.output_path.exists()
    assert res.duration == 2.0
    assert len(res.sha256) == 64

    # ffprobe check
    info = probe_video(res.output_path)
    streams = info["streams"]
    assert len(streams) >= 1
    vstream = streams[0]
    assert vstream["width"] == 1080
    assert vstream["height"] == 1920
    assert vstream["codec_name"] == "h264"

    # Delete artifact test
    res.output_path.unlink()
    assert not res.output_path.exists()
    with pytest.raises(CapabilityError):
        compute_sha256(res.output_path)
