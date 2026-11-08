"""Tests for the VibeVoice graft (A1-A6 gates, B1-B2 fake contracts)."""

import pytest

from hevi.capabilities import list_capabilities
from hevi.capabilities import vibevoice_asr_longform_note as a6
from hevi.capabilities import vibevoice_license_note as a5
from hevi.capabilities import vibevoice_longform_honesty_gate as a4
from hevi.capabilities import vibevoice_longform_tts_contract as b2
from hevi.capabilities import vibevoice_realtime_speaker_gate as a3
from hevi.capabilities import vibevoice_realtime_speaker_index as b1
from hevi.capabilities import vibevoice_tts_disabled_gate as a1
from hevi.capabilities import (
    vibevoice_voice_prompt_authorization_gate as a2,
)
from hevi.capabilities.errors import CapabilityError

EXPECTED_NAMES = {
    "qa.vibevoice_tts_disabled_gate",
    "qa.vibevoice_voice_prompt_authorization_gate",
    "qa.vibevoice_realtime_speaker_gate",
    "qa.vibevoice_longform_honesty_gate",
    "qa.vibevoice_license_note",
    "qa.vibevoice_asr_longform_note",
    "video.vibevoice_realtime_speaker_index",
    "video.vibevoice_longform_tts_contract",
}


def test_all_eight_registered() -> None:
    names = {c.name for c in list_capabilities()}
    assert names >= EXPECTED_NAMES


# --- A1: TTS-1.5B disabled path ---


def _a1_claim(**overrides):
    claim = {
        "model": "vibevoice-tts-1.5b",
        "declares_disabled": True,
        "implementation": "third_party_reproduction",
        "declares_non_official": True,
        "declares_unverified": True,
    }
    claim.update(overrides)
    return claim


def test_a1_third_party_reproduction_passes() -> None:
    report = a1.check_vibevoice_tts_disabled(_a1_claim())
    assert report["verdict"] == "pass"
    assert report["executed_here"] is False


def test_a1_hevi_oprim_worker_passes() -> None:
    report = a1.check_vibevoice_tts_disabled(_a1_claim(implementation="hevi_oprim_worker"))
    assert report["verdict"] == "pass"


def test_a1_official_path_claim_fails() -> None:
    report = a1.check_vibevoice_tts_disabled(_a1_claim(official_path_available=True))
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "official_path_claimed"


def test_a1_official_code_claim_fails() -> None:
    report = a1.check_vibevoice_tts_disabled(_a1_claim(official_code_runs=True))
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "official_code_claimed"


def test_a1_official_implementation_fails() -> None:
    report = a1.check_vibevoice_tts_disabled(_a1_claim(implementation="official"))
    assert report["verdict"] == "fail"


def test_a1_disabled_not_declared_fails() -> None:
    report = a1.check_vibevoice_tts_disabled(_a1_claim(declares_disabled=False))
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "disabled_not_declared"


def test_a1_reproduction_must_declare_non_official() -> None:
    report = a1.check_vibevoice_tts_disabled(_a1_claim(declares_non_official=False))
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "reproduction_not_declared_non_official"


def test_a1_reproduction_must_declare_unverified() -> None:
    report = a1.check_vibevoice_tts_disabled(_a1_claim(declares_unverified=False))
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "reproduction_not_declared_unverified"


def test_a1_model_mismatch_and_non_object_fail() -> None:
    assert a1.check_vibevoice_tts_disabled(_a1_claim(model="vibevoice-x"))["verdict"] == "fail"
    assert a1.check_vibevoice_tts_disabled("not a dict")["verdict"] == "fail"


# --- A2: voice-prompt authorization ---


def _auth(kind="own"):
    return {
        "voice_id": "host-voice",
        "authorization_kind": kind,
        "evidence_ref": "consent-record-001",
    }


def test_a2_embedded_prompt_passes_without_auth() -> None:
    report = a2.check_vibevoice_voice_prompt_authorization({"voice_prompt": {"source": "embedded"}})
    assert report["verdict"] == "pass"


def test_a2_reference_audio_with_auth_passes() -> None:
    report = a2.check_vibevoice_voice_prompt_authorization(
        {
            "voice_prompt": {"source": "reference_audio"},
            "voice_authorization": _auth(),
        }
    )
    assert report["verdict"] == "pass"
    assert report["voice_id"] == "host-voice"


def test_a2_script_voice_ref_with_auth_passes() -> None:
    report = a2.check_vibevoice_voice_prompt_authorization(
        {
            "script": [{"speaker": "host", "text": "hi", "voice_ref": "ref.wav"}],
            "voice_authorization": _auth("licensed"),
        }
    )
    assert report["verdict"] == "pass"


def test_a2_reference_audio_without_auth_fails() -> None:
    report = a2.check_vibevoice_voice_prompt_authorization(
        {"voice_prompt": {"source": "reference_audio"}}
    )
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "voice_prompt_authorization_missing"


def test_a2_clone_requests_fail() -> None:
    assert a2.check_vibevoice_voice_prompt_authorization({"clone_voice": True})["verdict"] == "fail"
    assert (
        a2.check_vibevoice_voice_prompt_authorization({"voice_prompt": {"kind": "clone"}})[
            "verdict"
        ]
        == "fail"
    )


def test_a2_auth_without_evidence_fails() -> None:
    auth = _auth()
    del auth["evidence_ref"]
    report = a2.check_vibevoice_voice_prompt_authorization(
        {
            "voice_prompt": {"source": "reference_audio"},
            "voice_authorization": auth,
        }
    )
    assert report["verdict"] == "fail"


def test_a2_unknown_source_fails() -> None:
    report = a2.check_vibevoice_voice_prompt_authorization({"voice_prompt": {"source": "mystery"}})
    assert report["verdict"] == "fail"
    assert report["issues"][0]["code"] == "voice_prompt_source_unknown"


# --- A3: Realtime embedded speaker ---


def test_a3_embedded_english_passes() -> None:
    report = a3.check_vibevoice_realtime_speaker(
        {
            "model": "vibevoice-realtime-0.5b",
            "speaker_id": "en-Carter_man",
            "speaker_source": "embedded",
            "language": "en",
        }
    )
    assert report["verdict"] == "pass"


def test_a3_experimental_language_needs_ack() -> None:
    plan = {
        "speaker_id": "de-Spk0_man",
        "speaker_source": "embedded",
        "language": "de",
    }
    assert a3.check_vibevoice_realtime_speaker(plan)["verdict"] == "fail"
    plan["experimental_language_acknowledged"] = True
    assert a3.check_vibevoice_realtime_speaker(plan)["verdict"] == "pass"


def test_a3_official_team_custom_passes_with_contact() -> None:
    report = a3.check_vibevoice_realtime_speaker(
        {
            "speaker_source": "official_team_custom",
            "official_team_contact_ref": "team-ticket-42",
        }
    )
    assert report["verdict"] == "pass"


def test_a3_reference_audio_and_unknown_speaker_fail() -> None:
    assert (
        a3.check_vibevoice_realtime_speaker(
            {
                "speaker_id": "en-Carter_man",
                "speaker_source": "reference_audio",
                "language": "en",
            }
        )["verdict"]
        == "fail"
    )
    assert (
        a3.check_vibevoice_realtime_speaker(
            {
                "speaker_id": "en-Nobody_man",
                "speaker_source": "embedded",
                "language": "en",
            }
        )["verdict"]
        == "fail"
    )


def test_a3_language_mismatch_and_pt_file_fail() -> None:
    assert (
        a3.check_vibevoice_realtime_speaker(
            {
                "speaker_id": "en-Carter_man",
                "speaker_source": "embedded",
                "language": "de",
            }
        )["verdict"]
        == "fail"
    )
    assert (
        a3.check_vibevoice_realtime_speaker(
            {
                "speaker_id": "en-Carter_man.pt",
                "speaker_source": "embedded",
                "language": "en",
            }
        )["verdict"]
        == "fail"
    )


# --- A4: long-form honesty ---


def _a4_claim(**overrides):
    claim = {
        "model": "vibevoice-tts-1.5b",
        "claim_kind": "research",
        "declares_official_disabled": True,
        "declares_research_status": True,
        "single_pass_minutes": 90,
        "speakers": 4,
        "languages": ["en", "zh"],
    }
    claim.update(overrides)
    return claim


def test_a4_research_claim_passes() -> None:
    report = a4.check_vibevoice_longform_honesty(_a4_claim())
    assert report["verdict"] == "pass"


def test_a4_realtime_envelope_passes() -> None:
    report = a4.check_vibevoice_longform_honesty(
        {
            "model": "vibevoice-realtime-0.5b",
            "claim_kind": "research",
            "single_pass_minutes": 10,
            "speakers": 1,
        }
    )
    assert report["verdict"] == "pass"


def test_a4_production_and_verified_1p5b_fail() -> None:
    assert (
        a4.check_vibevoice_longform_honesty(_a4_claim(claim_kind="production"))["verdict"] == "fail"
    )
    assert (
        a4.check_vibevoice_longform_honesty(_a4_claim(claim_kind="verified"))["verdict"] == "fail"
    )


def test_a4_missing_declarations_fail() -> None:
    assert (
        a4.check_vibevoice_longform_honesty(_a4_claim(declares_official_disabled=False))["verdict"]
        == "fail"
    )
    assert (
        a4.check_vibevoice_longform_honesty(_a4_claim(declares_research_status=False))["verdict"]
        == "fail"
    )


def test_a4_envelope_overflows_fail() -> None:
    assert (
        a4.check_vibevoice_longform_honesty(_a4_claim(single_pass_minutes=91))["verdict"] == "fail"
    )
    assert a4.check_vibevoice_longform_honesty(_a4_claim(speakers=5))["verdict"] == "fail"
    assert (
        a4.check_vibevoice_longform_honesty(_a4_claim(languages=["en", "fr"]))["verdict"] == "fail"
    )
    assert (
        a4.check_vibevoice_longform_honesty(
            {
                "model": "vibevoice-realtime-0.5b",
                "claim_kind": "research",
                "single_pass_minutes": 11,
                "speakers": 1,
            }
        )["verdict"]
        == "fail"
    )
    assert (
        a4.check_vibevoice_longform_honesty(
            {
                "model": "vibevoice-realtime-0.5b",
                "claim_kind": "research",
                "single_pass_minutes": 10,
                "speakers": 2,
            }
        )["verdict"]
        == "fail"
    )


# --- A5: license note ---


def test_a5_recorded_note_passes() -> None:
    assert a5.check_vibevoice_license_note(a5.vibevoice_license_notes())["verdict"] == "pass"


def test_a5_mixed_and_commercial_claims_fail() -> None:
    note = a5.vibevoice_license_notes()
    note["code_license"] = "Apache-2.0"
    assert a5.check_vibevoice_license_note(note)["verdict"] == "fail"
    note = a5.vibevoice_license_notes()
    note["mit_covers_weights"] = True
    assert a5.check_vibevoice_license_note(note)["verdict"] == "fail"
    note = a5.vibevoice_license_notes()
    note["weight_license_source"] = "repository"
    assert a5.check_vibevoice_license_note(note)["verdict"] == "fail"
    note = a5.vibevoice_license_notes()
    note["repo_weight_license"] = "MIT"
    assert a5.check_vibevoice_license_note(note)["verdict"] == "fail"
    note = a5.vibevoice_license_notes()
    note["commercial_use"] = "commercial"
    assert a5.check_vibevoice_license_note(note)["verdict"] == "fail"
    note["research_only_warning"] = True
    assert a5.check_vibevoice_license_note(note)["verdict"] == "pass"


# --- A6: ASR long-form note ---


def test_a6_recorded_note_passes() -> None:
    assert a6.check_vibevoice_asr_note(a6.vibevoice_asr_notes())["verdict"] == "pass"


def test_a6_implementation_and_tts_claims_fail() -> None:
    assert a6.check_vibevoice_asr_note({"claims_hevi_implements": True})["verdict"] == "fail"
    assert a6.check_vibevoice_asr_note({"claims_tts_solution": True})["verdict"] == "fail"
    assert a6.check_vibevoice_asr_note({"bitnet_cpu": {"is_tts": True}})["verdict"] == "fail"
    assert a6.check_vibevoice_asr_note({"single_pass_minutes": 61})["verdict"] == "fail"
    assert (
        a6.check_vibevoice_asr_note({"structured_output": ["who", "sentiment"]})["verdict"]
        == "fail"
    )


# --- B1: Realtime speaker index ---


def _full_index():
    return {
        "speakers": [
            {
                "speaker_id": speaker_id,
                "language": b1.speaker_language(speaker_id),
                "style": b1.speaker_style(speaker_id),
                "format": "embedded",
            }
            for speaker_id in b1.EMBEDDED_SPEAKERS
        ]
    }


def test_b1_full_index_passes_with_25_speakers() -> None:
    assert len(b1.EMBEDDED_SPEAKERS) == 25
    contract = b1.compile_vibevoice_realtime_speaker_index(_full_index())
    assert contract["speaker_count"] == 25
    assert contract["executed_here"] is False
    assert contract["audio_included"] is False
    assert contract["weights_downloaded"] is False


def test_b1_single_speaker_passes() -> None:
    contract = b1.compile_vibevoice_realtime_speaker_index(
        {
            "speakers": [
                {
                    "speaker_id": "en-Emma_woman",
                    "language": "en",
                    "style": "woman",
                    "format": "embedded",
                }
            ]
        }
    )
    assert contract["speaker_count"] == 1


def test_b1_unknown_speaker_language_style_format_fail() -> None:
    base = {
        "speaker_id": "en-Emma_woman",
        "language": "en",
        "style": "woman",
        "format": "embedded",
    }
    with pytest.raises(CapabilityError):
        b1.compile_vibevoice_realtime_speaker_index(
            {"speakers": [{**base, "speaker_id": "en-Nobody_man"}]}
        )
    with pytest.raises(CapabilityError):
        b1.compile_vibevoice_realtime_speaker_index({"speakers": [{**base, "language": "de"}]})
    with pytest.raises(CapabilityError):
        b1.compile_vibevoice_realtime_speaker_index({"speakers": [{**base, "style": "man"}]})
    with pytest.raises(CapabilityError):
        b1.compile_vibevoice_realtime_speaker_index(
            {"speakers": [{**base, "format": "reference_audio"}]}
        )


def test_b1_duplicates_pt_refs_and_empty_fail() -> None:
    base = {
        "speaker_id": "en-Emma_woman",
        "language": "en",
        "style": "woman",
        "format": "embedded",
    }
    with pytest.raises(CapabilityError):
        b1.compile_vibevoice_realtime_speaker_index({"speakers": [base, base]})
    with pytest.raises(CapabilityError):
        b1.compile_vibevoice_realtime_speaker_index({"speakers": [{**base, "audio_path": "x.pt"}]})
    with pytest.raises(CapabilityError):
        b1.compile_vibevoice_realtime_speaker_index(
            {"speakers": [{**base, "reference_audio": "ref.wav"}]}
        )
    with pytest.raises(CapabilityError):
        b1.compile_vibevoice_realtime_speaker_index({"speakers": []})
    with pytest.raises(CapabilityError):
        b1.compile_vibevoice_realtime_speaker_index("not a dict")


# --- B2: long-form TTS contract ---


def _b2_plan(**overrides):
    plan = {
        "model": "vibevoice-tts-1.5b",
        "dialogue": [
            {"speaker": "host", "text": "Welcome back."},
            {"speaker": "guest", "text": "Glad to be here."},
        ],
        "single_pass_minutes": 45,
        "sample_rate_hz": 24000,
        "languages": ["en", "zh"],
    }
    plan.update(overrides)
    return plan


def test_b2_contract_passes() -> None:
    contract = b2.compile_vibevoice_longform_tts_contract(_b2_plan())
    assert contract["speaker_count"] == 2
    assert contract["lines"] == 2
    assert contract["executed_here"] is False
    assert contract["gpu_required"] is True
    assert contract["output_file"] is None


def test_b2_word_anchor_and_authorized_prompt_pass() -> None:
    plan = _b2_plan(
        word_anchor=True,
        dialogue=[
            {
                "speaker": "host",
                "text": "Welcome back.",
                "word_anchors": ["Welcome"],
                "voice_prompt": {"source": "reference_audio"},
            }
        ],
        voice_authorization=_auth(),
    )
    contract = b2.compile_vibevoice_longform_tts_contract(plan)
    assert contract["word_anchor"] is True


def test_b2_envelope_and_shape_failures() -> None:
    with pytest.raises(CapabilityError):
        b2.compile_vibevoice_longform_tts_contract(_b2_plan(model="vibevoice-realtime-0.5b"))
    with pytest.raises(CapabilityError):
        b2.compile_vibevoice_longform_tts_contract(
            _b2_plan(dialogue=[{"speaker": f"s{i}", "text": "hi"} for i in range(5)])
        )
    with pytest.raises(CapabilityError):
        b2.compile_vibevoice_longform_tts_contract(_b2_plan(single_pass_minutes=91))
    with pytest.raises(CapabilityError):
        b2.compile_vibevoice_longform_tts_contract(_b2_plan(sample_rate_hz=16000))
    with pytest.raises(CapabilityError):
        b2.compile_vibevoice_longform_tts_contract(_b2_plan(languages=["en", "fr"]))
    with pytest.raises(CapabilityError):
        b2.compile_vibevoice_longform_tts_contract(_b2_plan(dialogue=[]))
    with pytest.raises(CapabilityError):
        b2.compile_vibevoice_longform_tts_contract("not a dict")


def test_b2_execution_clone_and_auth_failures() -> None:
    with pytest.raises(CapabilityError):
        b2.compile_vibevoice_longform_tts_contract(_b2_plan(executed_here=True))
    with pytest.raises(CapabilityError):
        b2.compile_vibevoice_longform_tts_contract(
            _b2_plan(
                dialogue=[
                    {
                        "speaker": "host",
                        "text": "hi",
                        "voice_prompt": {"kind": "clone"},
                    }
                ]
            )
        )
    with pytest.raises(CapabilityError):
        b2.compile_vibevoice_longform_tts_contract(
            _b2_plan(
                dialogue=[
                    {
                        "speaker": "host",
                        "text": "hi",
                        "voice_prompt": {"source": "reference_audio"},
                    }
                ]
            )
        )
    with pytest.raises(CapabilityError):
        b2.compile_vibevoice_longform_tts_contract(
            _b2_plan(
                word_anchor=True,
                dialogue=[{"speaker": "host", "text": "hi"}],
            )
        )
