"""Tests for the gate-side spectral hygiene checks (infrasound + HF spike).

The two checks live in ``hevi.audio.spectral_checks`` and are wired into
``audio.earshot_gate`` next to earshot's loudness/peak checks.  Fixtures
are synthesized with numpy and written as int16 PCM via the stdlib
``wave`` module (same convention as tests/test_earshot_gate.py); the
gate-level tests run the real local earshot CLI like the sibling suite.

Calibration behind the defaults (2026-10-23, measured on this host):
clean hevi products sit at infrasound ratio <= 0.0031 and HF prominence
<= 16.2 dB; injected faults measure >= 0.049 (subsonic) and >= 67 dB
(16 kHz tone over narration).  Defaults: ratio <= 0.01, prominence
<= 24 dB.  See docs/rules/audio_gate.md.
"""

import math
import wave
from pathlib import Path

import numpy as np
import pytest

import hevi.capabilities as caps
from hevi.audio import spectral_checks as sc
from hevi.capabilities.earshot_gate import _spectral_gate_checks
from hevi.capabilities.errors import CapabilityError

SR = 48000


def _sine(freq: float, amp: float, seconds: float = 3.0, sr: int = SR) -> np.ndarray:
    t = np.arange(int(sr * seconds)) / sr
    return amp * np.sin(2.0 * np.pi * freq * t)


def _write_wav(path: Path, samples: np.ndarray, sr: int = SR) -> Path:
    clipped = np.clip(samples, -1.0, 1.0)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((clipped * 32767).astype("<i2").tobytes())
    return path


def _verdicts(spec: dict) -> dict:
    checks = _spectral_gate_checks(spec, infrasound_max_ratio=0.01, hf_spike_max_db=24.0)
    return {c["name"]: c for c in checks}


# ---------------------------------------------------------------------------
# Metric level
# ---------------------------------------------------------------------------


def test_clean_signal_metrics() -> None:
    spec = sc.measure_spectrum(_sine(440.0, 0.2) + _sine(220.0, 0.1), SR)
    assert spec["infrasound_ratio"] is not None and spec["infrasound_ratio"] < 1e-3
    assert spec["hf_assessable"] is True
    verdicts = _verdicts(spec)
    assert verdicts["infrasound"]["ok"] is True
    assert verdicts["hf_narrowband_spike"]["ok"] is True


def test_infrasound_ratio_value() -> None:
    # Power ratio of the mix: 0.25^2 / (0.25^2 + 0.2^2) = 0.6098.
    spec = sc.measure_spectrum(_sine(10.0, 0.25) + _sine(440.0, 0.2), SR)
    assert spec["infrasound_ratio"] == pytest.approx(0.6098, abs=0.05)


def test_infrasound_fault_only_trips_infrasound() -> None:
    spec = sc.measure_spectrum(_sine(10.0, 0.25) + _sine(440.0, 0.2), SR)
    verdicts = _verdicts(spec)
    assert verdicts["infrasound"]["ok"] is False
    assert verdicts["hf_narrowband_spike"]["ok"] is True


def test_hf_tone_fault_only_trips_hf() -> None:
    spec = sc.measure_spectrum(_sine(440.0, 0.2) + _sine(16000.0, 0.05), SR)
    assert spec["hf_peak_freq_hz"] == pytest.approx(16000.0, abs=2.0)
    assert spec["hf_spike_prominence_db"] > 60.0
    assert spec["hf_peak_energy_share"] > 0.01
    verdicts = _verdicts(spec)
    assert verdicts["hf_narrowband_spike"]["ok"] is False
    assert verdicts["infrasound"]["ok"] is True


def test_silence_metrics_and_verdict() -> None:
    spec = sc.measure_spectrum(np.zeros(SR * 2), SR)
    assert spec["infrasound_ratio"] is None
    verdicts = _verdicts(spec)
    assert verdicts["infrasound"]["ok"] is False  # nothing measurable -> fail
    assert verdicts["hf_narrowband_spike"]["ok"] is True  # no spike in silence


def test_too_short_raises_and_short_does_not_crash() -> None:
    with pytest.raises(sc.SpectralError):
        sc.measure_spectrum(np.zeros(100), SR)
    spec = sc.measure_spectrum(_sine(440.0, 0.2, seconds=0.05), SR)
    assert spec["duration_s"] == pytest.approx(0.05, abs=0.01)


def test_low_sample_rate_hf_not_assessable() -> None:
    spec = sc.measure_spectrum(_sine(440.0, 0.2, seconds=1.0, sr=16000), 16000)
    assert spec["hf_assessable"] is False
    assert spec["hf_spike_prominence_db"] is None
    verdicts = _verdicts(spec)
    assert verdicts["hf_narrowband_spike"]["ok"] is True
    assert "Nyquist" in verdicts["hf_narrowband_spike"]["detail"]


def test_analyze_file_roundtrip(tmp_path: Path) -> None:
    path = _write_wav(tmp_path / "tone.wav", _sine(440.0, 0.2))
    spec = sc.analyze(path)
    assert spec["sample_rate"] == SR
    assert spec["infrasound_ratio"] < 1e-3


# ---------------------------------------------------------------------------
# Verdict boundaries (fabricated spectra -> pure decision function)
# ---------------------------------------------------------------------------


def _spec(**overrides) -> dict:
    base = {
        "sample_rate": SR,
        "duration_s": 3.0,
        "infrasound_ratio": 0.001,
        "hf_assessable": True,
        "hf_peak_freq_hz": 16000.0,
        "hf_spike_prominence_db": 10.0,
        "hf_peak_energy_share": 0.01,
    }
    base.update(overrides)
    return base


def test_verdict_threshold_boundaries() -> None:
    at = _verdicts(_spec(infrasound_ratio=0.01, hf_spike_prominence_db=24.0))
    assert at["infrasound"]["ok"] is True  # exactly at ceiling passes
    assert at["hf_narrowband_spike"]["ok"] is True
    over = _verdicts(_spec(infrasound_ratio=0.010001, hf_spike_prominence_db=24.1))
    assert over["infrasound"]["ok"] is False
    assert over["hf_narrowband_spike"]["ok"] is False


def test_verdict_negligible_peak_share_passes() -> None:
    # Huge prominence but the bin carries ~no energy (arithmetic noise on
    # a numerically silent band): not a whine.
    verdicts = _verdicts(
        _spec(hf_spike_prominence_db=180.0, hf_peak_energy_share=1e-14)
    )
    assert verdicts["hf_narrowband_spike"]["ok"] is True


def test_verdict_missing_measurements_fail() -> None:
    verdicts = _verdicts(_spec(infrasound_ratio=None, hf_spike_prominence_db=None))
    assert verdicts["infrasound"]["ok"] is False
    assert verdicts["hf_narrowband_spike"]["ok"] is False


# ---------------------------------------------------------------------------
# Gate integration (real earshot CLI, like tests/test_earshot_gate.py)
# ---------------------------------------------------------------------------


@pytest.fixture()
def clean_wav(tmp_path: Path) -> Path:
    return _write_wav(tmp_path / "clean.wav", _sine(440.0, 0.2))


@pytest.fixture()
def infra_wav(tmp_path: Path) -> Path:
    return _write_wav(
        tmp_path / "infra.wav", _sine(440.0, 0.2) + _sine(10.0, 0.25)
    )


@pytest.fixture()
def hf_wav(tmp_path: Path) -> Path:
    return _write_wav(
        tmp_path / "hf.wav", _sine(440.0, 0.2) + _sine(16000.0, 0.05)
    )


def _gate(media: Path, out: Path, **params):
    cap = caps.get("audio.earshot_gate")
    return cap.render_safe(
        {"media_path": str(media), **params},
        out,
        duration=3.0,
        aspect="16:9",
        seed=7,
    )


def test_gate_clean_fixture_passes_with_spectral(tmp_path: Path, clean_wav: Path) -> None:
    import json

    result = _gate(clean_wav, tmp_path / "out")
    assert result.qa["pass"] is True
    assert result.qa["failed_checks"] == []
    assert result.qa["infrasound_ratio"] is not None
    assert result.qa["infrasound_ratio"] < 0.01
    report = json.loads(Path(result.qa["report"]).read_text(encoding="utf-8"))
    names = [c["name"] for c in report["checks"]]
    assert "infrasound" in names and "hf_narrowband_spike" in names
    assert report["spectral"]["sample_rate"] == SR


def test_gate_infrasound_fixture_fails_only_infrasound(
    tmp_path: Path, infra_wav: Path
) -> None:
    result = _gate(infra_wav, tmp_path / "out")
    assert result.qa["pass"] is False
    assert result.qa["failed_checks"] == ["infrasound"]
    assert result.qa["infrasound_ratio"] > 0.5


def test_gate_hf_fixture_fails_only_hf(tmp_path: Path, hf_wav: Path) -> None:
    result = _gate(hf_wav, tmp_path / "out")
    assert result.qa["pass"] is False
    assert result.qa["failed_checks"] == ["hf_narrowband_spike"]
    assert result.qa["hf_spike_prominence_db"] > 100.0


def test_gate_spectral_can_be_disabled(tmp_path: Path, infra_wav: Path) -> None:
    result = _gate(infra_wav, tmp_path / "out", spectral_checks=False)
    assert result.qa["pass"] is True
    assert result.qa["infrasound_ratio"] is None


def test_gate_custom_threshold_relaxes_infrasound(
    tmp_path: Path, infra_wav: Path
) -> None:
    result = _gate(infra_wav, tmp_path / "out", infrasound_max_ratio=0.7)
    assert result.qa["pass"] is True


def test_gate_spectral_params_validated(tmp_path: Path, clean_wav: Path) -> None:
    with pytest.raises(CapabilityError):
        _gate(clean_wav, tmp_path / "o1", infrasound_max_ratio=1.5)  # schema max 1.0
    with pytest.raises(CapabilityError):
        _gate(clean_wav, tmp_path / "o2", hf_spike_max_db=100.0)  # schema max 60
