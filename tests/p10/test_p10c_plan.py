"""P10c acceptance: C1-C8 plan layer + compiler skeleton + P10-S binding."""

import ast
import json
from pathlib import Path

import pytest

from hevi.creative.direction_plan import (
    Anchor,
    Beat,
    BeatPlan,
    CameraSpec,
    Cue,
    CueAction,
    CueMap,
    Curve,
    CurveSample,
    DirectionDecision,
    FieldChange,
    Movement,
    PlanValidationError,
    SignatureShot,
    Silence,
    SoundDirection,
    TimeBinding,
    check_signature_unique,
    compile_program,
    is_directed,
    link_beatcue,
    negotiate,
)

REPO = Path(__file__).resolve().parents[2]
SPIKE = REPO / "docs" / "p10" / "p10_s"


def _anchor(target: str = "scene1.line002", offset: int = 500, coord: str = "film-global") -> Anchor:
    return Anchor("AFTER_DIALOGUE", target, "end", offset, coord)


def _binding() -> TimeBinding:
    return TimeBinding(_anchor())


# C1
def test_c1_decision_changeset_locatable():
    ok = DirectionDecision("D18", 3, "cinematography", proposition="pull back at reveal",
                           change_set=(FieldChange("S31", "camera.movement", "set", "h"),),
                           rationale="scale", status="APPROVED")
    ok.validate()
    with pytest.raises(PlanValidationError):
        DirectionDecision("D19", 3, " pacing", status="APPROVED").validate()
    with pytest.raises(PlanValidationError):
        DirectionDecision("D20", 3, "x",
                          change_set=(FieldChange("", "", "set"),)).validate()


# C2
def test_c2_beat_coverage_and_proxy():
    b1 = Beat("B1", _anchor("l1", 0), _anchor("l2", 0))
    b2 = Beat("B2", _anchor("l2", 0), _anchor("l3", 0))
    BeatPlan((b1, b2), (Curve("energy", (CurveSample("B1", 0.5),), "loudness"),)).validate()
    with pytest.raises(PlanValidationError):
        BeatPlan((b1, Beat("B3", _anchor("l9", 0), _anchor("l9", 100))), ()).validate()
    plan = BeatPlan((b1, b2), (Curve("mood", (CurveSample("B1", 0.2),), ""),))
    plan.validate()
    assert plan.h_class_curves() == ["mood"]


# C3
def test_c3_cue_conflict_and_expand():
    a1 = CueAction("A1", "camera", {"type": "pull_back"}, "must", "override", "M", "ncc", "EVENT_LOOSE")
    a2 = CueAction("A2", "camera", {"type": "push_in"}, "must", "", "M", "ncc", "EVENT_LOOSE")
    with pytest.raises(PlanValidationError) as exc:
        CueMap((Cue("cue:C21", _binding(), actions=(a1, a2)),)).validate()
    assert exc.value.code == "CUE_CONFLICT"
    cue = Cue("cue:C21", _binding(), "revelation", 1, "B7", ("D18",), "scale",
              actions=(a1, CueAction("A3", "music", {"type": "reduce"}, "may", "", "H", "", "EVENT_LOOSE")))
    entries = cue.expand_to_plan()
    assert [e["check_id"] for e in entries] == ["cue:C21:A1", "cue:C21:A3"]
    assert entries[0]["severity"] == "must"


# C4
def test_c4_camera_vocab_and_signature_unique():
    cam = CameraSpec(movement=Movement("pull_back", "extrinsic", "emotional_convergence",
                                       "scale", "moderate", "scale_change_ratio", 0.65, 0.75))
    cam.validate()
    assert cam.h_class_items() == []
    assert CameraSpec(movement=Movement("push_in", "extrinsic", intensity="strong")).h_class_items()
    with pytest.raises(PlanValidationError):
        CameraSpec(movement=Movement("zoompush", "extrinsic")).validate()
    s1 = SignatureShot("S1", camera=cam, uniqueness_reason="only reveal")
    s1.validate()
    with pytest.raises(PlanValidationError):
        SignatureShot("S2").validate()
    with pytest.raises(PlanValidationError) as exc:
        check_signature_unique([s1, SignatureShot("S3", camera=cam, uniqueness_reason="x")])
    assert exc.value.code == "SIGNATURE_DUPLICATE"


# C5
def test_c5_silence_scope_or_reject():
    good = Silence("S3", _binding(), 320, ("voice", "music"), ("ambience"),
                   "pre_reveal", "stem_p10_level", 30.0, "breath")
    SoundDirection(silences=(good,)).validate()
    with pytest.raises(PlanValidationError):
        SoundDirection(silences=(Silence("S4", _binding(), 320),)).validate()


# C6 adapters:回指 + legacy UNDIRECTED
def test_c6_adapter_link_and_legacy():
    bc = link_beatcue(cue_id="cue:C21", creative_ref="ccue:C21", time_s=10.5,
                      kind="revelation", strength=0.9)
    assert (bc.cue_id, bc.creative_cue_ref) == ("cue:C21", "ccue:C21") and is_directed(bc)
    from hevi.cinematic.shot_intelligence.models import BeatCue
    assert not is_directed(BeatCue(1.0))


# C7 compiler: fail-loud, reproducible, degrade policy
def test_c7_compile_fail_loud_and_reproducible():
    decisions = [{"id": "D18", "change_set": [{"node": "S31"}]}]
    with pytest.raises(PlanValidationError):
        compile_program(manifest={}, authority_pins=["canon@1"], decisions=decisions)
    with pytest.raises(PlanValidationError):
        compile_program(manifest={"approval": "a"}, authority_pins=[], decisions=decisions)
    with pytest.raises(PlanValidationError):
        compile_program(manifest={"approval": "a"}, authority_pins=["c@1"],
                        decisions=[{"id": "D19"}])
    manifest = {"approval": "user:gate1", "direction_revision": 3, "cue_refs": ["cue:C21"],
                "constraints": ["dur<=30s"]}
    p1 = compile_program(manifest=manifest, authority_pins=["canon@1"], decisions=decisions)
    p2 = compile_program(manifest=manifest, authority_pins=["canon@1"], decisions=decisions)
    assert p1.compile_hash == p2.compile_hash
    status, events = negotiate({"s31": "camera.movement=orbit"}, {"pA": {"static"}},
                               [{"capability_missing": "camera.movement=orbit",
                                 "replace": "push_in", "preserve": ["motivation"], "pre_approved": True}])
    assert status == "DEGRADABLE" and events[0].pre_approved
    assert negotiate({"s31": "camera.movement=orbit"}, {"pA": {"static"}}, [])[0] == "UNSATISFIABLE"
    assert negotiate({"s31": "static"}, {"pA": {"static"}}, [])[0] == "SATISFIED"


# C8: P10c objects bind the frozen P10-S run (no re-render; object-level rebinding)
def test_c8_p10s_rebind_matches_frozen_run():
    cue_json = json.loads((SPIKE / "cue.json").read_text(encoding="utf-8"))
    sig = json.loads((SPIKE / "signature_shot.json").read_text(encoding="utf-8"))
    cue = Cue(cue_json["id"], TimeBinding(Anchor(cue_json["at"]["type"], cue_json["at"]["target"],
                                                 "end", cue_json["at"]["offset_ms"], "film-global")),
              cue_json["trigger"], cue_json["priority"], cue_json["beat_ref"],
              tuple(cue_json["decision_refs"]), cue_json["rationale"],
              actions=(CueAction("A1", "camera", {"type": "pull_back"}, "must", "override",
                                 "M", "ncc_scale@spike", "EVENT_LOOSE"),))
    cue.validate()
    entries = cue.expand_to_plan()
    assert entries[0]["detector"] == "ncc_scale@spike"
    cam = CameraSpec(shot_size=sig["shot_size"], angle=sig["angle"], lens=sig["lens"],
                     movement=Movement(sig["movement"], sig["geometry_class"],
                                       sig["motivation"]["type"], sig["motivation"]["reason"],
                                       sig["intensity"], sig["expected_magnitude"]["metric"],
                                       sig["expected_magnitude"]["min"], sig["expected_magnitude"]["max"]))
    cam.validate()
    assert cam.movement.mag_min <= 0.675 <= cam.movement.mag_max  # P10-S measured scale
    assert cue.at.anchor.offset_ms == 500 and cue.at.anchor.target == "scene1.line002"


def test_authority_boundary_no_writes():
    pkg = REPO / "hevi" / "creative" / "direction_plan"
    banned = ("layer4_legacy", "production.p6", "production.p7", "providers.registry",
              "provider_policy", "studio.timeline", "narrative.revision")
    for mod in ["models.py", "adapters.py", "compiler.py", "errors.py", "__init__.py"]:
        tree = ast.parse((pkg / mod).read_text(encoding="utf-8"))
        imports = {n.module for n in ast.walk(tree)
                   if isinstance(n, ast.ImportFrom) and n.module}
        imports |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        hits = [i for i in imports if i.startswith("hevi.") and any(b in i for b in banned)]
        assert not hits, f"{mod}: {hits}"
