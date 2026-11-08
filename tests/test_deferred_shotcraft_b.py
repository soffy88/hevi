"""Tests for deferred shotcraft batch B: Remotion bridge contract (B3)
and theme catalog schema (B4). Contract layer only; nothing renders.
"""

import pytest

from hevi.capabilities import remotion_bridge_contract as b3
from hevi.capabilities import shotcraft_theme_catalog as b4
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import contains


def _plan(**overrides):
    plan = {
        "card": "assemble-then-type-flyin",
        "theme": "Modern Light",
        "composition": "MotionGraphics",
        "grid": {"width": 1920, "height": 1080, "fps": 30, "frames": 1085},
    }
    plan.update(overrides)
    return plan


def test_bridge_contract_positive():
    contract = b3.compile_remotion_bridge_contract(_plan())
    assert contract["card"] == "assemble-then-type-flyin"
    assert contract["theme"] == "Modern Light"
    assert contract["executed_here"] is False
    assert contract["rendered_here"] is False
    assert contract["output_file"] is None
    assert contract["verification"]["mp4_produced"] is False
    assert "EACCES" in contract["verification"]["error"]
    assert contract["verification"]["outcome"] == "blocked_before_render"


def test_bridge_contract_shots_checked():
    plan = _plan(shots=[
        {"card": "assemble-then-type-flyin", "start_frame": 0, "end_frame": 90},
    ])
    contract = b3.compile_remotion_bridge_contract(plan)
    assert len(contract["shots"]) == 1
    with pytest.raises(CapabilityError):
        b3.compile_remotion_bridge_contract(_plan(shots=[
            {"card": "assemble-then-type-flyin", "start_frame": 90, "end_frame": 90},
        ]))
    with pytest.raises(CapabilityError):
        b3.compile_remotion_bridge_contract(_plan(shots=[
            {"card": "not-a-tuned-card", "start_frame": 0, "end_frame": 10},
        ]))


def test_bridge_contract_rejects_unknown_card_and_theme():
    with pytest.raises(CapabilityError):
        b3.compile_remotion_bridge_contract(_plan(card="dolly-in-reveal"))
    with pytest.raises(CapabilityError):
        b3.compile_remotion_bridge_contract(_plan(theme="Neon Sunset"))
    with pytest.raises(CapabilityError):
        b3.compile_remotion_bridge_contract(_plan(grid={"width": 0, "height": 1080, "fps": 30, "frames": 10}))


def test_bridge_contract_ink_press_no_recolour():
    with pytest.raises(CapabilityError):
        b3.compile_remotion_bridge_contract(
            _plan(theme="Ink Press", palette_override={"accent": "#ff0000"})
        )
    contract = b3.compile_remotion_bridge_contract(_plan(theme="Ink Press"))
    assert contract["theme"] == "Ink Press"


def test_theme_catalog_nine_presets_no_values():
    catalog = b4.compile_theme_catalog()
    assert catalog["preset_count"] == 9
    assert len(catalog["presets"]) == 9
    assert catalog["palette_values_asserted"] is False
    assert catalog["executed_here"] is False
    for entry in catalog["presets"]:
        assert entry["palette_values"] is None
        assert entry["palette_fields"] == list(b4.PALETTE_FIELDS)
    assert catalog["palette_precedence"] == [
        "schema_default", "preset_default", "project_palette",
        "explicit_clip_edit",
    ]


def test_theme_catalog_ink_press_locked_others_not():
    ink = b4.compile_theme_catalog({"theme": "Ink Press"})
    assert ink["presets"][0]["recolour_locked"] is True
    for name in ("Modern Light", "Midnight", "Sage", "Coral", "Iris",
                 "Deep Ocean", "Obsidian Violet", "Vintage Kraft"):
        entry = b4.compile_theme_catalog({"theme": name})["presets"][0]
        assert entry["recolour_locked"] is False
    with pytest.raises(CapabilityError):
        b4.compile_theme_catalog({"theme": "Neon Sunset"})


def test_batch1_registered():
    assert contains("video.remotion_bridge_contract")
    assert contains("video.shotcraft_theme_catalog")
