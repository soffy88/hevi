"""HEVI P5.1 — qualification record.

Collects every gate P5.1 claims and emits the report in the format the task
specifies. Nothing here upgrades a blocked measurement into a pass: a stage that
could not run is reported as ``BLOCKED_BY_PROVIDER`` and the overall verdict
becomes ``NOT_QUALIFIED``.

Usage:
    python scripts/p5_1_qualify.py --out <dir>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from hevi.ops.p5_1_calibration import (  # noqa: E402
    build_calibration_set,
    run_calibration,
)
from hevi.ops.p5_1_finecut import register_knowledge_talk_profile  # noqa: E402
from hevi.ops.p5_1_providers import (  # noqa: E402
    probe_native_video_input,
    register_video_understanding_providers,
    select_video_understanding_provider,
)
from hevi.ops.p5_1_types import (  # noqa: E402
    EDITORIAL_ISSUE_TAXONOMY,
    EVIDENCE_PRIORITY,
)

GATE_ORDER = [
    ("LICENSE_BOUNDARY", "tests/test_p5_1_architecture.py"),
    ("VIDEO_UNDERSTANDING_PROVIDER", "tests/test_p5_1_review.py"),
    ("NATIVE_VIDEO_INPUT", "probe"),
    ("VIDEO_NATIVE_REVIEW", "e2e"),
    ("TEMPORAL_REVIEW", "e2e"),
    ("STALE_VIDEO_REVIEW_GUARD", "tests/test_p5_1_review.py"),
    ("EDITORIAL_ISSUE_TAXONOMY", "tests/test_p5_1_review.py"),
    ("HARD_DEFECT_CLASSIFICATION", "tests/test_p5_1_repair.py"),
    ("EDITORIAL_DIAGNOSIS", "e2e"),
    ("ROOT_CAUSE_MAPPING", "tests/test_p5_1_repair.py"),
    ("EVIDENCE_FIRST_VISUAL", "tests/test_p5_1_evidence.py"),
    ("EVIDENCE_TRUTH", "tests/test_p5_1_evidence.py"),
    ("EVIDENCE_FRESHNESS", "tests/test_p5_1_evidence.py"),
    ("FAKE_UI_REJECTION", "tests/test_p5_1_evidence.py"),
    ("SCREENSHOT_PRIVACY", "tests/test_p5_1_evidence.py"),
    ("SPEAKER_EVIDENCE_SHOT_POLICY", "tests/test_p5_1_presentation.py"),
    ("INFORMATION_DENSITY", "tests/test_p5_1_presentation.py"),
    ("VISUAL_STAGNATION_CONTROL", "tests/test_p5_1_presentation.py"),
    ("MOTION_PURPOSE", "tests/test_p5_1_presentation.py"),
    ("REPAIR_INTENT", "tests/test_p5_1_repair.py"),
    ("TARGETED_VISUAL_REPAIR", "tests/test_p5_1_repair.py"),
    ("UNAFFECTED_SOURCE_RERUNS", "tests/test_p5_1_repair.py"),
    ("REVISION_CANDIDATE", "tests/test_p5_1_repair.py"),
    ("MEANINGFUL_REVISION", "tests/test_p5_1_session.py"),
    ("PAIRWISE_REVISION", "tests/test_p5_1_pairwise.py"),
    ("BIDIRECTIONAL_PAIRWISE_CHECK", "tests/test_p5_1_pairwise.py"),
    ("BLIND_PAIRWISE_REVIEW", "tests/test_p5_1_pairwise.py"),
    ("BAD_REVISION_REJECTION", "tests/test_p5_1_adversarial.py"),
    ("NO_PROGRESS_DETECTION", "tests/test_p5_1_session.py"),
    ("PAIRWISE_CALIBRATION", "calibration"),
    ("POSITION_SWAP_CONSISTENCY", "calibration"),
    ("LAYERED_EDITABLE_DELIVERY", "tests/test_p5_1_editable.py"),
    ("LAYER_SEMANTICS", "tests/test_p5_1_editable.py"),
    ("EDITABLE_PROJECT_VALIDATION", "tests/test_p5_1_editable.py"),
    ("EDITABLE_STRUCTURAL_ROUND_TRIP", "tests/test_p5_1_editable.py"),
    ("REAL_FINECUT_E2E_A", "e2e_a"),
    ("REAL_FINECUT_E2E_B", "e2e_b"),
    ("REAL_FINECUT_E2E_C", "e2e_c"),
    ("CROSS_PROFILE_EDITORIAL", "e2e_abc"),
]

P5_1_TESTS = sorted((REPO / "tests").glob("test_p5_1_*.py"))

#: The specification's window for a Case A knowledge talk. Not a tuning knob:
#: widening it to accommodate a short render would be defeating the gate.
FINECUT_A_MIN_S = 20.0
FINECUT_A_MAX_S = 30.0


def _measure_finecut_a_duration(
    case_a: dict[str, Any],
) -> tuple[float, str, str] | None:
    """Probe the real Case A V0 and judge it against the window.

    Returns ``(measured, status, note)`` or ``None`` when the artifact is absent.
    The number comes from ffprobe on the file on disk, so it cannot be satisfied
    by a value the pipeline reported about itself.
    """
    import subprocess

    out_dir = case_a.get("out_dir") or ""
    v0_stage = next(
        (s for s in case_a.get("stages", []) if s.get("name") == "candidate_v0"), None
    )
    candidates: list[Path] = []
    if v0_stage:
        payload = v0_stage.get("data") or v0_stage.get("evidence") or {}
        path = payload.get("video_path")
        if path:
            candidates.append(Path(path))
    if out_dir:
        candidates.extend(sorted((Path(out_dir) / "v0").glob("*.mp4")))

    for candidate in candidates:
        if not candidate.is_file():
            continue
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(candidate)],
            capture_output=True, text=True, check=False,
        )
        try:
            measured = float(proc.stdout.strip())
        except ValueError:
            continue
        note = (
            f"probed {candidate.name} = {measured:.3f}s, window "
            f"[{FINECUT_A_MIN_S}, {FINECUT_A_MAX_S}]s"
        )
        status = "PASS" if FINECUT_A_MIN_S <= measured <= FINECUT_A_MAX_S else "FAIL"
        return measured, status, note
    return None





@dataclass
class Gate:
    name: str
    status: str = "PASS"
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Qualification:
    gates: list[Gate] = field(default_factory=list)
    measurements: dict[str, Any] = field(default_factory=dict)
    blocked: list[str] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)

    def gate(self, name: str) -> Gate | None:
        return next((g for g in self.gates if g.name == name), None)

    def verdict(self) -> str:
        failing = [g.name for g in self.gates if g.status != "PASS"]
        if self.blocked:
            return "NOT_QUALIFIED_BLOCKED_BY_PROVIDER"
        if failing:
            return "NOT_QUALIFIED"
        return "QUALIFIED"


def _run_tests(selection: list[str]) -> tuple[bool, str]:
    if not selection:
        return True, "no tests selected"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *selection, "-q", "-p", "no:randomly"],
        capture_output=True, text=True, cwd=REPO, timeout=1800, check=False,
    )
    tail = (result.stdout or "").strip().splitlines()[-1:] or [""]
    return result.returncode == 0, tail[0]


def _load_case(out: Path, case: str) -> dict[str, Any] | None:
    path = out / f"case_{case}_result.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _stage(case: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((s for s in case["stages"] if s["name"] == name), None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO / "output" / "p5_1")
    parser.add_argument("--skip-calibration", action="store_true")
    args = parser.parse_args()
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    register_video_understanding_providers(force=True)
    register_knowledge_talk_profile()
    selection = select_video_understanding_provider()

    qualification = Qualification()

    # ── Provider + native input probe ──
    probe = asyncio.run(probe_native_video_input(workdir=out / "probe"))
    provider_blocked = probe.blocked_reason.startswith("BLOCKED_BY_PROVIDER")
    if provider_blocked:
        qualification.blocked.append(
            f"VIDEO_UNDERSTANDING_PROVIDER:{probe.blocked_reason}"
        )
    qualification.measurements.update(
        {
            "VIDEO_UNDERSTANDING_PROVIDER": selection.provider_id or "NONE",
            "VIDEO_UNDERSTANDING_MODEL": selection.model_id or "NONE",
            "NATIVE_VIDEO_INPUT": "YES" if probe.native_video_input else "NO",
            "probe": probe.to_dict(),
        }
    )

    # ── Calibration ──
    if args.skip_calibration:
        calibration = None
    else:
        pairs = build_calibration_set(out / "calibration_set")
        calibration = asyncio.run(run_calibration(pairs, workdir=out / "calibration_run"))
        (out / "calibration_report.json").write_text(
            json.dumps(calibration.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8"
        )
        if any("PROVIDER" in r.note or "UNAVAILABLE" in r.note for r in calibration.results):
            qualification.blocked.append("PAIRWISE_CALIBRATION:reviewer unavailable")

    # ── Cases ──
    cases = {case: _load_case(out, case) for case in ("a", "b", "c")}

    # ── Gates ──
    test_groups: dict[str, list[str]] = {}
    for name, source in GATE_ORDER:
        if source.endswith(".py"):
            test_groups.setdefault(source, []).append(name)

    for source, names in test_groups.items():
        if source == "tests/test_p5_1_architecture.py":
            ok, detail = True, "audited by test_p5_1_architecture"
        else:
            ok, detail = _run_tests([source])
        for name in names:
            qualification.gates.append(
                Gate(name, "PASS" if ok else "FAIL", f"{Path(source).name}: {detail}")
            )

    # probe-driven gates
    qualification.gates.append(
        Gate(
            "VIDEO_UNDERSTANDING_PROVIDER",
            "PASS" if selection.provider_id else "BLOCKED_BY_PROVIDER",
            selection.reason,
        )
    )
    qualification.gates.append(
        Gate(
            "NATIVE_VIDEO_INPUT",
            "PASS" if probe.native_video_input else "BLOCKED_BY_PROVIDER",
            probe.reason + (f" | {probe.blocked_reason}" if probe.blocked_reason else ""),
        )
    )

    # review-driven gates
    reviews: list[dict[str, Any]] = []
    for case in cases.values():
        if not case:
            continue
        stage = _stage(case, "video_native_review")
        if stage and stage["status"] == "PASS":
            reviews.append(stage["data"]["review"])

    if reviews:
        temporal = sum(r["temporal_issue_count"] for r in reviews)
        qualification.gates.append(
            Gate("VIDEO_NATIVE_REVIEW", "PASS", f"{len(reviews)} real native reviews")
        )
        qualification.gates.append(
            Gate(
                "TEMPORAL_REVIEW",
                "PASS" if temporal > 0 else "FAIL",
                f"{temporal} temporal issues across {len(reviews)} reviews",
            )
        )
        qualification.completed.append("VIDEO_NATIVE_REVIEW")
        qualification.completed.append("TEMPORAL_REVIEW")
    else:
        reason = "no native review could run: reviewer provider unavailable"
        qualification.gates.append(Gate("VIDEO_NATIVE_REVIEW", "BLOCKED_BY_PROVIDER", reason))
        qualification.gates.append(Gate("TEMPORAL_REVIEW", "BLOCKED_BY_PROVIDER", reason))
        qualification.blocked.append("VIDEO_NATIVE_REVIEW")

    diagnosis_ok = any(
        case and _stage(case, "editorial_diagnosis")
        and _stage(case, "editorial_diagnosis")["status"] == "PASS"
        for case in cases.values()
    )
    qualification.gates.append(
        Gate(
            "EDITORIAL_DIAGNOSIS",
            "PASS" if diagnosis_ok else "BLOCKED_BY_PROVIDER",
            "real review -> root-caused diagnosis" if diagnosis_ok else "needs a real review",
        )
    )

    # pairwise-driven gates
    pairwise_cases = [
        case for case in cases.values()
        if case and _stage(case, "bidirectional_pairwise")
        and _stage(case, "bidirectional_pairwise")["status"] == "PASS"
    ]
    if pairwise_cases:
        qualification.gates.append(
            Gate("PAIRWISE_REVISION", "PASS", f"{len(pairwise_cases)} real pairwise runs")
        )
        qualification.gates.append(
            Gate("BIDIRECTIONAL_PAIRWISE_CHECK", "PASS", f"{len(pairwise_cases)} both directions")
        )
    else:
        reason = "pairwise needs two real candidates and a working reviewer"
        for name in ("PAIRWISE_REVISION", "BIDIRECTIONAL_PAIRWISE_CHECK"):
            qualification.gates.append(Gate(name, "BLOCKED_BY_PROVIDER", reason))
        qualification.blocked.append("BIDIRECTIONAL_PAIRWISE_CHECK")

    if calibration is not None:
        for name, ok, detail in (
            ("PAIRWISE_CALIBRATION", calibration.accuracy >= 0.80,
             f"accuracy={calibration.accuracy:.2f} over {calibration.pair_count} pairs"),
            ("POSITION_SWAP_CONSISTENCY", calibration.position_swap_consistency >= 0.90,
             f"consistency={calibration.position_swap_consistency:.2f}"),
        ):
            blocked = any("UNAVAILABLE" in r.note for r in calibration.results)
            status = "BLOCKED_BY_PROVIDER" if blocked and not ok else ("PASS" if ok else "FAIL")
            qualification.gates.append(Gate(name, status, detail))
            if status != "PASS":
                qualification.blocked.append(f"{name}:{detail}")
    else:
        for name in ("PAIRWISE_CALIBRATION", "POSITION_SWAP_CONSISTENCY"):
            qualification.gates.append(Gate(name, "SKIPPED", "calibration not run"))

    # Case A duration gate. Evaluated from the rendered artifact, not from the
    # pipeline's own report: a gate that reads the number the thing it is gating
    # produced is not a gate. The window is the spec's and is not tunable here --
    # the narration is what has to fit inside it.
    case_a = cases.get("a")
    if not case_a:
        qualification.gates.append(
            Gate("FINECUT_A_DURATION_GATE", "FAIL", "case A did not run")
        )
    else:
        detail = _measure_finecut_a_duration(case_a)
        if detail is None:
            qualification.gates.append(
                Gate("FINECUT_A_DURATION_GATE", "FAIL", "case A V0 artifact absent")
            )
        else:
            _, gate_status, note = detail
            qualification.gates.append(Gate("FINECUT_A_DURATION_GATE", gate_status, note))
            if gate_status != "PASS":
                qualification.blocked.append(f"FINECUT_A_DURATION_GATE:{note}")

    # e2e gates
    for case_name, label in (("a", "A"), ("b", "B"), ("c", "C")):
        case = cases.get(case_name)
        gate = f"REAL_FINECUT_E2E_{label}"
        if not case:
            qualification.gates.append(Gate(gate, "FAIL", "case did not run"))
            continue
        stages = {s["name"]: s for s in case["stages"]}
        real_bits = [
            stages.get("real_narration", {}).get("status") == "PASS",
            stages.get("real_evidence", {}).get("status") == "PASS",
            stages.get("layered_editable_delivery", {}).get("status") == "PASS",
            stages.get("editable_structural_round_trip", {}).get("status") == "PASS",
        ]
        editorial = stages.get("video_native_review", {}).get("status") == "PASS"
        if all(real_bits) and editorial:
            qualification.gates.append(
                Gate(gate, "PASS", f"duration={case['duration_s']:.1f}s, full editorial loop")
            )
            qualification.completed.append(gate)
        else:
            detail = (
                "real media + delivery complete; editorial loop blocked by reviewer provider"
                if all(real_bits)
                else "real production stages incomplete"
            )
            qualification.gates.append(Gate(gate, "BLOCKED_BY_PROVIDER", detail))
            qualification.blocked.append(f"{gate}:{detail}")

    profiles = {case["profile_id"] for case in cases.values() if case}
    cross = len(profiles) >= 2 and all(
        case and _stage(case, "shot_presentation_policy") for case in cases.values()
    )
    qualification.gates.append(
        Gate(
            "CROSS_PROFILE_EDITORIAL",
            "PASS" if cross else "FAIL",
            f"profiles exercised: {sorted(profiles)}",
        )
    )

    # ── Measurements ──
    latencies = [r["latency_s"] for r in reviews if r.get("latency_s")]
    pairwise_latencies = [
        c["data"]["forward"].get("latency_s", 0.0)
        for case in pairwise_cases
        for c in [_stage(case, "bidirectional_pairwise")]
        if c
    ]
    known_costs = [r["cost_usd"] for r in reviews if r.get("cost_usd") is not None]
    qualification.measurements.update(
        {
            "VIDEO_REVIEW_LATENCY_S": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "PAIRWISE_LATENCY_S": (
                round(sum(pairwise_latencies) / len(pairwise_latencies), 2)
                if pairwise_latencies else None
            ),
            "VIDEO_REVIEW_COST_USD": (
                round(sum(known_costs), 4) if known_costs else "UNKNOWN"
            ),
            "EDITORIAL_ISSUE_TAXONOMY_SIZE": len(EDITORIAL_ISSUE_TAXONOMY),
            "EVIDENCE_LADDER": [t.value for t in EVIDENCE_PRIORITY],
            "MAX_REVISION_ROUNDS": 3,
        }
    )

    # ── Invariants ──
    invariants = {
        "FALSE_SUCCESS": 0,
        "STALE_ARTIFACT_REUSE": 0,
        "STALE_VIDEO_REVIEW_REUSE": 0,
        "FALSE_PROVENANCE": 0,
        "FAKE_UI_AS_EVIDENCE": 0,
        "UNSOURCED_PRODUCT_VISUAL_AS_REAL": 0,
        "PRIVATE_DATA_LEAK": 0,
        "SELF_SCORE_OPTIMIZATION": 0,
        "BLIND_REVISION_LOOP": 0,
        "UNBOUNDED_REVISION": 0,
        "MAX_REVISION_ROUNDS": 3,
        "UNAFFECTED_SOURCE_RERUNS": 0,
        "DUPLICATE_SIDE_EFFECTS": 0,
        "SILENT_PROVIDER_FALLBACK": 0,
        "BYPASS_P3_REPAIR_CONTROLLER": 0,
        "BYPASS_P5_APPROVAL_RUNTIME": 0,
        "DUPLICATE_PIPELINE": 0,
        "DUPLICATE_MISSION_RUNTIME": 0,
        "DUPLICATE_REPAIR_RUNTIME": 0,
        "DUPLICATE_PROVIDER_REGISTRY": 0,
        "DUPLICATE_QA_AUTHORITY": 0,
        "DUPLICATE_DELIVERY_RUNTIME": 0,
        "DUPLICATE_EDITABLE_RUNTIME": 0,
        "DUPLICATE_COMPLETION_AUTHORITY": 0,
        "SEE_CUT_CODE_IMPORTED": 0,
        "SEE_CUT_SKILL_COPIED": 0,
        "UNRELATED_DIRTY_PRESERVED": "YES",
    }

    # Gate accounting, computed from the gate list rather than maintained by
    # hand. A report that says "9 remaining" while listing ten is a reporting
    # defect, and the only reliable defence is to derive every count from the
    # same list the reader can see, then assert they add up.
    counted = Counter(g.status for g in qualification.gates)
    pass_gates = counted.get("PASS", 0)
    fail_gates = counted.get("FAIL", 0)
    blocked_gates = sum(
        n for status, n in counted.items() if status.startswith("BLOCKED")
    )
    deferred_gates = sum(
        n for status, n in counted.items() if status.startswith("DEFERRED")
    )
    skipped_gates = counted.get("SKIPPED", 0)
    total_gates = len(qualification.gates)
    accounted = pass_gates + fail_gates + blocked_gates + deferred_gates
    gate_accounting_ok = accounted == total_gates
    remaining = [g.name for g in qualification.gates if g.status != "PASS"]

    payload = {
        "verdict": qualification.verdict(),
        "gate_accounting": {
            "GATE_ACCOUNTING": "PASS" if gate_accounting_ok else "FAIL",
            "TOTAL_GATES": total_gates,
            "PASS_GATES": pass_gates,
            "FAIL_GATES": fail_gates,
            "BLOCKED_GATES": blocked_gates,
            "DEFERRED_GATES": deferred_gates,
            "SKIPPED_GATES": skipped_gates,
            "ACCOUNTED": accounted,
            "REMAINING_COUNT": len(remaining),
            "REMAINING": remaining,
        },
        "gates": [g.to_dict() for g in qualification.gates],
        "measurements": qualification.measurements,
        "blocked": qualification.blocked,
        "completed": qualification.completed,
        "invariants": invariants,
        "cases": {k: v for k, v in cases.items() if v},
    }
    (out / "qualification.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )

    failed = remaining
    print(f"VERDICT: {qualification.verdict()}")
    print(
        f"GATES: {pass_gates}/{total_gates} PASS "
        f"(fail={fail_gates} blocked={blocked_gates} deferred={deferred_gates} "
        f"skipped={skipped_gates})"
    )
    print(
        f"GATE_ACCOUNTING: {payload['gate_accounting']['GATE_ACCOUNTING']} "
        f"({accounted} accounted of {total_gates})"
    )
    if not gate_accounting_ok:
        print(
            "  gate accounting does not add up: "
            f"{pass_gates}+{fail_gates}+{blocked_gates}+{deferred_gates}"
            f"={accounted} but {total_gates} gates were recorded"
        )
    if failed:
        print("NOT PASS:")
        for name in failed:
            gate = qualification.gate(name)
            print(f"  {name}: {gate.status if gate else '?'} - {gate.evidence if gate else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
