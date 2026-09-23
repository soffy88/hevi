from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_CHECKS = (
    "torch",
    "torchvision_consistency",
    "transformers.modeling_utils",
    "vibevoice_patch",
    "provider_registration",
    "ffmpeg_ffprobe",
    "cuda",
    "hyperframes_cli",
)
VALID_STATUSES = {"PASS", "FAIL", "ENV_BLOCKED"}


def test_environment_doctor_contract_is_self_consistent() -> None:
    namespace = runpy.run_path(str(ROOT / "scripts" / "qualification" / "environment_doctor.py"))
    report = namespace["run_doctor"]()
    assert report["doctor"] == "environment"
    assert report["software_gate"] in {"PASS", "FAIL"}
    checks = report["checks"]
    by_name = {item["check"]: item for item in checks}
    for name in REQUIRED_CHECKS:
        assert name in by_name
        assert by_name[name]["status"] in VALID_STATUSES
        assert by_name[name]["detail"]
    for status in VALID_STATUSES:
        assert report["summary"].get(status, 0) == sum(
            1 for item in checks if item["status"] == status
        )
    assert (report["software_gate"] == "FAIL") == (report["summary"].get("FAIL", 0) > 0)
    assert set(report["classification"]["ENV_BLOCKED"]) == {
        item["check"] for item in checks if item["status"] == "ENV_BLOCKED"
    }
