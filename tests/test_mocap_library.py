"""Offline contract tests for the internalised CMU motion library.

Validates ``assets/mocap-clips/manifest.json`` against the clip files on disk
(CAPABILITY_CONTRACT test style: registration visible, artifacts exist and are
well-formed, deleting an artifact must fail the test).  No network access.
"""

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MOCAP_ROOT = REPO / "assets" / "mocap-clips"
MANIFEST = MOCAP_ROOT / "manifest.json"
CLIP_DIR = MOCAP_ROOT / "clips"

JOINTS = {
    "hips", "chest", "neck", "head",
    "shR", "elR", "haR", "shL", "elL", "haL",
    "hipR", "knR", "ftR", "hipL", "knL", "ftL",
}


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert MANIFEST.is_file(), "manifest.json missing — run hevi.studio.mocap_manifest"
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_manifest_parses_and_covers_phase2_actions(manifest: dict) -> None:
    assert manifest["skeleton"] == "cmu-2d-16joints"
    assert set(manifest["joints"]) == JOINTS
    assert "CMU Graphics Lab" in manifest["license"]
    assert "NSF EIA-0196217" in manifest["license"]
    assert manifest["motion_count"] == len(manifest["motions"])
    names = {m["name"] for m in manifest["motions"]}
    # the ten actions targeted by the motion-library internalisation
    assert {
        "walk", "run", "sprint", "punch", "kick", "roll",
        "knockdown", "getup", "victory", "dance_spin", "dance_glide",
    } <= names


def test_manifest_entries_have_provenance(manifest: dict) -> None:
    for m in manifest["motions"]:
        assert m["name_cn"], m
        assert m["category"], m
        assert m["source"].startswith("CMU "), m
        assert m["file"].endswith(".json"), m
        assert m["fps"] == 30.0, m
        assert m["frames"] > 0, m
        assert m["duration_s"] > 0, m
        assert "CMU Graphics Lab" in m["license"], m


def test_every_manifest_clip_file_exists_and_is_wellformed(manifest: dict) -> None:
    for m in manifest["motions"]:
        path = REPO / m["file"]
        assert path.is_file(), f"clip file missing (delete must fail): {path}"
        clip = json.loads(path.read_text(encoding="utf-8"))
        assert clip["name"] == m["name"]
        assert clip["source"] == m["source"]
        assert clip["fps"] == m["fps"]
        assert clip["frameCount"] == m["frames"] == len(clip["frames"])
        assert clip["label"]
        for frame in clip["frames"]:
            assert set(frame.keys()) == JOINTS
            for pt in frame.values():
                assert len(pt) == 2


def test_manifest_matches_clips_dir_no_drift(manifest: dict) -> None:
    on_disk = {p.stem for p in CLIP_DIR.glob("*.json")}
    in_manifest = {m["name"] for m in manifest["motions"]}
    assert on_disk == in_manifest


def test_trials_table_covers_all_clips(manifest: dict) -> None:
    from hevi.studio.cmumocap import TRIALS

    for m in manifest["motions"]:
        assert m["name"] in TRIALS, f"{m['name']} not registered in cmumocap.TRIALS"


def test_studio_catalogue_sees_all_clips(manifest: dict) -> None:
    from hevi.studio.mocap import list_mocap

    listed = {item["name"] for item in list_mocap(root=REPO / "assets")}
    assert listed == {m["name"] for m in manifest["motions"]}
