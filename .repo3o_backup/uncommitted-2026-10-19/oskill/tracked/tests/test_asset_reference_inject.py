"""Tests for asset_reference_inject."""

from __future__ import annotations

from oskill._asset_reference_inject import asset_reference_inject


def _loader(asset_type: str, asset_id: str) -> dict:
    """Fake Layer4 asset loader."""
    return {
        "id": asset_id,
        "type": asset_type,
        "data": f"resolved_{asset_id}",
    }


class TestAssetReferenceInject:
    def test_returns_enhanced_shot_spec(self):
        spec = {"duration_s": 5.0}
        result = asset_reference_inject(
            shot_spec=spec,
            asset_refs={"character_id": "char_001"},
            asset_loader=_loader,
        )
        assert "_assets" in result

    def test_character_resolved_via_loader(self):
        result = asset_reference_inject(
            shot_spec={},
            asset_refs={"character_id": "char_001"},
            asset_loader=_loader,
        )
        assert result["_assets"]["character_id"]["id"] == "char_001"

    def test_scene_resolved_via_loader(self):
        result = asset_reference_inject(
            shot_spec={},
            asset_refs={"scene_id": "scene_beach"},
            asset_loader=_loader,
        )
        assert result["_assets"]["scene_id"]["data"] == "resolved_scene_beach"

    def test_voice_id_resolved(self):
        result = asset_reference_inject(
            shot_spec={},
            asset_refs={"voice_id": "voice_narrator"},
            asset_loader=_loader,
        )
        assert "voice_id" in result["_assets"]

    def test_loader_none_injects_raw_refs(self):
        result = asset_reference_inject(
            shot_spec={"duration_s": 3.0},
            asset_refs={"character_id": "char_007", "scene_id": "scene_002"},
            asset_loader=None,
        )
        assets = result["_assets"]
        assert assets["character_id"] == "char_007"
        assert assets["scene_id"] == "scene_002"

    def test_shot_spec_not_mutated(self):
        original = {"duration_s": 5.0, "prompt": "test"}
        result = asset_reference_inject(
            shot_spec=original,
            asset_refs={"voice_id": "v1"},
            asset_loader=_loader,
        )
        assert "_assets" not in original
        assert result is not original

    def test_empty_asset_id_skipped(self):
        result = asset_reference_inject(
            shot_spec={},
            asset_refs={"character_id": "", "scene_id": "s1"},
            asset_loader=_loader,
        )
        assert "character_id" not in result["_assets"]
        assert "scene_id" in result["_assets"]

    def test_multiple_refs_all_injected(self):
        refs = {"character_id": "c1", "scene_id": "s1", "voice_id": "v1"}
        result = asset_reference_inject(shot_spec={}, asset_refs=refs, asset_loader=_loader)
        assert len(result["_assets"]) == 3

    def test_loader_exception_falls_back_to_raw_id(self):
        def bad_loader(asset_type, asset_id):
            raise ConnectionError("DB offline")

        result = asset_reference_inject(
            shot_spec={},
            asset_refs={"character_id": "char_fail"},
            asset_loader=bad_loader,
        )
        # Falls back to raw id on exception
        assert result["_assets"]["character_id"] == "char_fail"

    def test_original_shot_spec_fields_preserved(self):
        spec = {"duration_s": 7.0, "prompt": "action scene"}
        result = asset_reference_inject(
            shot_spec=spec,
            asset_refs={"character_id": "hero"},
            asset_loader=None,
        )
        assert result["duration_s"] == 7.0
        assert result["prompt"] == "action scene"
