"""Audio remediation: pure gain math + the one-shot re-master wiring."""

from __future__ import annotations

from pathlib import Path

from hevi.talking_head import pipeline as th_pipeline
from hevi.talking_head.pipeline import compute_remediation_gain_db, run_talking_head


def test_gain_fixes_hot_peak() -> None:
    # run3's real failure: peak -0.4 dBTP vs ceiling -1.0, loudness fine
    gain = compute_remediation_gain_db(true_peak_dbtp=-0.4, lufs=-13.6)
    assert gain == -1.1


def test_gain_fixes_hot_loudness_with_headroom() -> None:
    gain = compute_remediation_gain_db(true_peak_dbtp=-3.0, lufs=-10.0)
    assert gain == -4.0


def test_gain_up_capped_by_peak() -> None:
    # quiet loudness but only 1.5 dB of peak headroom: partial fix is offered
    gain = compute_remediation_gain_db(true_peak_dbtp=-3.0, lufs=-20.0)
    assert gain == 1.5


def test_gain_none_when_levels_fine() -> None:
    assert compute_remediation_gain_db(true_peak_dbtp=-2.0, lufs=-14.0) is None


def _fake_tts(text: str, out_wav: Path, voice: str) -> Path:
    out_wav.write_bytes(b"wav")
    return out_wav


def _fake_lipsync(portrait, wav, duration_s, work_dir, engine) -> Path:
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out = work_dir / "clip.mp4"
    out.write_bytes(b"mp4")
    return out


def test_remediation_replaces_delivery_and_passes(tmp_path: Path, monkeypatch) -> None:
    portrait = tmp_path / "p.jpg"
    portrait.write_bytes(b"jpg")
    monkeypatch.setattr(
        th_pipeline, "run_preflight",
        lambda **kw: {"ok": True, "errors": [], "warnings": [],
                      "estimated_seconds": 5.0, "portrait": {"width": 10, "height": 10}},
    )
    monkeypatch.setattr(th_pipeline, "_media_duration", lambda p: 5.0)
    monkeypatch.setattr(
        th_pipeline, "_remux_with_gain",
        lambda src, dst, gain: (Path(dst).write_bytes(b"mastered"), Path(dst))[1],
    )
    calls: list[str] = []

    def flaky_gates(video, text, adur):
        calls.append(str(video))
        if len(calls) == 1:
            return {
                "pass": False,
                "failed": ["earshot_audio"],
                "gates": {"earshot_audio": {
                    "pass": False,
                    "failed_checks": ["true_peak"],
                    "measurements": {"true_peak_dbtp": -0.4, "lufs": -13.6},
                }},
            }
        return {"pass": True, "failed": [], "gates": {"earshot_audio": {"pass": True}}}

    ledger = run_talking_head(
        script_text="你好，这是一个口播测试。",
        portrait_path=portrait,
        out_dir=tmp_path / "job",
        tts_fn=_fake_tts,
        lipsync_fn=_fake_lipsync,
        gate_runner=flaky_gates,
    )
    assert ledger["status"] == "delivered"
    detail = ledger["stages"]["gates"]["detail"]
    assert detail["remediation"]["applied"] is True
    assert detail["remediation"]["gain_db"] == -1.1
    delivered = Path(ledger["artifacts"]["talking_head_mp4"])
    assert delivered.read_bytes() == b"mastered"
