"""P10d acceptance: D1-D7 close-the-loop + authority boundary."""

import ast
import json
from pathlib import Path

import pytest

from hevi.creative.direction_verify import (
    Calibration,
    CheckResult,
    CreativeMemory,
    DepEdge,
    DependencyGraph,
    DepNode,
    Detector,
    DetectorRegistry,
    DirectionEvidence,
    DirectionVerdict,
    MemoryEntry,
    ObservationSet,
    VerifyError,
    aggregate,
    apply_authority_change,
    apply_early_cutoff,
    compute_revision_impact,
)

REPO = Path(__file__).resolve().parents[2]
FROZEN_RUN = REPO / "artifacts" / "p10_s" / "20261003T002838Z"


def _check(cid: str, result: str, severity: str = "must", cls: str = "D") -> CheckResult:
    return CheckResult(cid, result, cls, severity)


# D1 aggregation rules
def test_d1_aggregation():
    assert aggregate([_check("a", "PASS"), _check("b", "PASS")]) == "PASS"
    assert aggregate([_check("a", "PASS"), _check("b", "FAIL", "may")]) == "PASS_WITH_WARNINGS"
    assert aggregate([_check("a", "FAIL")]) == "REVISE"
    assert aggregate([_check("a", "FAIL")], hard_requirement_failed=True) == "FAIL"
    assert aggregate([_check("a", "FAIL")], artifact_invalid=True) == "FAIL"
    assert aggregate([_check("a", "INCONCLUSIVE")]) == "INCONCLUSIVE"
    assert aggregate([_check("a", "NOT_EVALUABLE")]) == "INCONCLUSIVE"
    assert aggregate([_check("a", "FAIL", "must", "H")]) == "REVISE"  # H without attest path
    v = DirectionVerdict("a" * 64, "plan1", aggregate([_check("a", "PASS")]),
                         (_check("a", "PASS"),))
    v.validate()
    with pytest.raises(VerifyError):
        DirectionVerdict("nohash", "plan1", "PASS", ()).validate()


# D2 calibration gate: uncalibrated cannot issue PASS/FAIL
def test_d2_calibration_gate():
    reg = DetectorRegistry()
    reg.register(Detector("ncc_scale", "spike", "M", ("CHK-ZOOM",)))
    assert reg.issue("ncc_scale", "PASS", 0.99) == "INCONCLUSIVE"
    with pytest.raises(VerifyError):
        reg.register(Detector("bad", "1", "M", (), status="ENABLED_FOR_PASS"))
    with pytest.raises(VerifyError):
        reg.calibrate("ncc_scale", Calibration(("parallax_zoom_vs_dolly",), 0.9, 0.9, 0.5, "t"))
    reg.calibrate("ncc_scale", Calibration(
        ("parallax_zoom_vs_dolly", "shortest_silence", "known_av_offset", "no_change_control"),
        0.95, 0.93, 0.5, "2026-10-03"))
    assert reg.issue("ncc_scale", "PASS", 0.99) == "PASS"
    assert reg.issue("ncc_scale", "PASS", 0.3) == "INCONCLUSIVE"  # below theta
    DirectionEvidence("D18", "CHK-ZOOM", "0.65-0.75", "0.675", "ncc_scale", "spike",
                      "cal:1", 0.99, "a" * 64, "t").validate()


# D3 observationset cache + hash binding
def test_d3_observation_cache_binding():
    obs = ObservationSet("a" * 64, "vi", "t")
    obs.validate()
    with pytest.raises(VerifyError):
        ObservationSet("x").validate()
    assert obs.artifact_hash == "a" * 64  # same hash -> reuse; changed file -> new hash


# D4 impact: field-level seeds, preserved proof, early cutoff
def _graph() -> DependencyGraph:
    g = DependencyGraph()
    g.add_node(DepNode("thesis", "Thesis", frozenset(), frozenset({"thesis.emotional_arc"})))
    g.add_node(DepNode("beat", "BeatPlan", frozenset({"thesis.emotional_arc"}), frozenset({"beat.curve"})))
    g.add_node(DepNode("shot", "ShotPlan", frozenset({"beat.curve"}), frozenset({"shot.render"})))
    g.add_node(DepNode("tts", "TTS", frozenset(), frozenset({"tts.audio"})))
    g.add_edge(DepEdge("thesis", "beat", frozenset({"thesis.emotional_arc"})))
    g.add_edge(DepEdge("beat", "shot", frozenset({"beat.curve"})))
    return g


def test_d4_impact_and_cutoff():
    g = _graph()
    base = {"thesis": "h1", "beat": "h1", "shot": "h1", "tts": "h1"}
    new = dict(base, thesis="h2")
    report = compute_revision_impact(base, new, g)
    assert set(report.upper_bound) == {"thesis", "beat", "shot"} and "tts" in report.preserved
    assert report.earliest_stage == "Thesis"
    assert report.rerun_plan and all(s.cost_class for s in report.rerun_plan)
    # only motivation text changed -> beat output hash unchanged -> cutoff
    actual = apply_early_cutoff(report.upper_bound, {"beat": ("h1", "h1")})
    assert "beat" not in actual and set(actual) <= set(report.upper_bound)
    # conservative edge warns
    g.add_edge(DepEdge("thesis", "tts", frozenset()))
    report2 = compute_revision_impact(base, new, g)
    assert any("IMPACT_CONSERVATIVE_EDGE" in w for w in report2.conservative_warnings)


# D5 inbound invalidation
def test_d5_inbound_stale_blocks():
    g = _graph()
    stale = apply_authority_change(g, "style@v2", {"beat": "style@v2", "shot": "asset@1"})
    assert stale == ("beat",)


# D6 memory promotion/retirement/suggestion
def test_d6_memory_evidence_scoped():
    mem = CreativeMemory()
    with pytest.raises(VerifyError):
        mem.record(MemoryEntry("m1", "approved_pattern", "c", "p", evidence=()))
    mem.record(MemoryEntry("m1", "approved_pattern", "reveal", "silence-before-scale",
                           ("scale",), ("verdict:1",)))
    assert mem.suggest()[0].status == "candidate"
    mem.add_evidence("m1", "verdict:2")
    active = mem.suggest(("scale",))
    assert active and active[0].status == "active"
    assert mem.suggest(("other",)) == []
    mem.refuse("m1")
    mem.refuse("m1")
    assert mem.suggest() == []  # twice refused -> demoted, never auto-approves
    mem.add_evidence("m1", "verdict:3")
    mem.supersede("m1")
    assert mem._entries["m1"].status == "retired"


# D7 frozen P10-S run through the new engine
def test_d7_frozen_run_replayed():
    verdict_json = json.loads((FROZEN_RUN / "direction_verdict.json").read_text(encoding="utf-8"))
    checks = [CheckResult(c["id"] if "id" in c else c.get("check_id", ""), c["result"],
                          "M" if "ZOOM" in str(c.get("check_id", c.get("id"))) else "D",
                          "may" if str(c.get("check_id", c.get("id"))) == "CHK-MUS" else "must")
              for c in verdict_json["checks"]]
    assert aggregate(checks) == verdict_json["status"] == "PASS"
    obs = json.loads((FROZEN_RUN / "observation_set.json").read_text(encoding="utf-8"))
    ObservationSet(obs["artifact_hash"]).validate()
    assert obs["artifact_hash"] == verdict_json["artifact_hash"]


def test_authority_boundary_no_writes():
    pkg = REPO / "hevi" / "creative" / "direction_verify"
    banned = ("layer4_legacy", "production.p6", "production.p7", "providers.registry",
              "provider_policy", "studio.timeline", "narrative.revision")
    for mod in ["models.py", "verdict.py", "detectors.py", "impact.py", "memory.py",
                "errors.py", "__init__.py"]:
        tree = ast.parse((pkg / mod).read_text(encoding="utf-8"))
        imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        imports |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        hits = [i for i in imports if i.startswith("hevi.") and any(b in i for b in banned)]
        assert not hits, f"{mod}: {hits}"
