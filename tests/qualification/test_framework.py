from __future__ import annotations

import json
from pathlib import Path

from hevi.qualification.framework import discover_reports, write_reports
from hevi.qualification.media import validate_media

ROOT = Path(__file__).resolve().parents[2]


def test_discovery_uses_all_line_yaml_files(tmp_path: Path) -> None:
    reports = discover_reports(ROOT / "hevi/studio/lines", tmp_path)
    expected = sorted(path.stem for path in (ROOT / "hevi/studio/lines").glob("*.yaml"))
    assert [item["line"] for item in reports] == expected
    assert len(reports) == 13
    assert all(item["status"] in {
        "PRODUCTION_COMPLETE", "QUALIFIED", "PARTIAL", "BLOCKED_PROVIDER",
        "BLOCKED_HARDWARE", "FAILED",
    } for item in reports)


def test_reports_are_machine_readable_and_never_fake_artifacts(tmp_path: Path) -> None:
    reports = discover_reports(ROOT / "hevi/studio/lines", tmp_path)
    summary = write_reports(reports, tmp_path)
    assert summary["total"] == 13
    for item in reports:
        payload = json.loads((tmp_path / item["line"] / "result.json").read_text())
        assert payload["final_artifact"] is False
        assert payload["real_e2e"] is False


def test_media_validator_fails_missing_and_empty_artifacts(tmp_path: Path) -> None:
    missing = validate_media(tmp_path / "missing.mp4")
    assert missing.passed is False
    assert "artifact_missing" in missing.errors
    empty = tmp_path / "empty.mp4"
    empty.touch()
    result = validate_media(empty)
    assert result.passed is False
    assert "artifact_empty" in result.errors
