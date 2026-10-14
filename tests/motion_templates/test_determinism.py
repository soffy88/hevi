"""Determinism tests for Hevi Motion Templates."""

import tempfile
from pathlib import Path
import pytest
from hevi.motion_templates.render import render_with_frame_hashes

SPECS_DIR = Path(__file__).resolve().parents[2] / "hevi" / "motion_templates" / "specs"


@pytest.mark.parametrize("template,spec_file", [
    ("morph_ui", "morph_ui_hevi_pipeline.json"),
    ("timeline_explainer", "timeline_ai_video_evolution.json"),
    ("kinetic_lyrics", "kinetic_bpm_beat_drop.json"),
    ("layer_build", "layer_build_pipeline.json"),
])
def test_frame_hash_determinism(template: str, spec_file: str):
    spec_path = SPECS_DIR / spec_file
    assert spec_path.is_file(), f"Spec {spec_path} must exist"

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        mp4_1 = tmp_path / "run1.mp4"
        mp4_2 = tmp_path / "run2.mp4"

        # Render 1.5 seconds at 15fps (22 frames) for fast, thorough deterministic verification
        res1, hashes1 = render_with_frame_hashes(
            template=template,
            spec=spec_path,
            out_mp4=mp4_1,
            w=540,
            h=960,
            fps=15,
            contact_sheet=False,
        )

        res2, hashes2 = render_with_frame_hashes(
            template=template,
            spec=spec_path,
            out_mp4=mp4_2,
            w=540,
            h=960,
            fps=15,
            contact_sheet=False,
        )

        assert len(hashes1) > 0
        assert len(hashes1) == len(hashes2)
        assert hashes1 == hashes2, f"Template {template} produced mismatched frame hashes across runs"
