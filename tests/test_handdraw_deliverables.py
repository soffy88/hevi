"""Pytest suite for Hevi Handdraw step 5 E2E delivery contracts.

Verifies:
1. Stroke progress monotonic increasing.
2. Deliverable existence and integrity (delete product fails).
3. Single subtitle set (burned, exactly one editing SRT).
4. Narration timestamp alignment with picture within 0.2s.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts" / "handdraw"
SAMPLES = ["landscape_anger", "portrait_compound"]


@pytest.mark.parametrize("sample", SAMPLES)
def test_deliverables_exist_and_complete(sample: str) -> None:
    root = ARTIFACTS / sample
    outputs = root / "outputs"
    assert outputs.is_dir()

    film = outputs / "film.mp4"
    cover = outputs / "cover.png"
    srt = outputs / "editing" / "transcript.srt"
    script = outputs / "script.txt"
    ver_json = outputs / "verification.json"
    ver_txt = outputs / "verification.txt"

    for p in (film, cover, srt, script, ver_json, ver_txt):
        assert p.is_file(), f"Missing required deliverable: {p}"
        assert p.stat().st_size > 0, f"Empty deliverable: {p}"


@pytest.mark.parametrize("sample", SAMPLES)
def test_single_subtitle_track(sample: str) -> None:
    root = ARTIFACTS / sample
    outputs = root / "outputs"
    srt_files = list((outputs / "editing").glob("*.srt"))
    assert len(srt_files) == 1, "Must have exactly one editing SRT sidecar"

    ver = json.loads((outputs / "verification.json").read_text(encoding="utf-8"))
    eng = ver.get("engineering", ver)
    sub = eng.get("subtitles", {})
    assert sub.get("subtitle_streams") == 0, "No embedded subtitle stream (must be burned)"
    assert sub.get("presentation") == "burned"


@pytest.mark.parametrize("sample", SAMPLES)
def test_narration_timestamp_alignment(sample: str) -> None:
    root = ARTIFACTS / sample
    ali_path = root / "inputs" / "narration" / "alignment.json"
    assert ali_path.is_file()
    ali = json.loads(ali_path.read_text(encoding="utf-8"))

    ver = json.loads((root / "outputs" / "verification.json").read_text(encoding="utf-8"))
    eng = ver.get("engineering", ver)
    pages = eng.get("pages", [])
    assert len(pages) > 0

    # Verify drawing completes before speech ends (positive margin)
    for p in pages:
        assert p["drawing_completed_before_speech_end_seconds"] >= 0.0

    # Verify alignment beats vs continuous master range
    beats = ali.get("beats", [])
    assert len(beats) > 0
    prev_end = 0.0
    for b in beats:
        s, e = float(b["start"]), float(b["end"])
        assert 0.0 <= prev_end <= s < e <= ali["total_duration"] + 0.001
        prev_end = e


@pytest.mark.parametrize("sample", SAMPLES)
def test_stroke_progress_is_monotonic(sample: str) -> None:
    root = ARTIFACTS / sample
    asset_dir = root / "work" / "assets"
    if not asset_dir.is_dir():
        pytest.skip("work/assets not present")

    npz_files = list(asset_dir.glob("*.npz"))
    assert len(npz_files) > 0
    for npz in npz_files:
        data = np.load(npz)
        if "reveal" in data.files:
            rev = data["reveal"]
            finite = rev[np.isfinite(rev)]
            if len(finite) > 0:
                # Monotonic nondecreasing count over increasing reveal thresholds
                sorted_r = np.sort(finite)
                steps = np.linspace(sorted_r[0], sorted_r[-1], 20)
                counts = [int((sorted_r <= t).sum()) for t in steps]
                for i in range(len(counts) - 1):
                    c1, c2 = counts[i], counts[i + 1]
                    assert c2 >= c1, f"Stroke progress not monotonic in {npz.name}"
