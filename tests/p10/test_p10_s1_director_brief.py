"""S1 acceptance: ReferencePack/DirectorBrief contracts.

S1-1 schema + fail-loud diagnostics   S1-2 epistemic constraint classes
S1-3 provenance / reference identity S1-4 hash stability + round-trip
S1-5 completeness / approval state   S1-6 authority boundary (no second authority)
"""

import ast
import hashlib
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from hevi.creative.direction_content import content_hash
from hevi.creative.direction_state import Lifecycle
from hevi.creative.director_brief import (
    AntiPattern,
    ApprovalRecord,
    BriefCompleteness,
    Constraint,
    ConstraintStatus,
    DirectorBrief,
    DirectorBriefError,
    Priority,
    Provenance,
    ReferenceEntry,
    ReferencePack,
    SourceRef,
    canonical_json,
)
from hevi.creative.director_brief.reference_pack import SEVERITY

PIN = content_hash("benchmark-set")
SHA = hashlib.sha256(b"benchmark.json").hexdigest()
MODULES = ["__init__.py", "codec.py", "director_brief.py", "errors.py", "reference_pack.py"]


def _prov(reference_id: str = "BP4") -> Provenance:
    return Provenance(reference_id, "docs/p10/p10_s/benchmark.json", "2026-10-03T00:28:38Z", SHA)


def _pack(constraints=None, references=None) -> ReferencePack:
    return ReferencePack(
        PIN,
        references if references is not None else (ReferenceEntry(
            "BP4", "Gargantua first reveal", "Interstellar", provenance=_prov()),),
        constraints if constraints is not None else (
            Constraint("C-OBS", "scale_reveal", "尺度揭示时拉远镜头", ConstraintStatus.OBSERVED,
                       dimension="visual", provenance=_prov()),
            Constraint("C-TGT", "scale_reveal", "拉远使画面自己说出大", ConstraintStatus.TARGET,
                       dimension="motion", measurable="scale_change_ratio 0.65-0.75"),
            Constraint("C-FBD", "shot_copy", "禁止照搬镜头构图", ConstraintStatus.FORBIDDEN,
                       rationale="principle_only:只取拉远原则"),
        ),
        note="S1 fixture",
    )


def _brief(pack=None, approval=None, priorities=None, anti_patterns=None, **kw) -> DirectorBrief:
    base = {"direction_id": "d-s1", "revision": 1, "source": SourceRef("user"),
            "brief_ref": content_hash("p10b-brief"), "thesis_ref": content_hash("p10b-thesis"),
            "treatment_ref": content_hash("p10b-treatment")}
    return DirectorBrief(**{**base, "reference_pack": pack or _pack(),
                            "approval": approval or ApprovalRecord(Lifecycle.DRAFT),
                            "priorities": priorities if priorities is not None else (
                                Priority("P-VIS", "visual", "wide framing for the reveal", "must",
                                         "尺度必须被看见", ("C-OBS", "C-TGT")),
                                Priority("P-MOT", "motion", "pull back at the reveal", "must",
                                         "匹配尺度冲击", ("C-TGT",))),
                            "anti_patterns": anti_patterns if anti_patterns is not None else (
                                AntiPattern("A-COPY", "复制参考片镜头", "只取原则不取画面",
                                            ("C-FBD",)),),
                            **kw})


def _code(brief: DirectorBrief, code: str, *, complete: bool = False) -> None:
    with pytest.raises(DirectorBriefError) as exc:
        brief.validate(require_complete=complete)
    assert exc.value.code == code


def _pack_code(pack: ReferencePack, code: str) -> None:
    with pytest.raises(DirectorBriefError) as exc:
        pack.validate()
    assert exc.value.code == code


# S1-1 schema + fail-loud diagnostics
def test_s1_1_valid_contracts_pass():
    _pack().validate()
    _brief().validate()


def test_s1_1_missing_identity_and_revision():
    _code(_brief(direction_id=""), "BRIEF_INCOMPLETE")
    _code(_brief(revision=0), "BRIEF_INCOMPLETE")


def test_s1_1_unpinned_content_is_rejected_not_defaulted():
    _code(_brief(thesis_ref=""), "BRIEF_CONTENT_UNPINNED")
    _code(_brief(treatment_ref="T1"), "BRIEF_CONTENT_UNPINNED")
    with pytest.raises(DirectorBriefError) as exc:
        ReferencePack("not-a-hash", references=(), constraints=()).validate()
    assert exc.value.code == "BENCHMARK_UNPINNED"


def test_s1_1_narrative_source_must_pin_canon():
    brief = _brief(source=SourceRef("narrative"))
    _code(brief, "BRIEF_CANON_UNPINNED")
    _brief(source=SourceRef("narrative", reference="canon:fact12")).validate()
    _code(_brief(source=SourceRef("imported")), "BRIEF_IMPORT_UNHASHED")
    _code(_brief(source=SourceRef("telepathy")), "BRIEF_BAD_SOURCE")


def test_s1_1_payload_drift_fails_loud():
    payload = _brief().to_dict()
    payload["priorities"][0]["urgency"] = "high"
    with pytest.raises(DirectorBriefError) as exc:
        DirectorBrief.from_dict(payload)
    assert exc.value.code == "PAYLOAD_UNKNOWN_FIELD"
    payload = _brief().to_dict()
    payload["schema"] = "hevi.director_brief.director_brief/99"
    with pytest.raises(DirectorBriefError) as exc:
        DirectorBrief.from_dict(payload)
    assert exc.value.code == "PAYLOAD_SCHEMA_UNSUPPORTED"
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})
    with pytest.raises(ValueError):
        canonical_json({"x": float("inf")})
    with pytest.raises(TypeError):
        canonical_json({"x": object()})


# S1-2 epistemic constraint classes
def test_s1_2_statuses_are_distinct_and_queryable():
    pack = _pack()
    assert [c.id for c in pack.constraints_by_status(ConstraintStatus.TARGET)] == ["C-TGT"]
    assert pack.forbidden_constraints() == (pack.constraints[2],)
    assert {c.id for c in pack.required_constraints()} == {"C-OBS", "C-TGT", "C-FBD"}
    assert [str(s) for s in ConstraintStatus] == ["observed", "inferred", "target", "forbidden"]


def test_s1_2_observed_requires_provenance():
    _pack_code(_pack(constraints=(Constraint("C-OBS", "k", "s", ConstraintStatus.OBSERVED),)),
               "CONSTRAINT_UNSOURCED")
    _pack_code(_pack(constraints=(Constraint("C-OBS", "k", "s", ConstraintStatus.OBSERVED,
                                            provenance=Provenance("BP4")),)),
               "PROVENANCE_INCOMPLETE")


def test_s1_2_inferred_requires_provenance_and_rationale():
    _pack_code(_pack(constraints=(Constraint("C-INF", "k", "s", ConstraintStatus.INFERRED,
                                              provenance=_prov()),)),
               "INFERRED_CONSTRAINT_UNGROUNDED")
    _pack(constraints=(Constraint("C-INF", "k", "s", ConstraintStatus.INFERRED,
                                  provenance=_prov(), rationale="由 BP4 外推到本片"),)).validate()


def test_s1_2_target_requires_measurable():
    _pack_code(_pack(constraints=(Constraint("C-TGT", "k", "s", ConstraintStatus.TARGET),)),
               "TARGET_CONSTRAINT_UNMEASURABLE")


def test_s1_2_forbidden_requires_reason():
    _pack_code(_pack(constraints=(Constraint("C-FBD", "k", "s", ConstraintStatus.FORBIDDEN),)),
               "FORBIDDEN_CONSTRAINT_UNREASONED")


def test_s1_2_target_and_forbidden_on_one_key_is_contradiction():
    conflict = _pack(constraints=(
        *_pack().constraints,
        Constraint("C-FBD2", "scale_reveal", "不许拉远", ConstraintStatus.FORBIDDEN,
                   rationale="评审要求固定机位")))
    _pack_code(conflict, "CONSTRAINT_CONTRADICTION")


def test_s1_2_duplicate_ids_and_empty_pack():
    _pack_code(_pack(constraints=(_pack().constraints[0], _pack().constraints[0])),
               "CONSTRAINT_DUP_ID")
    _pack_code(_pack(references=(ReferenceEntry("BP4", "t", provenance=_prov()),
                                 ReferenceEntry("BP4", "t2", provenance=_prov()))),
               "REFPACK_DUP_REFERENCE")
    _pack_code(_pack(references=()), "REFPACK_EMPTY")
    _pack_code(_pack(constraints=()), "REFPACK_NO_CONSTRAINT")


def test_s1_2_bad_enum_and_severity():
    with pytest.raises(ValueError):
        Constraint.from_dict({"id": "C", "key": "k", "statement": "s", "status": "gut_feeling"})
    _pack_code(_pack(constraints=(Constraint("C", "k", "s", ConstraintStatus.TARGET,
                                              severity="urgent", measurable="x"),)),
               "CONSTRAINT_BAD_SEVERITY")
    _pack_code(_pack(constraints=(Constraint("", "", "", ConstraintStatus.TARGET,
                                             measurable="x"),)),
               "CONSTRAINT_INCOMPLETE")


# S1-3 provenance / reference identity
def test_s1_3_constraints_are_traceable_to_a_reference():
    _pack_code(_pack(constraints=(Constraint("C-OBS", "k", "s", ConstraintStatus.OBSERVED,
                                              provenance=_prov("BP9")),)),
               "CONSTRAINT_UNTRACEABLE")


def test_s1_3_reference_identity_is_bound_to_provenance():
    _pack_code(_pack(references=(ReferenceEntry("BP4", "Gargantua first reveal",
                                                 provenance=_prov("BP7")),)),
               "REFERENCE_IDENTITY_MISMATCH")
    _pack_code(_pack(references=(ReferenceEntry("BP4", "", provenance=_prov()),)),
               "REFERENCE_INCOMPLETE")
    _pack_code(_pack(references=(ReferenceEntry("BP4", "Gargantua first reveal"),)),
               "REFERENCE_UNPROVENANCED")


def test_s1_3_provenance_survives_serialization():
    restored = ReferencePack.from_dict(json.loads(json.dumps(_pack().to_dict())))
    entry = restored.references[0]
    assert (entry.provenance.uri, entry.provenance.retrieved_at, entry.provenance.content_hash) == (
        "docs/p10/p10_s/benchmark.json", "2026-10-03T00:28:38Z", SHA)
    assert restored.constraints[0].provenance is not None


# S1-4 hash stability + round-trip
def test_s1_4_hash_is_stable_across_equal_constructions():
    a, b = _pack(), _pack()
    assert a.pack_hash() == b.pack_hash() == _pack().pack_hash()
    assert _brief().brief_hash() == _brief().brief_hash()


def test_s1_4_hash_tracks_content_and_declaration_order():
    assert _brief().brief_hash() != _brief(revision=2).brief_hash()
    reversed_pack = _pack(constraints=tuple(reversed(_pack().constraints)))
    assert _pack().pack_hash() != reversed_pack.pack_hash()


def test_s1_4_round_trip_is_lossless():
    for original in (_pack(), _brief()):
        payload = json.loads(json.dumps(original.to_dict(), ensure_ascii=False))
        restored = type(original).from_dict(payload)
        assert restored == original
        assert restored.to_dict() == original.to_dict()


def test_s1_4_round_trip_preserves_approval_and_hashes():
    brief = _brief(approval=ApprovalRecord(Lifecycle.APPROVED, "user", "2026-10-03T01:00:00Z",
                                           "方向确认", content_hash("stale")))
    restored = DirectorBrief.from_dict(json.loads(json.dumps(brief.to_dict(), ensure_ascii=False)))
    assert restored == brief
    assert restored.approval.state is Lifecycle.APPROVED
    assert restored.content_pins() == brief.content_pins()
    assert restored.reference_pack.pack_hash() == brief.reference_pack.pack_hash()


# S1-5 completeness / approval state
def test_s1_5_draft_may_be_incomplete_but_is_diagnosed():
    draft = _brief(priorities=(), anti_patterns=())
    draft.validate()
    gap = draft.completeness()
    assert gap == BriefCompleteness(("priorities.visual", "priorities.motion", "anti_patterns"))
    assert gap.complete is False
    with pytest.raises(DirectorBriefError) as exc:
        draft.validate_for_approval()
    assert exc.value.code == "BRIEF_NOT_COMPLETE"


def test_s1_5_missing_target_or_forbidden_blocks_approval():
    no_forbidden = _brief(pack=_pack(constraints=_pack().constraints[:2]), anti_patterns=())
    with pytest.raises(DirectorBriefError) as exc:
        no_forbidden.validate_for_approval()
    assert exc.value.code == "BRIEF_NOT_COMPLETE"
    assert "constraints.forbidden" in str(exc.value)
    no_target = _brief(pack=_pack(constraints=_pack().constraints[::2]),
                       priorities=(Priority("P-VIS", "visual", "wide framing", "must", "r",
                                           ("C-OBS",)),
                                   Priority("P-MOT", "motion", "pull back", "should")))
    with pytest.raises(DirectorBriefError) as exc:
        no_target.validate_for_approval()
    assert "constraints.target" in str(exc.value)


def test_s1_5_must_priority_must_be_grounded():
    _code(_brief(priorities=(Priority("P-VIS", "visual", "wide framing", "must",
                                       rationale="", constraint_refs=("C-TGT",)),)),
          "PRIORITY_UNGROUNDED")
    _code(_brief(priorities=(Priority("P-VIS", "visual", "wide framing", "must",
                                       rationale="尺度必须被看见"),)), "PRIORITY_UNGROUNDED")
    _code(_brief(priorities=(Priority("P-VIS", "camera", "wide framing"),)), "PRIORITY_BAD_DIMENSION")
    _code(_brief(priorities=(Priority("P-VIS", "visual", "wide", "must", "r", ("C-NOPE",)),)),
          "PRIORITY_CONSTRAINT_UNKNOWN")
    _code(_brief(priorities=(Priority("P-VIS", "visual", "wide", "must", "r", ("C-TGT",)),
                              Priority("P-VIS", "motion", "pull back", "should"))),
          "PRIORITY_DUP_ID")


def test_s1_5_anti_patterns_are_grounded():
    _code(_brief(anti_patterns=(AntiPattern("A", "复制镜头", "",),)), "ANTIPATTERN_INCOMPLETE")
    _code(_brief(anti_patterns=(AntiPattern("A", "复制镜头", "只取原则", ("C-NOPE",)),)),
          "ANTIPATTERN_CONSTRAINT_UNKNOWN")


def test_s1_5_approval_must_be_attested_and_pinned():
    _code(_brief(approval=ApprovalRecord(Lifecycle.APPROVED)), "APPROVAL_UNATTESTED")
    _code(_brief(approval=ApprovalRecord(Lifecycle.APPROVED, "user", "2026-10-03T01:00:00Z")),
          "APPROVAL_UNPINNED")
    _code(_brief(approval=ApprovalRecord(Lifecycle.COMPILED, "user", "2026-10-03T01:00:00Z")),
          "APPROVAL_OUT_OF_BAND")


def test_s1_5_approved_brief_cannot_be_edited_in_place():
    pending = _brief(approval=ApprovalRecord(Lifecycle.APPROVED, "user", "2026-10-03T01:00:00Z",
                                             "方向确认", "0" * 64))
    with pytest.raises(DirectorBriefError) as exc:
        pending.validate_for_approval()
    assert exc.value.code == "APPROVAL_VOID"
    approved = replace(pending, approval=replace(pending.approval, pinned_hash=pending.brief_hash()))
    approved.validate_for_approval()
    edited = replace(approved, reference_pack=replace(approved.reference_pack, note="偷偷改一句"))
    with pytest.raises(DirectorBriefError) as exc:
        edited.validate_for_approval()
    assert exc.value.code == "APPROVAL_VOID"


def test_s1_5_pins_expose_the_existing_p10b_boundary():
    brief = _brief()
    assert {"brief", "thesis", "benchmarks", "treatment"} <= set(brief.content_pins())
    assert brief.content_pins()["brief"] == brief.brief_ref
    assert brief.content_pins()["thesis"] == brief.thesis_ref
    assert brief.content_pins()["benchmarks"] == brief.reference_pack.benchmark_ref
    assert brief.content_pins()["treatment"] == brief.treatment_ref
    assert brief.content_pins()["director_brief"] == brief.brief_hash()
    assert brief.constraints == brief.reference_pack.constraints


# S1-6 authority boundary
def test_s1_6_package_defines_no_authority_or_orchestration():
    pkg = Path(__file__).resolve().parents[2] / "hevi" / "creative" / "director_brief"
    banned_imports = ("narrative", "canon", "style", "asset", "provider", "timeline", "omodul",
                      "oprim", "oservi", "oskill", "obase", "director", "api", "prompt", "llm",
                      "direction_plan", "direction_state.repository", "direction_state.machine")
    banned_classes = ("Agent", "Orchestrator", "Workflow", "Service", "Runner", "Engine",
                      "Planner", "Compiler", "Registry")
    seen_classes: list[str] = []
    for name in MODULES:
        tree = ast.parse((pkg / name).read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Import):
                imports.update(a.name for a in node.names)
            elif isinstance(node, ast.ClassDef):
                seen_classes.append(node.name)
            assert not isinstance(node, (ast.AsyncFunctionDef, ast.AsyncFor, ast.AsyncWith)), \
                f"{name}: S1 is synchronous data only"
        hits = [i for i in imports
                if i.startswith("hevi.") and not i.startswith("hevi.creative.director_brief")
                and any(b in i for b in banned_imports)]
        assert not hits, f"{name}: {hits}"
        if name == "director_brief.py":
            assert "hevi.creative.direction_state.state" in imports, "lifecycle comes from P10a"
    assert [c for c in seen_classes if any(b in c for b in banned_classes)] == []
    assert "Lifecycle" not in seen_classes, "lifecycle authority belongs to P10a"
    assert "CreativeProgram" not in seen_classes, "program authority belongs to P10c"


def test_s1_6_vocabulary_is_locked_to_existing_authorities():
    from hevi.creative.direction_plan.models import SEVERITY as P10C_SEVERITY

    assert SEVERITY == P10C_SEVERITY
    assert re.fullmatch(r"[0-9a-f]{64}", PIN)
    ApprovalRecord(Lifecycle.REVIEW_REQUIRED).validate()