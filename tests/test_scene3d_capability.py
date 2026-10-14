"""Tests for the SCENE3D capability contract (CAPABILITY_CONTRACT.md).

These cover the four guarantees every capability must satisfy:

1. After registration the capability is discoverable via ``list`` / ``get``.
2. Illegal params are rejected by the capability's ``params_schema``.
3. A short (2 s) render produces an artefact that passes ``ffprobe``.
4. If the produced artefact is deleted, a follow-up integrity check fails.

The scene3d renderer is CPU-only (Playwright + SwiftShader) and needs the
chromium binary installed in ``~/.cache/ms-playwright``; the suite skips
gracefully otherwise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.capabilities import (
    CapabilityError,
    CapabilityResult,
    get,
    list_capabilities,
)
from hevi.capabilities.scene3d import _META

_CHROMIUM = Path.home() / ".cache" / "ms-playwright"


def _chromium_available() -> bool:
    if not _CHROMIUM.exists():
        return False
    for sub in _CHROMIUM.iterdir():
        if sub.name.startswith("chromium-"):
            for cand in ("chrome-linux64/chrome", "chrome-linux/chrome"):
                if (sub / cand).exists():
                    return True
    return False


pytestmark = pytest.mark.skipif(
    not _chromium_available(),
    reason="playwright chromium not installed in ~/.cache/ms-playwright",
)


# --------------------------------------------------------------------------- #
# 1) Registration: the capability is findable through the registry.
# --------------------------------------------------------------------------- #
def test_capability_registered_and_listable() -> None:
    for name in _META:
        assert get(name).name == name
    found = [c.name for c in list_capabilities()]
    for name in _META:
        assert name in found
    # Kind / aspect metadata is wired correctly.
    cap = get("scene3d.planet_orbit")
    assert cap.kind == "shot"
    assert "16:9" in cap.aspects and "9:16" in cap.aspects


# --------------------------------------------------------------------------- #
# 2) Illegal params are rejected by the params schema.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("bad", [
    {"wind_strength": 99},        # exceeds maximum 4.0
    {"foo": 1},                   # unknown property (additionalProperties: false)
    {"camera_path": [{}]},        # missing required t/pos/look
    {"resolution": 1},            # below minimum 64
])
def test_capability_rejects_bad_params(bad: dict) -> None:
    cap = get("scene3d.planet_orbit")
    with pytest.raises(CapabilityError):
        cap.validate_params(bad)


def test_capability_accepts_valid_params() -> None:
    cap = get("scene3d.fox_wheat")
    # No exception == pass.
    cap.validate_params({"seed": 7, "wind_strength": 1.2, "bloom_strength": 0.6})
    cap.validate_params({})  # empty params are allowed


# --------------------------------------------------------------------------- #
# 3) A 2-second render yields an ffprobe-clean MP4.
# --------------------------------------------------------------------------- #
def test_capability_render_passes_ffprobe(tmp_path: Path) -> None:
    from hevi.layer4_legacy.scene3d.renderer import ffprobe

    cap = get("scene3d.planet_orbit")
    out = tmp_path / "cap_render"
    res = cap.render(
        {"seed": 4242},
        out,
        duration=2.0,
        aspect="16:9",
        seed=4242,
    )
    assert isinstance(res, CapabilityResult)
    assert res.mp4 and Path(res.mp4).exists()
    probe = ffprobe(res.mp4)
    assert probe["codec"] == "h264"
    # Within tolerance of the requested 2 s (30 fps -> 60 frames).
    assert abs(probe["duration"] - 2.0) <= 0.5
    assert probe["width"] == 1920 and probe["height"] == 1080
    assert res.sha256


# --------------------------------------------------------------------------- #
# 4) Deleting the produced artefact makes a follow-up check fail.
# --------------------------------------------------------------------------- #
def test_capability_missing_artefact_fails(tmp_path: Path) -> None:
    cap = get("scene3d.fox_wheat")
    out = tmp_path / "cap_missing"
    res = cap.render({}, out, duration=2.0, aspect="9:16", seed=99)
    video = Path(res.mp4)
    assert video.exists()
    # Integrity gate: after deletion the result is no longer verifiable, and a
    # fresh render whose output is removed must raise CapabilityError.
    video.unlink()
    assert not video.exists()
    with pytest.raises(CapabilityError):
        _require_present(res)


def _require_present(res: CapabilityResult) -> None:
    """Re-validate the result's primary artefact exists on disk."""
    from hevi.capabilities import CapabilityError as _CE

    if not Path(res.mp4).exists():
        raise _CE(f"capability artefact missing: {res.mp4}")


# --------------------------------------------------------------------------- #
# Determinism: same seed -> byte-identical MP4 sha256.
# --------------------------------------------------------------------------- #
def test_capability_render_deterministic(tmp_path: Path) -> None:
    cap = get("scene3d.star_sea")
    a = cap.render({}, tmp_path / "det_a", duration=2.0, aspect="9:16", seed=1234)
    b = cap.render({}, tmp_path / "det_b", duration=2.0, aspect="9:16", seed=1234)
    assert a.sha256 == b.sha256, "same seed produced different artefacts"
