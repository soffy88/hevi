"""W4 sound-effect library acceptance tests (SFXBAD_TASK.md section A).

Everything here measures the real files on disk with real ``ffprobe`` /
``ffmpeg ebur128`` - nothing is mocked and no expected value is hard-coded
except the policy constants the generator itself declares.

Run::

    JWT_SECRET=test-secret-local .venv/bin/python -m pytest tests/test_sfx_library.py -q
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB = REPO_ROOT / "assets" / "audio" / "sfx" / "library"
MANIFEST = LIB / "manifest.json"
SCHEMA = LIB / "manifest.schema.json"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "sfx"))

import gen_sfx_library as G  # noqa: E402

TARGET_LUFS = -16.0
LUFS_TOLERANCE = 1.5
MIN_ASSETS = 60


@pytest.fixture(scope="module")
def manifest() -> dict:
    if not MANIFEST.exists():
        pytest.skip(f"{MANIFEST} not built yet")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _ffprobe(path: Path) -> dict:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_name,sample_rate,channels,bits_per_sample",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)


def test_asset_count_and_files_exist(manifest):
    assert manifest["asset_count"] >= MIN_ASSETS, manifest["asset_count"]
    assert len(manifest["assets"]) == manifest["asset_count"]
    missing = [a["file"] for a in manifest["assets"] if not (REPO_ROOT / a["file"]).exists()]
    assert not missing, f"manifest lists missing files: {missing[:5]}"
    wavs = list(LIB.glob("*/*.wav"))
    assert len(wavs) >= MIN_ASSETS, f"only {len(wavs)} wav files on disk"
    # every on-disk wav is accounted for by the manifest
    listed = {a["file"] for a in manifest["assets"]}
    on_disk = {str(p.relative_to(REPO_ROOT)) for p in wavs}
    assert on_disk == listed, f"extra={on_disk - listed} missing={listed - on_disk}"


def test_ffprobe_valid_and_format(manifest):
    for a in manifest["assets"]:
        path = REPO_ROOT / a["file"]
        info = _ffprobe(path)
        stream = info["streams"][0]
        assert stream["codec_name"] == "pcm_s16le", (a["id"], stream["codec_name"])
        assert int(stream["sample_rate"]) == a["sample_rate"]
        assert int(stream["channels"]) == a["channels"]
        assert int(stream["bits_per_sample"]) == 16


def test_duration_range(manifest):
    for a in manifest["assets"]:
        d = a["duration_s"]
        assert 0.1 <= d <= 4.0, (a["id"], d)


def test_true_peak_below_minus_1_dbfs(manifest):
    """Spec: no clipping - true peak strictly below -1 dBFS for every clip."""
    for a in manifest["assets"]:
        assert a["true_peak_dbfs"] < -1.0, (a["id"], a["true_peak_dbfs"])


def test_loudness_policy_measured_with_ebur128(manifest):
    """Re-measure >=0.5s clips with real ffmpeg ebur128 and check the policy.

    A clip is acceptable when either
      * it lands within +/-1.5 LU of -16 LUFS, or
      * it is flagged ``loudness_limited`` (too impulsive to reach -16 LUFS
        without clipping) and is consequently quieter than the target.
    Clips <0.5s must report ``lufs_integrated=null`` and must not be boosted
    into clipping.
    """
    for a in manifest["assets"]:
        path = REPO_ROOT / a["file"]
        lufs, peak = G.measure(path)
        assert peak < -1.0, (a["id"], peak)
        if a["duration_s"] < 0.5:
            assert a["lufs_integrated"] is None, a["id"]
            assert a["loudness_limited"] is False, a["id"]
            continue
        assert a["lufs_integrated"] is not None, a["id"]
        # manifest value must match a fresh measurement
        assert abs(lufs - a["lufs_integrated"]) <= 0.1, (a["id"], lufs, a["lufs_integrated"])
        if abs(lufs - TARGET_LUFS) <= LUFS_TOLERANCE:
            assert a["loudness_limited"] is False, a["id"]
        else:
            assert a["loudness_limited"] is True, (a["id"], lufs)
            assert lufs < TARGET_LUFS, (a["id"], lufs)


def test_manifest_matches_schema(manifest):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    errors = sorted(
        jsonschema.Draft202012Validator(schema).iter_errors(manifest),
        key=lambda e: list(e.path),
    )
    assert not errors, [f"{'/'.join(map(str, e.path))}: {e.message}" for e in errors[:10]]


def test_sha256_matches_file(manifest):
    for a in manifest["assets"]:
        digest = hashlib.sha256((REPO_ROOT / a["file"]).read_bytes()).hexdigest()
        assert digest == a["sha256"], a["id"]


def test_source_provenance(manifest):
    for a in manifest["assets"]:
        assert a["source"].startswith(f"synth:{a['type']}:"), a["id"]
        assert a["mood"] in {"tense", "joyful", "comic", "epic", "calm", "tech"}
        assert a["tags"]


def test_generator_rerun_is_byte_stable(tmp_path):
    """Re-rendering a sample of assets into a scratch dir must reproduce the
    exact same bytes as the committed library (deterministic synthesis)."""
    sample = ["whoosh_air_up", "click_pen", "shutter_single"]
    by_id = {e[1]: e for e in G.CATALOG}
    committed = json.loads(MANIFEST.read_text(encoding="utf-8"))
    committed_sha = {a["id"]: a["sha256"] for a in committed["assets"]}

    for aid in sample:
        out_path, _ = G.render_asset(tmp_path, by_id[aid], G.SEED_DEFAULT)
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        assert digest == committed_sha[aid], aid
