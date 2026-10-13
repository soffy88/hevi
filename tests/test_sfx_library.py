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
import wave
from pathlib import Path

import numpy as np
import pytest
from scipy.signal import stft

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB = REPO_ROOT / "assets" / "audio" / "sfx" / "library"
MANIFEST = LIB / "manifest.json"
SCHEMA = LIB / "manifest.schema.json"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "sfx"))

import gen_sfx_library as G  # noqa: E402
import sfx_synth as S  # noqa: E402

TARGET_LUFS = -16.0
LUFS_TOLERANCE = 1.5
MIN_ASSETS = 60
SAMPLE_RATE = 44100

# FIX item 2b: two same-type assets are "distinct" when the cosine similarity
# of the concatenated (mean-spectrum, envelope) feature is at most this.
SIMILARITY_MAX = 0.99


# ---------------------------------------------------------------------------
# spectral feature helpers (FIX item 2)
# ---------------------------------------------------------------------------


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0


def _centroid_slope(x: np.ndarray, sr: int = SAMPLE_RATE) -> float:
    """Least-squares slope (Hz/s) of the STFT spectral centroid over time.

    A rising sweep gives a positive slope, a falling sweep a negative one.
    """
    f, t, z = stft(x, sr, nperseg=2048, noverlap=1536)
    mag = np.abs(z)
    centroid = (mag * f[:, None]).sum(axis=0) / (mag.sum(axis=0) + 1e-12)
    return float(np.polyfit(t, centroid, 1)[0])


def _spectral_envelope_features(
    x: np.ndarray, nbands: int = 32, nseg: int = 20, sr: int = SAMPLE_RATE
):
    """32 log-band mean spectrum (mean-removed, L2-normalised) + 20-segment
    normalised envelope.  Each half is unit-norm so the cosine of the
    concatenation is the average of the two cosines."""
    f, _, z = stft(x, sr, nperseg=2048, noverlap=1024)
    mean_spec = np.abs(z).mean(axis=1)
    edges = np.geomspace(40.0, sr / 2.0, nbands + 1)
    bands = np.array(
        [mean_spec[(f >= lo) & (f < hi)].sum() for lo, hi in zip(edges[:-1], edges[1:])]
    )
    bands = bands - bands.mean()
    nb = float(np.linalg.norm(bands))
    if nb > 0:
        bands = bands / nb
    env = np.array([seg.mean() for seg in np.array_split(np.abs(x), nseg)])
    env = env - env.mean()
    ne = float(np.linalg.norm(env))
    if ne > 0:
        env = env / ne
    return bands, env


def _cos(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def _combined_similarity(x: np.ndarray, y: np.ndarray) -> float:
    b1, e1 = _spectral_envelope_features(x)
    b2, e2 = _spectral_envelope_features(y)
    return 0.5 * _cos(b1, b2) + 0.5 * _cos(e1, e2)


def _parse_source(src: str) -> dict:
    """``synth:<type>:k=v;k=v`` -> {k: float} (float where parseable)."""
    parts = src.split(":", 2)[2]
    out: dict = {}
    for kv in parts.split(";"):
        k, _, v = kv.partition("=")
        try:
            out[k] = float(v)
        except ValueError:
            out[k] = v
    return out


def _sweep_endpoints(a: dict):
    """Return (f_lo_end, f_hi_end) for the swept assets, else None.

    whoosh/swipe carry ``f0``/``f1``; riser/downer carry ``f_start``/``f_end``.
    """
    src = _parse_source(a["source"])
    if "f0" in src and "f1" in src:
        return float(src["f0"]), float(src["f1"])
    if "f_start" in src and "f_end" in src:
        return float(src["f_start"]), float(src["f_end"])
    return None


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

    Every clip >=0.5s must land within +/-1.5 LU of -16 LUFS *integrated*
    (no exemption: the loudness_limited escape hatch is gone - each such clip
    now carries a sustained body bed that lifts its integrated loudness).
    Clips <0.5s must report ``lufs_integrated=null``, be peak-normalised and
    must not clip.
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
        assert abs(lufs - TARGET_LUFS) <= LUFS_TOLERANCE, (a["id"], lufs)
        assert a["loudness_limited"] is False, a["id"]


def test_no_loudness_limited_exemption(manifest):
    """FIX item 3: the ``loudness_limited`` exemption must be fully retired."""
    limited = [a["id"] for a in manifest["assets"] if a["loudness_limited"]]
    assert limited == [], f"assets still flagged loudness_limited: {limited}"
    longs = [a for a in manifest["assets"] if a["duration_s"] >= 0.5]
    assert len(longs) >= 45, len(longs)
    out_of_band = [
        a["id"] for a in longs if abs(a["lufs_integrated"] - TARGET_LUFS) > LUFS_TOLERANCE
    ]
    assert out_of_band == [], out_of_band


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
    sample = ["whoosh_air_up", "whoosh_air_down", "click_pen", "shutter_single"]
    by_id = {e[1]: e for e in G.CATALOG}
    committed = json.loads(MANIFEST.read_text(encoding="utf-8"))
    committed_sha = {a["id"]: a["sha256"] for a in committed["assets"]}

    for aid in sample:
        out_path, _ = G.render_asset(tmp_path, by_id[aid], G.SEED_DEFAULT)
        digest = hashlib.sha256(out_path.read_bytes()).hexdigest()
        assert digest == committed_sha[aid], aid


def test_sweep_direction_matches_source(manifest):
    """FIX item 1: a swept asset's spectral centroid must move the way its
    source parameters say.  ``f0 > f1`` sweeps down (negative slope),
    ``f0 < f1`` sweeps up (positive slope)."""
    swept = [a for a in manifest["assets"] if a["type"] in ("whoosh", "swipe", "riser", "downer")]
    assert len(swept) >= 11, len(swept)
    for a in swept:
        ends = _sweep_endpoints(a)
        assert ends is not None, a["id"]
        f0, f1 = ends
        slope = _centroid_slope(_read_wav(REPO_ROOT / a["file"]))
        if f0 > f1:
            assert slope < 0.0, (a["id"], f0, f1, slope)
        else:
            assert slope > 0.0, (a["id"], f0, f1, slope)


def test_down_and_up_sweeps_are_spectrally_opposite(manifest):
    """FIX item 1 regression: ``whoosh_air_down`` must not be a copy of
    ``whoosh_air_up`` (nor ``swipe_down`` of ``swipe_up``)."""
    for down_id, up_id in (("whoosh_air_down", "whoosh_air_up"), ("swipe_down", "swipe_up")):
        d = next(a for a in manifest["assets"] if a["id"] == down_id)
        u = next(a for a in manifest["assets"] if a["id"] == up_id)
        sd = _centroid_slope(_read_wav(REPO_ROOT / d["file"]))
        su = _centroid_slope(_read_wav(REPO_ROOT / u["file"]))
        assert sd < 0.0 < su, (down_id, sd, up_id, su)


def test_same_type_assets_are_distinct(manifest):
    """FIX item 2b: no two assets of the same type may be near-duplicates.

    Similarity is the cosine of the concatenated (32 log-band mean spectrum +
    20-segment envelope) feature - two unit-norm halves, so the value is the
    average of the two cosines.  Everything of the same type must be <= 0.99.
    """
    by_type: dict[str, list[dict]] = {}
    for a in manifest["assets"]:
        by_type.setdefault(a["type"], []).append(a)

    worst = (0.0, None, None)
    for typ, items in sorted(by_type.items()):
        sigs = [(a["id"], _read_wav(REPO_ROOT / a["file"])) for a in items]
        for i in range(len(sigs)):
            for j in range(i + 1, len(sigs)):
                c = _combined_similarity(sigs[i][1], sigs[j][1])
                if c > worst[0]:
                    worst = (c, sigs[i][0], sigs[j][0])
                assert c <= SIMILARITY_MAX, (typ, sigs[i][0], sigs[j][0], c)
    assert worst[0] <= SIMILARITY_MAX, worst
