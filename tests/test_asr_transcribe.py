"""Tests for the ASR-line fix P0+P1+P2+P3 (2026-11-01).

P0: observed-side t2s normalisation + audited glossary (exact
reproduction of the measured ASR-fix transcripts, embedded here so
the tests are self-contained).
P1: default model small + large-v3-turbo fallback trigger.
P2: audio.asr_transcribe capability + evidence fields + final_qc
calling it via audio_path.
P3: manual proofreading re-review in final_qc (provenance, positive
and negative cases).
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

import hevi.capabilities as caps
from hevi.capabilities.asr_glossary import (
    ASR_GLOSSARY,
    GLOSSARY_VERSION,
    apply_asr_glossary,
    asr_glossary_entries,
)
from hevi.capabilities.asr_normalization import (
    normalize_observed_text,
    traditional_to_simplified,
)
from hevi.capabilities.asr_transcribe import (
    DEFAULT_ASR_MODEL,
    FALLBACK_ASR_MODEL,
    FALLBACK_COVERAGE_FLOOR,
    resolve_model_path,
    transcribe_audio,
)
from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.final_qc import run_final_qc
from hevi.capabilities.prompt_eval_harness import (
    DIALOGUE_COVERAGE_FLOOR,
    _containment_coverage,
)
from hevi.capabilities.subtitle_discipline import validate_events

# Measured transcripts from /data/soffy/asr-fix (2026-11-01), embedded.
E2_BASE_RAW = (
    "鄧隆該點起來了奶奶我來幫忙火柴放在木河裡盒子是空的呀"
    "昨天還在抽屜裡找到了在抽屜裡燈籠亮起來了整條街都亮了老街的燈又亮了"
)
E2_BASE_T2S = (
    "邓隆该点起来了奶奶我来帮忙火柴放在木河里盒子是空的呀"
    "昨天还在抽屉里找到了在抽屉里灯笼亮起来了整条街都亮了老街的灯又亮了"
)
E2_BASE_GLOSS = (
    "灯笼该点起来了奶奶我来帮忙火柴放在木盒里盒子是空的呀"
    "昨天还在抽屉里找到了在抽屉里灯笼亮起来了整条街都亮了老街的灯又亮了"
)
E3_BASE_RAW = (
    "中午影子最短太陽月 地影月長我們來亮一亮尺子立在這裡"
    "影子長了兩倍光寫著照過來影子跟著太陽走"
)
E3_BASE_T2S = (
    "中午影子最短太阳月 地影月长我们来亮一亮尺子立在这里"
    "影子长了两倍光写著照过来影子跟著太阳走"
)
E3_BASE_GLOSS = (
    "中午影子最短太阳月 地影月长我们来量一量尺子立在这里"
    "影子长了两倍光写著照过来影子跟著太阳走"
)
E3_LINES = [
    "中午影子最短", "太阳越低影越长", "我们来量一量", "尺子立在这里",
    "影子长了两倍", "光斜着照过来", "影子跟着太阳走",
]
E2_LINES = [
    "灯笼该点起来了", "奶奶我来帮忙", "火柴放在木盒里", "盒子是空的呀",
    "昨天还在抽屉里", "找到了在抽屉里", "灯笼亮起来了", "整条街都亮了",
    "老街的灯又亮了",
]

_SMALL_CACHE = Path("/data/soffy/models/hf/hub/models--Systran--faster-whisper-small")
_E3_AUDIO = Path("/data/soffy/stable-acceptance-20261101/assemblies/E3/runA_audio.wav")


# ---------------------------------------------------------------- P0


def test_glossary_is_exactly_four_versioned_entries() -> None:
    assert GLOSSARY_VERSION == "asr-glossary-v1"
    assert len(ASR_GLOSSARY) == 4
    assert [src for src, _dst, _ev in ASR_GLOSSARY] == [
        "邓隆", "木河", "我们来亮一亮", "光写着照过来",
    ]
    assert [dst for _src, dst, _ev in ASR_GLOSSARY] == [
        "灯笼", "木盒", "我们来量一量", "光斜着照过来",
    ]
    entries = asr_glossary_entries()
    assert len(entries) == 4
    assert all(e["version"] == GLOSSARY_VERSION and e["evidence"] for e in entries)


def test_glossary_hits_all_four_audited_entries() -> None:
    text = "邓隆在木河里，我们来亮一亮，光写着照过来"
    out, hits = apply_asr_glossary(text)
    assert out == "灯笼在木盒里，我们来量一量，光斜着照过来"
    # Hits follow application order: longest source first (so a longer
    # misrecognition is never half-replaced by a shorter one inside it).
    assert hits == [
        "我们来亮一亮->我们来量一量", "光写着照过来->光斜着照过来",
        "邓隆->灯笼", "木河->木盒",
    ]


def test_glossary_miss_leaves_unrelated_text_untouched() -> None:
    text = "灯笼已经亮了，木盒里没有火柴"
    out, hits = apply_asr_glossary(text)
    assert out == text
    assert hits == []


def test_glossary_never_rewrites_whole_sentence() -> None:
    # E3 S02: deliberately NOT in the glossary (circular rewrite).
    text = "太阳月 地影月长"
    out, hits = apply_asr_glossary(text)
    assert out == text
    assert hits == []
    assert "太阳越低影越长" not in out


def test_t2s_builtin_reproduces_measured_e2_transcript() -> None:
    norm = normalize_observed_text(E2_BASE_RAW)
    assert norm["t2s"] == E2_BASE_T2S
    assert norm["normalized"] == E2_BASE_GLOSS
    assert norm["glossary_hits"] == ["邓隆->灯笼", "木河->木盒"]
    assert norm["glossary_version"] == GLOSSARY_VERSION
    assert norm["normalization_backend"] == "builtin"
    assert norm["raw"] == E2_BASE_RAW


def test_t2s_builtin_reproduces_measured_e3_transcript() -> None:
    norm = normalize_observed_text(E3_BASE_RAW)
    assert norm["t2s"] == E3_BASE_T2S
    assert norm["normalized"] == E3_BASE_GLOSS
    # Entry 4 does NOT hit the base raw form: t2s leaves 著 untouched,
    # so "光写著照过来" is not the t2s-form entry "光写着照过来".
    # This is the measured behaviour (E3/base glossary mean 0.8707).
    assert norm["glossary_hits"] == ["我们来亮一亮->我们来量一量"]


def test_t2s_leaves_simplified_text_and_zhu_untouched() -> None:
    assert traditional_to_simplified("太阳光太亮了，著名") == "太阳光太亮了，著名"
    assert traditional_to_simplified("光写著照过来") == "光写著照过来"
    assert traditional_to_simplified("光写着照过来") == "光写着照过来"


def test_normalization_is_idempotent() -> None:
    once = normalize_observed_text(E2_BASE_RAW)["normalized"]
    twice = normalize_observed_text(once)["normalized"]
    assert once == twice == E2_BASE_GLOSS


def test_normalization_none_is_explicit_and_recorded() -> None:
    norm = normalize_observed_text(E2_BASE_RAW, normalization="none")
    assert norm["normalized"] == E2_BASE_RAW
    assert norm["glossary_hits"] == []
    assert norm["glossary_version"] is None
    assert norm["normalization_applied"] is False
    assert "warning" in norm


def test_opencc_backend_fails_loudly_when_unavailable() -> None:
    if importlib.util.find_spec("opencc") is not None:
        pytest.skip("opencc is importable in this environment")
    with pytest.raises(RuntimeError, match="OpenCC"):
        traditional_to_simplified("太陽", backend="opencc")


def test_coverage_normalises_observed_side_only() -> None:
    assert DIALOGUE_COVERAGE_FLOOR == 0.80
    # Traditional observed, simplified expected: normalised -> full cover.
    assert _containment_coverage("灯笼该点起来了", "燈籠該點起來了") == 1.0
    # Glossary on the observed side only.
    assert _containment_coverage("灯笼该点起来了", "邓隆该点起来了") == 1.0
    # Expected side is NEVER normalised: a traditional expected line
    # against simplified observed text does not get a free pass.
    assert _containment_coverage("鄧隆", "灯笼") == 0.0
    # Measured E3/base glossary mean reproduces exactly.
    coverages = [
        round(_containment_coverage(line, E3_BASE_RAW), 4) for line in E3_LINES
    ]
    assert coverages == [1.0, 0.5714, 1.0, 1.0, 1.0, 0.6667, 0.8571]
    assert round(sum(coverages) / len(coverages), 4) == 0.8707


def test_subtitle_discipline_vo_check_uses_normalised_observed() -> None:
    report = validate_events(
        [{"start_sec": 0.0, "end_sec": 2.0, "text": "灯笼该点起来了"}],
        orientation="horizontal",
        asr_text="燈籠該點起來了",
    )
    assert report["verdict"] == "pass"
    assert not any(f["kind"] == "vo_asr_mismatch" for f in report["failures"])


# ---------------------------------------------------------------- P1/P2


def test_default_model_is_small_and_fallback_is_large_turbo() -> None:
    assert DEFAULT_ASR_MODEL == "small"
    assert FALLBACK_ASR_MODEL == "large-v3-turbo"
    assert FALLBACK_COVERAGE_FLOOR == 0.90


def test_resolve_model_path_rejects_unknown_and_missing() -> None:
    with pytest.raises(CapabilityError, match="unknown model"):
        resolve_model_path("sensevoice")
    with pytest.raises(CapabilityError, match="model_path"):
        resolve_model_path("small", model_path="/nonexistent/model-dir")


@pytest.mark.skipif(not _SMALL_CACHE.exists(), reason="small model cache absent")
def test_resolve_small_model_to_cached_directory() -> None:
    resolved = resolve_model_path("small")
    assert Path(resolved, "model.bin").is_file()


def _fake_transcriber_factory(small_text: str, large_text: str):
    def _fake(model_path: str, audio_path: Path, **kwargs):
        text = large_text if "large" in model_path else small_text
        return {
            "segments": [{"start": 0.0, "end": 1.0, "text": text}],
            "words": [],
            "language": "zh",
            "language_probability": 1.0,
            "load_seconds": 0.5,
            "transcribe_seconds": 1.25,
        }

    return _fake


def _silent_wav(path: Path) -> Path:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 16000)
    return path


@pytest.mark.skipif(not _SMALL_CACHE.exists(), reason="small model cache absent")
def test_fallback_triggers_below_floor_and_keeps_both_passes(tmp_path: Path) -> None:
    audio = _silent_wav(tmp_path / "a.wav")
    fake = _fake_transcriber_factory(
        "完全不相干的旁白", "灯笼该点起来了")
    evidence = transcribe_audio(
        audio, expected_lines=["灯笼该点起来了"],
        _transcriber=fake,
    )
    assert evidence["model"] == FALLBACK_ASR_MODEL
    assert evidence["fallback"]["triggered"] is True
    assert len(evidence["passes"]) == 2
    assert evidence["passes"][0]["model"] == "small"
    assert evidence["passes"][1]["model"] == FALLBACK_ASR_MODEL
    assert evidence["transcript_normalized"] == "灯笼该点起来了"
    assert evidence["coverage"]["mean"] == 1.0
    assert evidence["load_seconds"] == 0.5
    assert evidence["transcribe_seconds"] == 1.25


@pytest.mark.skipif(not _SMALL_CACHE.exists(), reason="small model cache absent")
def test_no_fallback_when_primary_meets_floor(tmp_path: Path) -> None:
    audio = _silent_wav(tmp_path / "a.wav")
    fake = _fake_transcriber_factory("灯笼该点起来了", "灯笼该点起来了")
    evidence = transcribe_audio(
        audio, expected_lines=["灯笼该点起来了"], _transcriber=fake)
    assert evidence["model"] == "small"
    assert evidence["fallback"]["triggered"] is False
    assert len(evidence["passes"]) == 1


@pytest.mark.skipif(not _SMALL_CACHE.exists(), reason="small model cache absent")
def test_fallback_disabled_never_runs_large(tmp_path: Path) -> None:
    audio = _silent_wav(tmp_path / "a.wav")
    fake = _fake_transcriber_factory("完全不相干的旁白", "灯笼该点起来了")
    evidence = transcribe_audio(
        audio, expected_lines=["灯笼该点起来了"],
        enable_fallback=False, _transcriber=fake)
    assert evidence["model"] == "small"
    assert evidence["fallback"]["triggered"] is False
    assert evidence["fallback"]["enabled"] is False


@pytest.mark.skipif(not _SMALL_CACHE.exists(), reason="small model cache absent")
def test_fallback_unavailable_keeps_primary_and_warns(tmp_path: Path) -> None:
    audio = _silent_wav(tmp_path / "a.wav")
    fake = _fake_transcriber_factory("完全不相干的旁白", "灯笼该点起来了")
    evidence = transcribe_audio(
        audio, expected_lines=["灯笼该点起来了"],
        fallback_model="no-such-model", _transcriber=fake)
    assert evidence["model"] == "small"
    assert evidence["fallback"]["triggered"] is True
    assert evidence["fallback"]["available"] is False
    assert evidence["warnings"]


@pytest.mark.skipif(not _SMALL_CACHE.exists(), reason="small model cache absent")
def test_capability_evidence_fields_are_complete(tmp_path: Path) -> None:
    audio = _silent_wav(tmp_path / "a.wav")
    fake = _fake_transcriber_factory("鄧隆該點起來了", "鄧隆該點起來了")
    evidence = transcribe_audio(
        audio, expected_lines=["灯笼该点起来了"],
        enable_fallback=False, _transcriber=fake)
    assert evidence["capability"] == "audio.asr_transcribe"
    assert evidence["model"] == "small"
    assert evidence["device"] == "cpu"
    assert evidence["compute_type"] == "int8"
    assert evidence["language"] == "zh"
    assert evidence["normalization"] == "builtin"
    assert evidence["glossary_version"] == GLOSSARY_VERSION
    assert evidence["glossary_hits"] == ["邓隆->灯笼"]
    assert evidence["transcript_raw"] == "鄧隆該點起來了"
    assert evidence["transcript_normalized"] == "灯笼该点起来了"
    assert evidence["transcript_t2s"] == "邓隆该点起来了"
    assert evidence["load_seconds"] >= 0
    assert evidence["transcribe_seconds"] >= 0
    assert evidence["coverage"]["mean"] == 1.0


def test_unknown_glossary_version_is_rejected(tmp_path: Path) -> None:
    audio = _silent_wav(tmp_path / "a.wav")
    with pytest.raises(CapabilityError, match="glossary version"):
        transcribe_audio(audio, glossary_version="asr-glossary-v999")


def test_missing_audio_file_is_rejected() -> None:
    with pytest.raises(CapabilityError, match="audio file not found"):
        transcribe_audio("/nonexistent/audio.wav")


def test_capability_is_registered_with_schema() -> None:
    cap = caps.get("audio.asr_transcribe")
    assert cap.name == "audio.asr_transcribe"
    assert cap.validate_params({"audio_path": "x.wav"}) == {"audio_path": "x.wav"}
    with pytest.raises(CapabilityError, match="audio_path"):
        cap.validate_params({})


@pytest.mark.skipif(not _E3_AUDIO.is_file(), reason="E3 acceptance audio absent")
def test_real_small_model_reproduces_measured_e3_coverage() -> None:
    evidence = transcribe_audio(_E3_AUDIO, expected_lines=E3_LINES)
    assert evidence["model"] == "small"
    assert evidence["fallback"]["triggered"] is False
    assert evidence["coverage"]["mean"] == 1.0
    assert evidence["coverage"]["per_line"] == [1.0] * len(E3_LINES)
    assert evidence["glossary_hits"] == ["我们来亮一亮->我们来量一量"]
    assert evidence["load_seconds"] > 0
    assert evidence["transcribe_seconds"] > 0


# ---------------------------------------------------------------- P2/P3 via final_qc


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg required")
def _moving_video(path: Path) -> Path:
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "testsrc2=size=320x180:rate=10:duration=4",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(path)],
        capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    return path


_PROOF = {
    "corrected_transcript": "灯笼该点起来了",
    "proofreader": "test-proofreader",
    "timestamp": "2026-11-01T00:00:00+00:00",
    "voice_correct_attested": True,
}


def test_final_qc_proofreading_reviews_failed_vo_asr(tmp_path: Path) -> None:
    media = _moving_video(tmp_path / "m.mp4")
    report = run_final_qc(
        media,
        expected_vo_lines=["灯笼该点起来了"],
        asr_text="灯笼亮起来了",
        asr_proofreading=dict(_PROOF),
        work_dir=tmp_path / "work",
    )
    assert report["checks"]["vo_asr"]["pass"] is True
    proof = report["asr_proofreading"]
    assert proof["status"] == "applied"
    assert proof["corrected_transcript"] == "灯笼该点起来了"
    assert proof["proofreader"] == "test-proofreader"
    assert proof["timestamp"] == "2026-11-01T00:00:00+00:00"
    assert proof["provenance"] == "manual_proofreading"
    # Original evidence preserved, never overwritten.
    assert proof["original_observed_text"] == "灯笼亮起来了"
    assert proof["original_dialogue"]["verdict"] == "fail"
    assert proof["recomputed_verdict"] == "pass"
    assert report["vo_asr_evidence"]["supplied_asr_text"] == "灯笼亮起来了"
    assert report["vo_asr_evidence"]["dialogue"]["verdict"] == "fail"


def test_final_qc_proofreading_does_not_alter_passing_check(tmp_path: Path) -> None:
    media = _moving_video(tmp_path / "m.mp4")
    report = run_final_qc(
        media,
        expected_vo_lines=["灯笼该点起来了"],
        asr_text="灯笼该点起来了",
        asr_proofreading=dict(_PROOF),
        work_dir=tmp_path / "work",
    )
    assert report["checks"]["vo_asr"]["pass"] is True
    assert report["asr_proofreading"]["status"] == "not_applied"
    assert report["asr_proofreading"]["recomputed_dialogue"] is None


def test_final_qc_proofreading_still_fails_when_corrected_text_fails(
    tmp_path: Path,
) -> None:
    media = _moving_video(tmp_path / "m.mp4")
    bad_proof = {**_PROOF, "corrected_transcript": "完全不相干的旁白"}
    report = run_final_qc(
        media,
        expected_vo_lines=["灯笼该点起来了"],
        asr_text="灯笼亮起来了",
        asr_proofreading=bad_proof,
        work_dir=tmp_path / "work",
    )
    assert report["checks"]["vo_asr"]["pass"] is False
    assert report["asr_proofreading"]["status"] == "applied"
    assert report["asr_proofreading"]["recomputed_verdict"] == "fail"
    assert "vo_asr" in report["failed_checks"]


def test_final_qc_proofreading_requires_proofreader(tmp_path: Path) -> None:
    media = _moving_video(tmp_path / "m.mp4")
    bad = {k: v for k, v in _PROOF.items() if k != "proofreader"}
    with pytest.raises(CapabilityError, match="proofreader"):
        run_final_qc(
            media, expected_vo_lines=["灯笼该点起来了"],
            asr_text="灯笼亮起来了", asr_proofreading=bad,
            work_dir=tmp_path / "work")


def test_final_qc_proofreading_requires_voice_attestation(tmp_path: Path) -> None:
    media = _moving_video(tmp_path / "m.mp4")
    bad = {**_PROOF, "voice_correct_attested": False}
    with pytest.raises(CapabilityError, match="voice_correct_attested"):
        run_final_qc(
            media, expected_vo_lines=["灯笼该点起来了"],
            asr_text="灯笼亮起来了", asr_proofreading=bad,
            work_dir=tmp_path / "work")


def test_final_qc_proofreading_rejects_verdict_fields(tmp_path: Path) -> None:
    media = _moving_video(tmp_path / "m.mp4")
    bad = {**_PROOF, "verdict": "pass"}
    with pytest.raises(CapabilityError, match="verdict"):
        run_final_qc(
            media, expected_vo_lines=["灯笼该点起来了"],
            asr_text="灯笼亮起来了", asr_proofreading=bad,
            work_dir=tmp_path / "work")


def test_final_qc_proofreading_without_original_evidence_rejected(
    tmp_path: Path,
) -> None:
    media = _moving_video(tmp_path / "m.mp4")
    with pytest.raises(CapabilityError, match="original VO evidence"):
        run_final_qc(
            media, asr_proofreading=dict(_PROOF), work_dir=tmp_path / "work")


def test_final_qc_proofreading_timestamp_defaults_to_now(tmp_path: Path) -> None:
    media = _moving_video(tmp_path / "m.mp4")
    proof = {k: v for k, v in _PROOF.items() if k != "timestamp"}
    report = run_final_qc(
        media,
        expected_vo_lines=["灯笼该点起来了"],
        asr_text="灯笼亮起来了",
        asr_proofreading=proof,
        work_dir=tmp_path / "work",
    )
    assert report["asr_proofreading"]["timestamp"]
    assert report["checks"]["vo_asr"]["pass"] is True


def test_final_qc_calls_asr_transcribe_via_audio_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    media = _moving_video(tmp_path / "m.mp4")
    audio = _silent_wav(tmp_path / "a.wav")

    def _fake_transcribe(audio_path, **kwargs):
        return {
            "transcript_raw": "燈籠該點起來了",
            "transcript_t2s": "灯笼该点起来了",
            "transcript_normalized": "灯笼该点起来了",
            "glossary_hits": [],
            "model": "small",
            "model_path": "/cached/small",
        }

    monkeypatch.setattr(
        "hevi.capabilities.asr_transcribe.transcribe_audio", _fake_transcribe)
    report = run_final_qc(
        media,
        expected_vo_lines=["灯笼该点起来了"],
        audio_path=audio,
        work_dir=tmp_path / "work",
    )
    assert report["checks"]["vo_asr"]["pass"] is True
    assert report["vo_asr_evidence"]["source"] == "audio.asr_transcribe"
    assert report["vo_asr_evidence"]["observed_text"] == "灯笼该点起来了"
    assert report["vo_asr_evidence"]["asr_evidence"]["model"] == "small"
