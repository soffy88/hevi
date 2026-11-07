"""Contract tests for the earshot audio-gate capabilities (CAPABILITY_CONTRACT.md).

These tests run the real local earshot CLI (model-free paths: ``measure`` /
``sfx render``) in ~/.venvs/earshot.  Test tones are synthesized with the
stdlib ``wave`` module so no extra test dependencies are needed.
"""

import json
import math
import wave
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.errors import CapabilityError


def _sine_wav(path: Path, *, amp: float, seconds: float = 3.0, clip: bool = False) -> Path:
    """Mono 48 kHz PCM16 sine (optionally hard-clipped)."""
    sr = 48000
    n = int(sr * seconds)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        for i in range(n):
            v = amp * math.sin(2.0 * math.pi * 440.0 * i / sr)
            if clip:
                v = max(-1.0, min(1.0, v))
            w.writeframes(int(v * 32767).to_bytes(2, "little", signed=True))
    return path


@pytest.fixture()
def good_wav(tmp_path: Path) -> Path:
    return _sine_wav(tmp_path / "good.wav", amp=0.2)


@pytest.fixture()
def bad_wav(tmp_path: Path) -> Path:
    return _sine_wav(tmp_path / "bad.wav", amp=1.4, clip=True)


def test_earshot_capabilities_registered_and_listable() -> None:
    names = caps.names()
    assert "audio.earshot_gate" in names
    assert "audio.sfx_render" in names
    listed = [c.name for c in caps.list(kind="audio")]
    assert "audio.earshot_gate" in listed
    assert "audio.sfx_render" in listed


def test_earshot_describe_has_params_schema() -> None:
    from hevi.capabilities.registry import describe

    by_name = {item["name"]: item for item in describe()}
    for expected in ("audio.earshot_gate", "audio.sfx_render"):
        assert expected in by_name
        assert by_name[expected].get("description"), expected
        assert by_name[expected].get("params_schema"), expected


def test_gate_rejects_invalid_params(good_wav: Path) -> None:
    cap = caps.get("audio.earshot_gate")
    with pytest.raises(CapabilityError):
        cap.render_safe({}, Path("/tmp/eg"), duration=1.0, aspect="16:9", seed=1)
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"media_path": str(good_wav), "lufs_target": 5.0},  # out of schema range
            Path("/tmp/eg"),
            duration=1.0,
            aspect="16:9",
            seed=1,
        )
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"media_path": str(good_wav), "bogus": 1},  # additionalProperties: False
            Path("/tmp/eg"),
            duration=1.0,
            aspect="16:9",
            seed=1,
        )


def test_gate_passes_clean_tone(tmp_path: Path, good_wav: Path) -> None:
    cap = caps.get("audio.earshot_gate")
    result = cap.render_safe(
        {"media_path": str(good_wav)},
        tmp_path / "out",
        duration=3.0,
        aspect="16:9",
        seed=7,
    )
    assert result.qa["pass"] is True
    assert result.qa["failed_checks"] == []
    assert abs(result.qa["lufs"] - (-14.7)) < 1.0
    assert result.qa["true_peak_dbtp"] <= -1.0
    assert result.wav == str(good_wav)
    assert result.sha256

    report = Path(result.qa["report"])
    assert report.is_file()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["pass"] is True
    assert payload["tool"].startswith("earshot measure")

    report.unlink()
    assert not report.exists(), "contract: deleting the artifact must break verification"


def test_gate_fails_hot_tone(tmp_path: Path, bad_wav: Path) -> None:
    cap = caps.get("audio.earshot_gate")
    result = cap.render_safe(
        {"media_path": str(bad_wav)},
        tmp_path / "out",
        duration=3.0,
        aspect="16:9",
        seed=7,
    )
    assert result.qa["pass"] is False
    failed = result.qa["failed_checks"]
    assert "loudness" in failed
    assert "true_peak" in failed
    assert "no_hard_clipping" in failed


def test_gate_missing_file_raises(tmp_path: Path) -> None:
    cap = caps.get("audio.earshot_gate")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"media_path": str(tmp_path / "nope.wav")},
            tmp_path / "out",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )


def test_gate_missing_earshot_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, good_wav: Path
) -> None:
    monkeypatch.setenv("EARSHOT_BIN", "/nonexistent/earshot")
    cap = caps.get("audio.earshot_gate")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"media_path": str(good_wav)},
            tmp_path / "out",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )


def test_sfx_render_rejects_invalid_params() -> None:
    cap = caps.get("audio.sfx_render")
    with pytest.raises(CapabilityError):
        cap.render_safe({}, Path("/tmp/es"), duration=1.0, aspect="16:9", seed=1)
    with pytest.raises(CapabilityError):
        cap.render_safe({"sfx_id": ""}, Path("/tmp/es"), duration=1.0, aspect="16:9", seed=1)


def test_sfx_render_produces_decodable_wav(tmp_path: Path) -> None:
    cap = caps.get("audio.sfx_render")
    result = cap.render_safe(
        {"sfx_id": "click/double"},
        tmp_path / "out",
        duration=1.0,
        aspect="16:9",
        seed=42,
    )
    wav = Path(result.wav)
    assert wav.is_file() and wav.suffix == ".wav"
    with wave.open(str(wav), "rb") as w:
        assert w.getframerate() == 48000
        assert w.getnframes() > 0
    assert result.qa["sfx_id"] == "click/double"
    assert result.qa["category"] == "click"
    assert result.qa["license"].startswith("Sound bank from earshot")
    assert result.sha256

    wav.unlink()
    assert not wav.exists(), "contract: deleting the artifact must break verification"


def test_sfx_render_invalid_id_raises(tmp_path: Path) -> None:
    cap = caps.get("audio.sfx_render")
    with pytest.raises(CapabilityError):
        cap.render_safe(
            {"sfx_id": "no/such_id"},
            tmp_path / "out",
            duration=1.0,
            aspect="16:9",
            seed=1,
        )


def test_sfx_render_with_dur_pitch(tmp_path: Path) -> None:
    cap = caps.get("audio.sfx_render")
    result = cap.render_safe(
        {"sfx_id": "whoosh_fast/tight", "dur": 1.0, "apex": 0.5},
        tmp_path / "out",
        duration=1.0,
        aspect="16:9",
        seed=42,
    )
    assert Path(result.wav).is_file()
