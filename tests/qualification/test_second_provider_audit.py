from __future__ import annotations

import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REQUIRED_KEYS = (
    "doctor",
    "generated_at",
    "candidates",
    "corpus",
    "summary",
    "second_independent_provider_ready",
    "second_independent_provider_counted",
    "distinct_succeeded_repro_providers",
    "cross_model_gate",
    "cross_model_qualified",
    "software_gate",
    "notes",
)

VALID_STATUSES = {
    "BASELINE_QUALIFIED",
    "FREE_LOCAL_RUNNABLE",
    "OWNER_BLOCKED_NO_CREDENTIAL",
    "OWNER_BLOCKED_SPEND",
    "ENV_BLOCKED",
    "NOT_REGISTERED_VIDEO",
}

REQUIRED_CANDIDATES = {
    "hyperframes",
    "manim",
    "remotion",
    "h3_local",
    "happyhorse_1_1",
    "veo3",
}


def test_second_provider_audit_contract() -> None:
    namespace = runpy.run_path(
        str(ROOT / "scripts" / "qualification" / "second_provider_audit.py")
    )
    report = namespace["run_audit"](probe=False)
    for key in REQUIRED_KEYS:
        assert key in report, key
    assert report["doctor"] == "second_provider"
    assert report["software_gate"] in {"PASS", "FAIL"}
    assert report["cross_model_gate"] in {"READY_FOR_REAL_RUN", "BLOCKED"}

    by_name = {item["provider"]: item for item in report["candidates"]}
    for name in REQUIRED_CANDIDATES:
        assert name in by_name, name
        assert by_name[name]["status"] in VALID_STATUSES, name
        assert by_name[name]["reason"], name

    for status in VALID_STATUSES:
        bucket = report["summary"].get(status)
        if status.startswith("OWNER_BLOCKED"):
            continue
        if bucket is None:
            continue
        expected = [
            item["provider"]
            for item in report["candidates"]
            if item["status"] == status
        ]
        assert sorted(bucket) == sorted(expected), status

    owner = {
        item["provider"]
        for item in report["candidates"]
        if item["status"].startswith("OWNER_BLOCKED")
    }
    assert sorted(report["summary"]["OWNER_BLOCKED"]) == sorted(owner)

    assert (
        report["second_independent_provider_ready"]
        == (
            bool(report["summary"]["FREE_LOCAL_RUNNABLE"])
            and bool(report["summary"]["BASELINE_QUALIFIED"])
        )
    )
    assert (
        report["software_gate"] == "FAIL"
    ) == bool(report.get("registration_error"))
    # Honesty bar: counted only when >=2 distinct succeeded durable repro
    # providers exist alongside a ready baseline+free-local pair.
    assert report["second_independent_provider_counted"] == (
        report["second_independent_provider_ready"]
        and int(report["distinct_succeeded_repro_providers"]) >= 2
    )
    assert report["cross_model_qualified"] == (
        report["second_independent_provider_counted"]
        and report["software_gate"] == "PASS"
    )

    # Secrets never appear as values — only PRESENT/ABSENT markers.
    for item in report["candidates"]:
        for value in item.get("credential_env", {}).values():
            assert value in {"PRESENT", "ABSENT"}, item["provider"]

    # Corpus projections are structured (live read or explicit error), never
    # a hardcoded magic count baked into the script.
    corpus = report["corpus"]
    assert isinstance(corpus, dict)
    assert "error" in corpus or "distinct_succeeded_repro_providers" in corpus

    assert report["notes"], "honesty notes required"


def test_second_provider_statuses_cover_baseline_and_manim() -> None:
    namespace = runpy.run_path(
        str(ROOT / "scripts" / "qualification" / "second_provider_audit.py")
    )
    report = namespace["run_audit"](probe=False)
    by_name = {item["provider"]: item for item in report["candidates"]}
    assert by_name["hyperframes"]["status"] == "BASELINE_QUALIFIED"
    # With probe disabled, manim cannot claim FREE_LOCAL_RUNNABLE — it must
    # classify honestly as ENV_BLOCKED (probe not run).
    assert by_name["manim"]["status"] == "ENV_BLOCKED"
    assert by_name["remotion"]["status"] == "NOT_REGISTERED_VIDEO"
    assert by_name["h3_local"]["status"] == "ENV_BLOCKED"
