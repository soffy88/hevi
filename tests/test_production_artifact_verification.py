"""V0..V3 verification — fail-closed behaviour.

The property under test throughout: an unobserved check is not a pass, and
UNKNOWN can never produce an ACCEPTED receipt.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hevi.creative.autonomous.verdict import VerdictInput
from hevi.production.artifact_verification import (
    Level,
    LevelOutcome,
    LevelResult,
    ReceiptStatus,
    ShotContract,
    _status_for,
    verify_artifact,
    verify_v0,
    verify_v1_subprocess,
    verify_v2,
    verify_v3,
)

REPO = Path(__file__).resolve().parents[1]
REAL_MP4 = REPO / "output/real_content_chain/20260924T085929Z/final_timeline.mp4"


def _real_mp4() -> Path:
    if not REAL_MP4.is_file():
        pytest.skip("real content artifact not present")
    return REAL_MP4


def _silent_video(tmp_path: Path, *, seconds: float = 2.0) -> Path:
    """A real, decodable MP4 with no audio stream."""
    out = tmp_path / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"color=c=black:s=320x240:d={seconds}", str(out)],
        check=True, capture_output=True,
    )
    return out


class TestV0Existence:
    def test_missing_file_fails(self, tmp_path: Path) -> None:
        result, _ = verify_v0(tmp_path / "nope.mp4")
        assert result.outcome is LevelOutcome.FAIL
        assert result.detail == "ARTIFACT_MISSING"

    def test_empty_file_fails(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty.mp4"
        empty.touch()
        result, _ = verify_v0(empty)
        assert result.outcome is LevelOutcome.FAIL
        assert result.detail == "ARTIFACT_EMPTY"

    def test_directory_is_not_an_artifact(self, tmp_path: Path) -> None:
        result, _ = verify_v0(tmp_path)
        assert result.outcome is LevelOutcome.FAIL

    def test_real_file_passes_with_hash(self) -> None:
        result, checksum = verify_v0(_real_mp4())
        assert result.outcome is LevelOutcome.PASS
        assert len(checksum) == 64
        assert result.evidence["sha256"] == checksum


class TestV1MediaValidity:
    def test_real_mp4_passes(self) -> None:
        result = verify_v1_subprocess(_real_mp4())
        assert result.outcome is LevelOutcome.PASS
        probe = result.evidence["probe"]
        assert probe["codec"] == "h264"
        assert probe["has_audio"] is True
        assert probe["aspect_ratio"] == "16:9"
        assert probe["duration"] > 0

    def test_non_media_file_fails(self, tmp_path: Path) -> None:
        junk = tmp_path / "junk.mp4"
        junk.write_bytes(b"this is not a video" * 100)
        result = verify_v1_subprocess(junk)
        assert result.outcome is LevelOutcome.FAIL

    def test_missing_ffprobe_is_unknown_not_pass(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The core fail-closed property of §8."""

        def _boom(*_a: object, **_k: object) -> None:
            raise FileNotFoundError("ffprobe")

        monkeypatch.setattr(subprocess, "run", _boom)
        result = verify_v1_subprocess(_real_mp4())
        assert result.outcome is LevelOutcome.UNKNOWN
        assert result.outcome is not LevelOutcome.PASS

    def test_probe_timeout_is_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _timeout(*_a: object, **_k: object) -> None:
            raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=1)

        monkeypatch.setattr(subprocess, "run", _timeout)
        result = verify_v1_subprocess(_real_mp4())
        assert result.outcome is LevelOutcome.UNKNOWN

    def test_audio_only_has_no_video_stream(self, tmp_path: Path) -> None:
        audio = tmp_path / "a.m4a"
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
             "-i", "sine=frequency=440:duration=2", str(audio)],
            check=True, capture_output=True,
        )
        result = verify_v1_subprocess(audio)
        assert result.outcome is LevelOutcome.FAIL
        assert "MEDIA_CODEC_INVALID" in result.detail


class TestV2ContractCompliance:
    def test_matching_contract_passes(self) -> None:
        v1 = verify_v1_subprocess(_real_mp4())
        contract = ShotContract(
            aspect_ratio="16:9", duration_min_s=11.0, duration_max_s=13.0,
            requires_audio=True,
        )
        assert verify_v2(v1.evidence, contract).outcome is LevelOutcome.PASS

    def test_technically_valid_but_wrong_shape_fails(self) -> None:
        """§7: a technically valid video can still fail V2."""
        v1 = verify_v1_subprocess(_real_mp4())
        contract = ShotContract(
            aspect_ratio="9:16", duration_min_s=60.0, duration_max_s=90.0,
        )
        result = verify_v2(v1.evidence, contract)
        assert result.outcome is LevelOutcome.FAIL
        assert "aspect_ratio" in result.detail
        assert "duration_min_s" in result.detail

    def test_missing_audio_fails_when_required(self, tmp_path: Path) -> None:
        silent = _silent_video(tmp_path)
        v1 = verify_v1_subprocess(silent)
        assert v1.outcome is LevelOutcome.PASS, "probe itself should pass"
        assert v1.evidence["probe"]["has_audio"] is False
        result = verify_v2(v1.evidence, ShotContract(requires_audio=True))
        assert result.outcome is LevelOutcome.FAIL
        assert "has_audio" in result.detail

    def test_audio_requirement_skipped_when_not_required(self, tmp_path: Path) -> None:
        silent = _silent_video(tmp_path)
        v1 = verify_v1_subprocess(silent)
        result = verify_v2(v1.evidence, ShotContract(requires_audio=False))
        assert result.outcome is LevelOutcome.PASS
        assert "has_audio" not in {c["field"] for c in result.evidence["checks"]}

    def test_no_v1_evidence_is_unknown(self) -> None:
        result = verify_v2({}, ShotContract(requires_audio=True))
        assert result.outcome is LevelOutcome.UNKNOWN


class TestV3Creative:
    def test_no_evidence_is_unknown(self) -> None:
        result = verify_v3(inputs=(), artifact_validated=True)
        assert result.outcome is LevelOutcome.UNKNOWN
        assert result.outcome is not LevelOutcome.PASS

    def test_failing_input_fails(self) -> None:
        result = verify_v3(
            inputs=(VerdictInput(source="gate", passed=False),),
            artifact_validated=True,
        )
        assert result.outcome is LevelOutcome.FAIL

    def test_passing_input_passes(self) -> None:
        result = verify_v3(
            inputs=(VerdictInput(source="gate", passed=True),),
            artifact_validated=True,
        )
        assert result.outcome is LevelOutcome.PASS

    def test_human_accept_is_a_decision_not_an_inference(self) -> None:
        result = verify_v3(
            inputs=(VerdictInput(source="gate", passed=True),),
            artifact_validated=True, human_review="ACCEPT",
        )
        assert result.outcome is LevelOutcome.PASS
        assert result.evidence["human_review"] == "ACCEPT"

    def test_human_reject_overrides_passing_machine_evidence(self) -> None:
        result = verify_v3(
            inputs=(VerdictInput(source="gate", passed=True),),
            artifact_validated=True, human_review="REJECT",
        )
        assert result.outcome is LevelOutcome.FAIL

    def test_human_cannot_accept_an_unvalidated_artifact(self) -> None:
        """§20: human acceptance records a decision; it does not erase evidence."""
        result = verify_v3(
            inputs=(), artifact_validated=False, human_review="ACCEPT",
        )
        assert result.outcome is not LevelOutcome.PASS

    def test_bad_human_verdict_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="human_review must be"):
            verify_v3(
                inputs=(VerdictInput(source="g", passed=True),),
                artifact_validated=True, human_review="looks good to me",
            )


class TestReceipt:
    def test_status_table_is_pinned(self) -> None:
        """Pin the whole outcome -> status table directly.

        Asserting it through verify_artifact only covered the combinations the
        other tests happened to construct, which let a redundant guard hide a
        real gap.
        """
        def _lv(level: Level, outcome: LevelOutcome) -> LevelResult:
            return LevelResult(level, outcome)

        # No FAIL anywhere means it is never rejected.
        for unknown in (LevelOutcome.PASS, LevelOutcome.UNKNOWN,
                        LevelOutcome.REQUIRES_HUMAN_REVIEW):
            levels = [_lv(Level.V0, LevelOutcome.PASS), _lv(Level.V3, unknown)]
            status = _status_for(levels)
            assert status is not ReceiptStatus.REJECTED
        # UNKNOWN blocks acceptance, which is the §8 property.
        assert _status_for([_lv(Level.V1, LevelOutcome.UNKNOWN)]) \
            is ReceiptStatus.UNVERIFIED
        # One FAIL is enough.
        assert _status_for(
            [_lv(Level.V0, LevelOutcome.PASS), _lv(Level.V1, LevelOutcome.FAIL),
             _lv(Level.V2, LevelOutcome.PASS)]
        ) is ReceiptStatus.REJECTED
        # All settled and passing.
        assert _status_for(
            [_lv(Level.V0, LevelOutcome.PASS), _lv(Level.V1, LevelOutcome.PASS)]
        ) is ReceiptStatus.ACCEPTED
        # Nothing verified is nothing accepted.
        assert _status_for([]) is ReceiptStatus.UNVERIFIED

    def test_unknown_never_yields_accepted(self, tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(*_a: object, **_k: object) -> None:
            raise FileNotFoundError("ffprobe")

        monkeypatch.setattr(subprocess, "run", _boom)
        _receipt, status = verify_artifact(
            _real_mp4(), run_id="r", task_id="t",
            creative_inputs=(VerdictInput(source="gate", passed=True),),
            human_review="ACCEPT",
        )
        assert status is ReceiptStatus.UNVERIFIED

    def test_missing_artifact_is_rejected(self, tmp_path: Path) -> None:
        receipt, status = verify_artifact(
            tmp_path / "gone.mp4", run_id="r", task_id="t")
        assert status is ReceiptStatus.REJECTED
        assert receipt["status"] == "REJECTED"

    def test_full_pass_produces_accepted_receipt(self) -> None:
        receipt, status = verify_artifact(
            _real_mp4(), run_id="run-1", task_id="task-1",
            contract=ShotContract(aspect_ratio="16:9", duration_min_s=11.0,
                                  duration_max_s=13.0, requires_audio=True),
            creative_inputs=(
                VerdictInput(source="technical", passed=True),
                VerdictInput(source="creative", passed=True),
            ),
            human_review="ACCEPT",
            executor="local_media_workflow", provider="QUALIFIED_SOURCE_NASA",
            shot_spec_hash="abc123",
        )
        assert status is ReceiptStatus.ACCEPTED
        assert receipt["status"] == "ACCEPTED"
        assert receipt["executor"] == "local_media_workflow"
        assert receipt["provider"] == "QUALIFIED_SOURCE_NASA"
        assert receipt["evidence"]["shot_spec_hash"] == "abc123"
        assert len(receipt["evidence"]["artifact_sha256"]) == 64
        assert [lv["level"] for lv in receipt["verification"]["levels"]] == ["V0", "V1", "V2", "V3"]
        assert all(lv["outcome"] == "PASS" for lv in receipt["verification"]["levels"])

    def test_receipt_records_every_level_with_its_reason(self, tmp_path: Path) -> None:
        junk = tmp_path / "junk.mp4"
        junk.write_bytes(b"not a video")
        receipt, status = verify_artifact(junk, run_id="r", task_id="t")
        assert status is ReceiptStatus.REJECTED
        levels = {lv["level"]: lv for lv in receipt["verification"]["levels"]}
        assert levels["V0"]["outcome"] == "PASS"
        assert levels["V1"]["outcome"] == "FAIL"
        assert levels["V1"]["detail"]
        assert levels["V2"]["outcome"] == "UNKNOWN", "V2 must not run past a failed V1"

    def test_verification_is_repeatable(self) -> None:
        contract = ShotContract(aspect_ratio="16:9", duration_min_s=11.0,
                                duration_max_s=13.0, requires_audio=True)
        runs = [
            verify_artifact(_real_mp4(), run_id="r", task_id="t", contract=contract)[0]
            for _ in range(2)
        ]
        a, b = runs
        assert a["evidence"]["artifact_sha256"] == b["evidence"]["artifact_sha256"]
        assert a["status"] == b["status"]
