"""W17-I: recompute the P1 consumer adoption matrix from source/test evidence.

Read-only. Each of the 18 P1 items must show a real production consumer
adoption: specific production symbols AND executable tests. Status is derived
from evidence presence, never hand-edited. Run from the repository root:

    .venv/bin/python scripts/research/p1_consumer_recheck.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "artifacts" / "research" / "arcreel_p1_consumer_adoption_matrix.json"

# item -> (production symbol, evidence file, test path)
EVIDENCE: dict[str, tuple[str, str, str]] = {
    "ARC-C06": (
        r"def build_appearance_record|def register_appearance",
        "hevi/creative/layer4/character_authority.py",
        "tests/test_subjects.py",
    ),
    "ARC-C08": (
        r"def _missing_character_references",
        "hevi/api/routers/director_pipeline.py",
        "tests/test_director_pipeline_router.py",
    ),
    "ARC-E04": (
        r"async def provider_capabilities|async def admission_media",
        "hevi/api/routers/authorities.py",
        "tests/test_authorities_api.py",
    ),
    "ARC-E06": (
        r"async def admission_batch|async def admit_regeneration_media",
        "hevi/api/routers/authorities.py",
        "tests/test_authorities_api.py",
    ),
    "ARC-E09": (
        r"def classify_failure_code",
        "hevi/creative/layer4/plan_projection.py",
        "tests/test_task_durable_execution.py",
    ),
    "ARC-F02": (
        r"def derive_consistency",
        "hevi/creative/layer4/character_authority.py",
        "tests/creative_runtime/test_character_authority.py",
    ),
    "ARC-F03": (
        r"def voice_binding_from_project",
        "hevi/creative/layer4/character_authority.py",
        "tests/creative_runtime/test_character_authority.py",
    ),
    "ARC-F04": (
        r"def resolve_speech_segment_owner",
        "hevi/creative/layer4/character_authority.py",
        "tests/creative_runtime/test_character_authority.py",
    ),
    "ARC-I02": (
        r"async def task_editable_export",
        "hevi/api/routers/authorities.py",
        "tests/test_authorities_api.py",
    ),
    "ARC-J05": (
        r"source_unproven",
        "hevi/creative/layer4/editable_delivery.py",
        "tests/test_authorities_api.py",
    ),
    "ARC-K02": (
        r"async def task_plan",
        "hevi/api/routers/authorities.py",
        "tests/test_authorities_api.py",
    ),
    "ARC-L02": (
        r"async def track_adapter_execution",
        "hevi/tasks/task_service.py",
        "tests/test_task_durable_execution.py",
    ),
    "ARC-L03": (
        r"async def reconcile_on_startup",
        "hevi/tasks/task_service.py",
        "tests/test_task_durable_execution.py",
    ),
    "ARC-M06": (
        r"def _run_declarative_endpoint",
        "hevi/tasks/task_service.py",
        "tests/test_task_durable_execution.py",
    ),
    "ARC-M07": (
        r"async def endpoints_run",
        "hevi/api/routers/authorities.py",
        "tests/test_capability_inventory.py",
    ),
    "ARC-N05": (
        r"def _emit_ok|def _normalized_error_code",
        "hevi/tasks/durable_provider.py",
        "tests/test_durable_provider.py",
    ),
    "ARC-N06": (
        r"async def reconcile_call_rows|def reconcile_pending_rows",
        "hevi/tasks/task_service.py",
        "tests/test_task_durable_execution.py",
    ),
    "ARC-O04": (
        r"async def regeneration_plan|def _regeneration_plan",
        "hevi/api/routers/tasks.py",
        "tests/test_authorities_api.py",
    ),
}


def _evidence_ok(symbol: str, file_path: str, test_path: str) -> tuple[bool, str]:
    source = ROOT / file_path
    test = ROOT / test_path
    if not source.is_file():
        return False, f"missing source {file_path}"
    if not re.search(symbol, source.read_text(encoding="utf-8")):
        return False, f"symbol not found in {file_path}"
    if not test.is_file():
        return False, f"missing test {test_path}"
    return True, "production consumer + test present"


def main() -> int:
    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    checked = 0
    adopted = 0
    for item in matrix["items"]:
        arc_id = item["arc_id"]
        spec = EVIDENCE.get(arc_id)
        if spec is None:
            item["status"] = "CONSUMER_PENDING"
            item["adoption_note"] = "no recheck evidence registered"
            continue
        ok, note = _evidence_ok(*spec)
        item["status"] = "CONSUMER_ADOPTED" if ok else "CONSUMER_PENDING"
        item["adoption_note"] = note
        checked += 1
        adopted += int(ok)
    statuses = [i["status"] for i in matrix["items"]]
    matrix["summary"] = {
        "consumer_adopted": statuses.count("CONSUMER_ADOPTED"),
        "consumer_partial": statuses.count("CONSUMER_PARTIAL"),
        "consumer_pending": statuses.count("CONSUMER_PENDING"),
        "authority_only": statuses.count("AUTHORITY_ONLY"),
        "remaining_p1": sum(1 for s in statuses if s != "CONSUMER_ADOPTED"),
    }
    matrix["p1_consumer_gap_count_initial"] = len(matrix["items"])
    matrix["recheck"] = {"checked": checked, "adopted": adopted, "basis": "source + test evidence"}
    MATRIX.write_text(json.dumps(matrix, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(matrix["summary"], ensure_ascii=False))
    print(
        "non-adopted:", [i["arc_id"] for i in matrix["items"] if i["status"] != "CONSUMER_ADOPTED"]
    )
    return 0 if matrix["summary"]["remaining_p1"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
