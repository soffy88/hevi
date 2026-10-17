"""P10-E acceptance: canonical ShotSpec contract layer (E1-E8).

E1 contract completeness + P10c vocabulary reuse · E2 validator report/fail-loud ·
E3 film-global anchor discipline (R-P10-01) · E4 hash determinism + domain
separation · E5 revision immutability · E6 zero mutation on rejection ·
E7 idempotency · E8 authority boundary + tamper detection.
"""

import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest

from hevi.creative.direction_plan.models import (
    CHECK_CLASSES,
    SEVERITY,
    Anchor,
    CameraSpec,
    Movement,
    PlanValidationError,
    TimeBinding,
    plan_hash,
)
from hevi.creative.direction_shot import (
    CONTENT_PIN_KEYS,
    ChainBrokenError,
    ShotRefIndex,
    ShotSpec,
    ShotSpecError,
    ShotSpecImmutableError,
    ShotSpecNotFoundError,
    ShotSpecRevisionStore,
    ShotTiming,
    ShotVerification,
    canonical_body,
    chain_hash,
    is_hash,
    shot_spec_hash,
    validate_shot_specs,
)

PKG = Path(__file__).resolve().parents[2] / "hevi" / "creative" / "direction_shot"

PINS = {"brief": "a" * 64, "thesis": "b" * 64,
        "benchmarks": "c" * 64, "treatment": "d" * 64}
LINE = "scene1.line002"


def _binding(offset_ms: int, coordinate: str = "film-global", target: str = LINE) -> TimeBinding:
    return TimeBinding(Anchor("AFTER_DIALOGUE", target, "end", offset_ms, coordinate))


def _spec(shot_id: str = "S31", revision: int = 1, start: int = 0, end: int = 2000,
          coordinate: str = "film-global", target: str = LINE, **over) -> ShotSpec:
    base = {
        "shot_id": shot_id,
        "revision": revision,
        "timing": ShotTiming(_binding(start, coordinate, target), _binding(end, coordinate, target)),
        "camera": CameraSpec(shot_size="medium",
                             movement=Movement(type="push_in", magnitude_metric="deg_per_s")),
        "beat_ref": "b_reveal",
        "cue_refs": ("c_push",),
        "decision_refs": ("D18",),
        "verification": (ShotVerification("S31:silence", "must", "D", "silence_probe"),),
        "content_pins": dict(PINS),
        "authority_pins": ("canon@r7",),
    }
    return ShotSpec(**{**base, **over})


def _index() -> ShotRefIndex:
    return ShotRefIndex.of(beats=("b_reveal",), cues=("c_push",),
                           decisions=("D18",), authority=("canon@r7", "style@r2"))


# E1 ── contract completeness, vocabulary reuse
def test_e1_spec_requires_p10b_pins_and_bound_detectors():
    _spec().validate()
    for missing in CONTENT_PIN_KEYS:
        broken = _spec(content_pins={**PINS, missing: ""})
        with pytest.raises(ShotSpecError) as exc:
            broken.validate()
        assert exc.value.code == "SHOT_PINS_INCOMPLETE"
    with pytest.raises(ShotSpecError) as exc:
        _spec(verification=(ShotVerification("S31:silence", "must", "D"),)).validate()
    assert exc.value.code == "SHOT_DETECTOR_UNBOUND"
    with pytest.raises(ShotSpecError) as exc:
        _spec(verification=(ShotVerification("S31:taste", "must", "X", "d"),)).validate()
    assert exc.value.code == "SHOT_BAD_CLASS"
    with pytest.raises(ShotSpecError) as exc:
        _spec(verification=(ShotVerification("S31:x", "sometimes", "D", "d"),)).validate()
    assert exc.value.code == "SHOT_BAD_SEVERITY"


def test_e1_non_draft_requires_verification_and_camera_uses_p10c_vocab():
    with pytest.raises(ShotSpecError) as exc:
        _spec(status="APPROVED", verification=()).validate()
    assert exc.value.code == "SHOT_NO_VERIFICATION"
    _spec().camera.validate()
    # P10c's own error type and code propagate: not re-wrapped, not re-worded
    with pytest.raises(PlanValidationError) as exc:
        _spec(camera=CameraSpec(movement=Movement(type="zoom_push"))).validate()
    assert exc.value.code == "CAMERA_BAD_MOVEMENT"


def test_e1_no_local_duplicate_of_p10c_vocabulary():
    """Vocabularies must be imported from P10c, not re-declared (reuse-first)."""
    banned_literals = {repr(CHECK_CLASSES), repr(SEVERITY)}
    for mod in sorted(PKG.glob("*.py")):
        tree = ast.parse(mod.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Tuple | ast.List) or not node.elts:
                continue
            if not all(isinstance(e, ast.Constant) and isinstance(e.value, str)
                       for e in node.elts):
                continue
            rendered = repr(ast.literal_eval(node))
            assert rendered not in banned_literals, f"{mod.name}: re-declares {rendered}"


# E2 ── validator: complete report, then fail-loud
def test_e2_reports_every_finding_then_fails_loud():
    clean = validate_shot_specs([_spec()], _index())
    assert clean.ok and clean.codes == ()

    second = replace(_spec("S32", start=3000, end=5000), beat_ref="b_missing",
                     cue_refs=("c_missing",), authority_pins=("ghost@r1",))
    report = validate_shot_specs([_spec(), second], _index())
    assert set(report.codes) == {"SHOT_REF_UNRESOLVED", "SHOT_AUTHORITY_UNPINNED"}
    with pytest.raises(ShotSpecError):
        report.raise_for_blocking()


def test_e2_duplicates_drift_and_overlap():
    assert "SHOT_DUP_ID" in validate_shot_specs([_spec(), _spec()], _index()).codes
    drifted = replace(_spec("S32", start=4000, end=6000), content_pins={**PINS, "thesis": "e" * 64})
    assert "SHOT_PINS_DIVERGED" in validate_shot_specs([_spec(), drifted], _index()).codes
    overlap = replace(_spec("S32", start=1500, end=2500))
    assert "SHOT_TIME_OVERLAP" in validate_shot_specs([_spec(), overlap], _index()).codes
    # adjacent (touching, not overlapping) shots are legal
    adjacent = replace(_spec("S32", start=2000, end=4000))
    assert validate_shot_specs([_spec(), adjacent], _index()).ok


def test_e2_unattested_class_h_must_blocks_approval():
    approved = replace(_spec(status="APPROVED"), verification=(ShotVerification("S31:taste", "must", "H"),))
    assert "SHOT_H_UNATTESTED" in validate_shot_specs([approved], _index()).codes
    # class H needs no detector while it is only advisory
    advisory = replace(_spec(), verification=(ShotVerification("S31:taste", "should", "H"),))
    assert validate_shot_specs([advisory], _index()).ok
    assert validate_shot_specs([], _index()).codes == ("SHOT_EMPTY",)


def test_e2_camera_signature_repeat_is_advisory_not_blocking():
    twin = replace(_spec("S32", start=3000, end=5000))
    report = validate_shot_specs([_spec(), twin], _index())
    assert report.ok
    assert "SHOT_CAMERA_SIGNATURE_DUPLICATE" in {f.code for f in report.findings}


# E3 ── R-P10-01: only film-global timing is accepted
@pytest.mark.parametrize("coordinate", ["line-local", ""])
def test_e3_line_local_timing_rejected(coordinate):
    with pytest.raises(ShotSpecError) as exc:
        _spec(coordinate=coordinate).validate()
    assert exc.value.code == "SHOT_COORDINATE_NOT_FILM_GLOBAL"


def test_e3_inverted_or_cross_target_timing_rejected():
    with pytest.raises(ShotSpecError) as exc:
        _spec(start=2000, end=1000).validate()
    assert exc.value.code == "SHOT_TIMING_INVERTED"
    mixed = ShotSpec("S31", 1, ShotTiming(_binding(0), _binding(100, target="scene1.line003")),
                     content_pins=dict(PINS))
    with pytest.raises(ShotSpecError) as exc:
        mixed.validate()
    assert exc.value.code == "SHOT_TIMING_TARGET_MISMATCH"


# E4 ── hash layer
def test_e4_hash_is_reproducible_and_self_reference_excluded():
    sealed = _spec().sealed()
    sealed.validate()
    assert sealed.compute_hash() == _spec().compute_hash()
    assert sealed.spec_hash == sealed.compute_hash()
    assert "spec_hash" not in canonical_body(_spec())
    assert _spec().compute_hash() == _spec().compute_hash()
    assert is_hash(sealed.spec_hash) and not is_hash("nope")


def test_e4_domain_separated_from_bare_plan_hash():
    spec = _spec()
    body = canonical_body(spec)
    assert shot_spec_hash(spec) not in {plan_hash(body), plan_hash([body])}
    assert shot_spec_hash(spec) != chain_hash("", [shot_spec_hash(spec)])
    with pytest.raises(ShotSpecError) as exc:
        replace(spec, spec_hash="0" * 64).validate()
    assert exc.value.code == "SHOT_HASH_MISMATCH"


def test_e4_mutation_changes_the_digest():
    base = _spec()
    for mutated in (replace(base, shot_id="S32"),
                    replace(base, content_pins={**PINS, "thesis": "e" * 64}),
                    replace(base, timing=replace(base.timing, end=_binding(2500)))):
        assert mutated.compute_hash() != base.compute_hash()


# E5/E6/E7 ── revision store
def _seeded(tmp_path: Path) -> ShotSpecRevisionStore:
    store = ShotSpecRevisionStore(tmp_path / "shots")
    store.create_revision("dir-1", (_spec(),), actor="director", command_id="c-create",
                          index=_index())
    return store


def test_e5_payload_is_written_once_and_never_rewritten(tmp_path):
    store = _seeded(tmp_path)
    frozen = (tmp_path / "shots" / "dir-1" / "shot_r1" / "specs.json").read_bytes()
    approved = store.approve_revision("dir-1", 1, index=_index(), actor="director",
                                      command_id="c-approve")
    assert approved.status == "APPROVED"
    assert (tmp_path / "shots" / "dir-1" / "shot_r1" / "specs.json").read_bytes() == frozen

    next_rev = store.revise(
        "dir-1", (replace(_spec(revision=2), camera=CameraSpec(shot_size="wide")),),
        actor="director", command_id="c-revise", index=_index())
    assert next_rev.revision == 2 and next_rev.status == "DRAFT"
    assert (tmp_path / "shots" / "dir-1" / "shot_r1" / "specs.json").read_bytes() == frozen
    assert store.revision_statuses("dir-1") == {1: "SUPERSEDED", 2: "DRAFT"}


def test_e5_locked_revision_cannot_be_reopened(tmp_path):
    store = _seeded(tmp_path)
    store.approve_revision("dir-1", 1, index=_index(), actor="director", command_id="c-approve")
    with pytest.raises(ShotSpecImmutableError):
        store.approve_revision("dir-1", 1, index=_index(), actor="director", command_id="c-again")
    # the head is APPROVED, so revising is legal — from APPROVED only
    store.revise("dir-1", (_spec(revision=2),), actor="director", command_id="c-revise",
                 index=_index())
    with pytest.raises(ShotSpecError) as exc:  # new head is DRAFT again
        store.revise("dir-1", (_spec(revision=3),), actor="director", command_id="c-second")
    assert exc.value.code == "SHOT_REVISION_NOT_APPROVED"
    assert store.revision_statuses("dir-1") == {1: "SUPERSEDED", 2: "DRAFT"}


def test_e6_rejection_leaves_zero_mutation(tmp_path):
    store = _seeded(tmp_path)
    before = {p: p.read_bytes() for p in (tmp_path / "shots").rglob("*") if p.is_file()}
    with pytest.raises(ShotSpecError):  # dirty index -> approve must not write
        store.approve_revision("dir-1", 1, index=ShotRefIndex.of(), actor="d", command_id="c1")
    with pytest.raises(ShotSpecError) as exc:  # unapproved head -> revise must not write
        store.revise("dir-1", (_spec(revision=2),), actor="d", command_id="c2")
    assert exc.value.code == "SHOT_REVISION_NOT_APPROVED"
    with pytest.raises(ShotSpecError) as exc:  # existing direction is never overwritten
        store.create_revision("dir-1", (_spec(),), actor="d", command_id="c3")
    assert exc.value.code == "SHOT_DIRECTION_EXISTS"
    with pytest.raises(ShotSpecNotFoundError):
        store.revise("dir-absent", (_spec(revision=2),), actor="d", command_id="c4")
    assert {p: p.read_bytes() for p in (tmp_path / "shots").rglob("*") if p.is_file()} == before


def test_e6_spec_revision_must_match_the_revision_it_is_stored_in(tmp_path):
    store = _seeded(tmp_path)
    store.approve_revision("dir-1", 1, index=_index(), actor="d", command_id="c-approve")
    with pytest.raises(ShotSpecError) as exc:  # r1 payload re-stamped as r2
        store.revise("dir-1", (_spec(revision=1),), actor="d", command_id="c-bad",
                     index=_index())
    assert exc.value.code == "SHOT_REVISION_MISMATCH"
    assert store.revision_statuses("dir-1") == {1: "APPROVED"}
    assert not (tmp_path / "shots" / "dir-1" / "shot_r2").exists()


def test_e7_replay_is_idempotent_and_reuse_is_refused(tmp_path):
    store = _seeded(tmp_path)
    store.approve_revision("dir-1", 1, index=_index(), actor="d", command_id="c-approve")
    first = store.revise("dir-1", (_spec(revision=2),), actor="d", command_id="c-revise",
                         index=_index())
    after_first = {p: p.read_bytes() for p in (tmp_path / "shots").rglob("*") if p.is_file()}
    replay = store.revise("dir-1", (_spec(revision=2),), actor="d", command_id="c-revise",
                          index=_index())
    assert replay.revision == first.revision
    assert {p: p.read_bytes() for p in (tmp_path / "shots").rglob("*") if p.is_file()} == after_first

    with pytest.raises(ShotSpecError) as exc:  # same id, different payload
        store.revise("dir-1", (replace(_spec(revision=2), camera=CameraSpec(shot_size="wide")),),
                     actor="d", command_id="c-revise", index=_index())
    assert exc.value.code == "SHOT_DUPLICATE_COMMAND"


# E8 ── chain verification + authority boundary
def test_e8_chain_verification_and_tamper_detection(tmp_path):
    store = _seeded(tmp_path)
    store.approve_revision("dir-1", 1, index=_index(), actor="d", command_id="c-approve")
    store.revise("dir-1", (replace(_spec(revision=2), camera=CameraSpec(shot_size="wide")),),
                 actor="d", command_id="c-revise", index=_index())
    assert len(store.verify_chain("dir-1")) == 2
    assert store.get_revision("dir-1", 1).specs[0].compute_hash() == _spec().compute_hash()

    specs_path = tmp_path / "shots" / "dir-1" / "shot_r2" / "specs.json"
    tampered = json.loads(specs_path.read_text())
    tampered["specs"][0]["camera"]["shot_size"] = "extreme_close_up"
    specs_path.write_text(json.dumps(tampered, ensure_ascii=False, sort_keys=True, indent=2))
    with pytest.raises(ChainBrokenError):
        store.verify_chain("dir-1")

    doc = json.loads(specs_path.read_text())
    doc["chain_hash"] = "0" * 64
    doc["specs"][0]["camera"]["shot_size"] = "wide"
    specs_path.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2))
    with pytest.raises(ChainBrokenError):
        store.verify_chain("dir-1")


def test_e8_no_authority_or_shot_planner_imports():
    banned = ("layer4_legacy", "production.p6", "production.p7", "providers.registry",
              "provider_policy", "studio.timeline", "narrative.revision",
              "shot_intelligence.planner", "shot_intelligence.selection")
    for mod in sorted(PKG.glob("*.py")):
        tree = ast.parse(mod.read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Import):
                imports.update(a.name for a in node.names)
        hits = [i for i in imports if i.startswith("hevi.") and any(b in i for b in banned)]
        assert not hits, f"{mod.name}: {hits}"
