"""Tests for deferred camera-movement batch B: render mapping (B3)
and duration/grid advisory (B4). Contract/advisory only.
"""

import pytest

from hevi.capabilities import camera_duration_advisory as b4
from hevi.capabilities import camera_render_mapping as b3
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import contains


def test_mapping_full_46_four_supported_42_not_supported():
    entries = b3.list_render_mapping()
    assert len(entries) == 46
    assert len({e["id"] for e in entries}) == 46
    supported = [e for e in entries if e["status"] == "supported"]
    blocked = [e for e in entries if e["status"] == "not_supported"]
    assert len(supported) == 4
    assert len(blocked) == 42
    assert {e["id"] for e in supported} == {
        "static_shot", "orbit_clockwise", "dolly_in", "pan_right",
    }
    for entry in entries:
        # No silent fallback anywhere.
        assert entry["fallback"] is None
        assert entry["reason"]
        if entry["status"] == "not_supported":
            assert entry["renderer_movement"] is None
        else:
            assert entry["direction_verified"] is False


def test_mapping_slow_zoom_legal_but_not_renderable():
    # slow_zoom_in/out are legal vocabulary ids, never banned;
    # they are simply not renderable by the minimal renderer.
    for movement_id in ("slow_zoom_in", "slow_zoom_out"):
        entry = b3.map_movement(movement_id)
        assert entry["status"] == "not_supported"
        assert "focal-length" in entry["reason"]
    with pytest.raises(CapabilityError):
        b3.map_movement("not_a_movement")


def test_mapping_compile_fails_closed_no_fallback():
    with pytest.raises(CapabilityError, match="not_supported"):
        b3.compile_render_mapping({"movement_id": "pan_left"})
    with pytest.raises(CapabilityError, match="not_supported"):
        b3.compile_render_mapping({"movement_id": "tracking_shot"})
    with pytest.raises(CapabilityError, match="disagrees"):
        b3.compile_render_mapping(
            {"movement_id": "dolly_in", "renderer_movement": "orbit"}
        )
    contract = b3.compile_render_mapping({"movement_id": "dolly_in"})
    assert contract["renderer_movement"] == "dolly"
    assert contract["executed_here"] is False
    assert contract["output_file"] is None


def test_advisory_short_beat_min_long_segment_max():
    whip = b4.advise("whip_pan_right")
    assert whip["suggested_duration_s"] == pytest.approx(5.1667, abs=1e-3)
    assert whip["suggested_frames"] == 124
    assert (124 - 5) % 17 == 0
    orbit = b4.advise("orbit_clockwise")
    assert orbit["suggested_duration_s"] == 15.0
    assert orbit["suggested_frames"] == 345
    assert (345 - 5) % 17 == 0
    earth = b4.advise("earth_zoom_out")
    assert earth["suggested_duration_s"] == 15.0
    static = b4.advise("static_shot")
    assert static["suggested_duration_s"] == pytest.approx(10.0833, abs=1e-3)
    for advisory in (whip, orbit, earth, static):
        assert advisory["advisory_only"] is True
        assert advisory["verified_by_hevi_render"] is False


def test_advisory_time_lapse_needs_compression_declaration():
    bare = b4.advise("time_lapse")
    assert bare["needs_time_compression_declaration"] is True
    declared = b4.advise("time_lapse", compression_ratio=60)
    assert declared["needs_time_compression_declaration"] is False
    assert declared["compression_ratio"] == 60
    with pytest.raises(CapabilityError):
        b4.advise("time_lapse", compression_ratio=1)


def test_advisory_unknown_provider_no_invented_numbers():
    advisory = b4.advise("static_shot", provider="no_such_provider")
    assert advisory["tier_status"] == "unknown"
    assert advisory["suggested_duration_s"] is None
    assert advisory["suggested_frames"] is None
    pixstag = b4.advise("static_shot", provider="pixstag")
    assert pixstag["suggested_duration_s"] == 17.0
    assert pixstag["suggested_frames"] is None
    assert "no verified frame basis" in pixstag["frame_basis"]
    with pytest.raises(CapabilityError):
        b4.advise("not_a_movement")


def test_batch2_registered():
    assert contains("video.camera_render_mapping")
    assert contains("qa.camera_duration_advisory")
