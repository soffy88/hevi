"""Generate an evidence-oriented closure ledger for currently partial InkOS capabilities.

This is qualification tooling only.  It does not change capability status or runtime
state; it makes each missing evidence class explicit before a wave is executed.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
LEDGER = ROOT / "docs/research/inkos_capability_ledger.yaml"
OUTPUT = ROOT / "artifacts/qualification/creative-partial-closure.json"

MISSING: dict[str, dict[str, str]] = {
    "unified-agent-production-harness": {
        "missing_evidence": "Studio/CLI/TUI parity and persisted artifact-grounded completion",
        "missing_runtime_path": "service -> ProductionHarness -> persisted ProductionRun",
        "missing_persistence": "durable action envelope and run snapshot",
        "missing_fault_test": "cancel/reconnect and missing-artifact fail-closed run",
        "missing_e2e": "real service request through completion and restart",
        "missing_product_surface": "canonical Studio service route",
        "missing_quality_gate": "artifact and result truth gate",
        "blocking_dependency": "service/runtime integration",
    },
    "longform-narrative-production": {
        "missing_evidence": "complete stage settlement with canonical commit and restart recovery",
        "missing_runtime_path": "LongFormWorkflow stage output -> workspace -> canon commit",
        "missing_persistence": "stage artifacts, summaries, hooks, and canon revision",
        "missing_fault_test": "settlement crash and bounded revision recovery",
        "missing_e2e": "one real multi-stage longform run with durable artifacts",
        "missing_product_surface": "longform ProductionRun surface",
        "missing_quality_gate": "manuscript/canon/hook/audit completeness",
        "blocking_dependency": "atomic workspace and snapshot evidence",
    },
    "canonical-narrative-state": {
        "missing_evidence": "all state dimensions and cross-project authority validation",
        "missing_runtime_path": "typed delta -> authority validator -> canonical persistence",
        "missing_persistence": "projection rebuild and revision ledger",
        "missing_fault_test": "malformed, duplicate, stale, and cross-project deltas",
        "missing_e2e": "real project mutation sequence and reload",
        "missing_product_surface": "canonical state service surface",
        "missing_quality_gate": "monotonic revision and provenance completeness",
        "blocking_dependency": "state authority integration",
    },
    "observer-state-extraction": {
        "missing_evidence": "nine-class observation stored and explicitly settled",
        "missing_runtime_path": "chapter artifact -> observation -> validated delta",
        "missing_persistence": "observation and accepted-delta records",
        "missing_fault_test": "malformed JSON, unknown entity, conflict, stale revision",
        "missing_e2e": "real chapter observation with restart",
        "missing_product_surface": "observation/audit service result",
        "missing_quality_gate": "no direct LLM canonical mutation",
        "blocking_dependency": "canonical state closure",
    },
    "governed-context-composer": {
        "missing_evidence": "cross-module ContextManifest selection trace",
        "missing_runtime_path": "task request -> governed working set -> persisted manifest",
        "missing_persistence": "selected/excluded/compressed/protected decisions",
        "missing_fault_test": "protected fact overflow and stale source reference",
        "missing_e2e": "draft/revision/audit/forecast/script contexts",
        "missing_product_surface": "context trace in production run",
        "missing_quality_gate": "protected constraints never silently dropped",
        "blocking_dependency": "canonical state and memory closure",
    },
    "long-term-creative-memory": {
        "missing_evidence": "50-chapter relevance, temporal retrieval, and rebuild report",
        "missing_runtime_path": "chapter/material facts -> isolated index -> traced retrieval",
        "missing_persistence": "rebuildable records and source hashes",
        "missing_fault_test": "corrupt record and credential/cross-project leakage",
        "missing_e2e": "restart and index rebuild on longform fixture",
        "missing_product_surface": "memory query service",
        "missing_quality_gate": "source trace and no secret indexing",
        "blocking_dependency": "canonical state closure",
    },
    "continuity-and-multidimensional-audit": {
        "missing_evidence": "positive/negative deterministic corpus for every audit dimension",
        "missing_runtime_path": "artifact/canon -> 33-dimension audit -> persisted findings",
        "missing_persistence": "findings, locations, refs, severity, and re-audit history",
        "missing_fault_test": "missing state and malformed audit input fail closed",
        "missing_e2e": "defect corpus through audit and repeatability",
        "missing_product_surface": "review/audit artifact surface",
        "missing_quality_gate": "deterministic gates for structural facts",
        "blocking_dependency": "canonical state and revision closure",
    },
    "governed-revision": {
        "missing_evidence": "all four revision modes with re-audit and atomic approval",
        "missing_runtime_path": "audit -> proposal -> candidate -> diff -> approval -> commit",
        "missing_persistence": "candidate, diff, approval, remaining findings",
        "missing_fault_test": "stale write, rejection, limit, and process interruption",
        "missing_e2e": "real artifact revision and reload",
        "missing_product_surface": "revision proposal/approval service",
        "missing_quality_gate": "failed issues retained and no false pass",
        "blocking_dependency": "atomic workspace closure",
    },
}

WAVE_GAPS = {
    "short-fiction-production": "complete sales package persistence and export recovery",
    "script-runtime": "downstream production graph handoff with artifact provenance",
    "production-storyboard": "real ShotPlan/production consumption and quality evidence",
    "interactive-film": "playable package persistence and full graph negative controls",
    "persistent-interactive-play": "durable redo/recovery and visual asset references",
    "creative-research": "explicit claim acceptance and canonical commit evidence",
    "material-library": "multi-format source authority, citation, and isolation evidence",
    "existing-work-import-continuation": "20+ chapter reconstruction and three-chapter continuation",
    "style-intelligence": "abstract profile persistence and no-text-retention evidence",
    "synthetic-writing-quality": "defect corpus with bounded repair and false-positive evidence",
    "extensible-genre-system": "five effective profiles with planning/audit behavior evidence",
    "creative-analytics": "ledger reconciliation for cost, latency, recovery, and audit metrics",
    "translation-localization": "review/resume/roundtrip evidence across four formats",
    "cover-visual-asset-runtime": "existing visual provider artifact and regeneration provenance",
    "professional-skills": "adversarial authority/permission boundary evidence",
    "creative-policy-packs": "precedence, version diff, rollback, and invalid-pack evidence",
    "review-workflow": "durable approval/rejection and stale guard evidence",
    "background-production-notifications": "runtime-backed reconnect/cancel/resume and event evidence",
    "run-snapshot-recovery": "stage-wide crash/restart and partial-artifact evidence",
    "atomic-creative-workspace": "all listed transaction fault paths and read-back evidence",
    "backup-restore-rollback": "corruption rejection and semantic restore evidence",
    "concurrency-and-locks": "two-writer live lock/lease recovery evidence",
    "targeted-editing": "semantic locator and CAS/cascade evidence",
    "model-provider-routing": "real endpoint routing/failure and provenance trace",
    "notifications-webhooks": "event taxonomy, receiver, retry, idempotency, redaction",
    "creative-export": "approved artifact package hashes and EPUB reopen evidence",
    "studio-product-surfaces": "real Studio E2E over one canonical backend",
}


def main() -> None:
    source = yaml.safe_load(LEDGER.read_text(encoding="utf-8"))
    entries = []
    for item in source["capabilities"]:
        if item["status"] != "PARTIAL":
            continue
        explicit = MISSING.get(item["id"], {})
        gap = explicit.get("missing_evidence", WAVE_GAPS.get(item["id"], item["hevi_gap"]))
        entries.append(
            {
                "capability_id": item["id"],
                "current_status": item["status"],
                "missing_evidence": gap,
                "missing_runtime_path": explicit.get(
                    "missing_runtime_path",
                    "existing module -> qualification runner -> persisted evidence",
                ),
                "missing_persistence": explicit.get(
                    "missing_persistence", "durable artifact/state/revision manifest"
                ),
                "missing_fault_test": explicit.get(
                    "missing_fault_test", "capability-specific interruption and fail-closed path"
                ),
                "missing_e2e": explicit.get("missing_e2e", item["qualification_test"]),
                "missing_product_surface": explicit.get(
                    "missing_product_surface", "HEVI service or Studio surface"
                ),
                "missing_quality_gate": explicit.get(
                    "missing_quality_gate", "deterministic capability quality gate"
                ),
                "blocking_dependency": explicit.get(
                    "blocking_dependency", "wave dependency closure"
                ),
                "acceptance_commands": [
                    "PYTHONPATH=. uv run --no-sync pytest -q tests/creative_runtime tests/gold/creative_runtime",
                    "PYTHONPATH=. uv run --no-sync python scripts/qualification/qualify_creative_runtime.py --capability "
                    + item["id"],
                ],
                "evidence_paths": [
                    "artifacts/qualification/creative-runtime/" + item["id"] + ".json",
                    "tests/gold/creative_runtime/test_qualification.py",
                ],
            }
        )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_from": "docs/research/inkos_capability_ledger.yaml",
                "partial_total": len(entries),
                "entries": entries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
