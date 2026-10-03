"""S1 minimal real vertical contract test.

Path exercised end to end, with no mocks and no invented creative data:

  real P10-S artifacts (docs/p10/p10_s/*.json — the PASS run of the P10-S spike)
    -> real P10b content objects (BenchmarkSet/CreativeThesis/Treatment/CreativeBrief)
    -> real content hashes
    -> S1 ReferencePack (constraints read off the real benchmark + signature shot)
    -> S1 DirectorBrief pinned to those hashes, approved
    -> real P10a revision dir on disk via the existing P10b pin record
    -> drift is detected (APPROVAL_VOID), in-place edits refused.
"""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from hevi.creative.direction_content import (
    BenchmarkReference,
    BenchmarkSet,
    ContentValidationError,
    CreativeBrief,
    CreativeThesis,
    ExtractedPrinciple,
    Treatment,
    TreatmentAlternative,
    content_hash,
    record_content_pins,
    verify_content_pins,
)
from hevi.creative.direction_state import DirectionRepository, Lifecycle
from hevi.creative.director_brief import (
    AntiPattern,
    ApprovalRecord,
    Constraint,
    ConstraintStatus,
    DirectorBrief,
    DirectorBriefError,
    Priority,
    Provenance,
    ReferenceEntry,
    ReferencePack,
    SourceRef,
)

SPIKE = Path(__file__).resolve().parents[2] / "docs" / "p10" / "p10_s"
PROJECT, DIRECTION = "p10-s", "d-blackhole"
# The P10-S run stamp that produced these artifacts (STATUS.md P10 pointer).
RETRIEVED_AT = "2026-10-03T00:28:38Z"


def _artifact(name: str) -> dict:
    return json.loads((SPIKE / name).read_text(encoding="utf-8"))


def _provenance(reference_id: str) -> Provenance:
    return Provenance(reference_id, "docs/p10/p10_s/benchmark.json", RETRIEVED_AT,
                      hashlib.sha256((SPIKE / "benchmark.json").read_bytes()).hexdigest(),
                      extractor="p10s-reviewer")


def _p10b_objects() -> tuple[BenchmarkSet, CreativeThesis, Treatment, CreativeBrief]:
    benchmark, thesis = _artifact("benchmark.json"), _artifact("thesis.json")
    treatment = _artifact("treatment.json")
    principle = benchmark["principle"]
    reference = benchmark["reference"]
    principle_id = principle["id"]
    benchmarks = BenchmarkSet((BenchmarkReference(
        id=principle_id, title=reference["title"], creator=reference["creator"],
        uri="docs/p10/p10_s/benchmark.json", retrieved_at=RETRIEVED_AT,
        reference_hash=content_hash(benchmark), extraction_method="p10s-reviewer",
        extraction_actor="p10s-reviewer", transfer_mode=reference["transfer_mode"],
        principles=(ExtractedPrinciple(principle_id, principle["statement"],
                                       principle["dimension"], "principle"),),
        avoid=tuple(benchmark["avoid"]), relevance=benchmark["relevance"]),))
    creative_thesis = CreativeThesis(logline=thesis["logline"],
                                     central_question=thesis["central_question"],
                                     emotional_arc=thesis["emotional_arc"],
                                     audience_effect=thesis["audience_effect"])
    creative_treatment = Treatment(
        thesis_ref=content_hash(creative_thesis), structure=treatment["structure"],
        opening=treatment["opening"], ending=treatment["ending"],
        alternatives=(TreatmentAlternative(treatment["selected"], treatment["structure"],
                                           treatment["alternatives_note"]),),
        short_form_reason=treatment["alternatives_note"],
        recommended_by_actor=treatment["recommended_by"]["actor"],
        recommended_by_rationale=treatment["recommended_by"]["rationale"],
        selected=treatment["selected"],
        selected_by_actor=treatment["recommended_by"]["actor"],
        selection_rationale=treatment["selection_rationale"])
    creative_brief = CreativeBrief(subject=creative_thesis.central_question,
                                   objective=creative_thesis.audience_effect,
                                   audience="general", emotional_target=creative_thesis.emotional_arc,
                                   forbidden_elements=tuple(benchmark["avoid"]),
                                   source_type="user", source_reference="docs/p10/p10_s")
    for obj in (benchmarks, creative_thesis, creative_treatment, creative_brief):
        obj.validate()
    return benchmarks, creative_thesis, creative_treatment, creative_brief


def _pack(benchmarks: BenchmarkSet) -> ReferencePack:
    reference = benchmarks.references[0]
    principle = reference.principles[0]
    signature = _artifact("signature_shot.json")
    magnitude = signature["expected_magnitude"]
    return ReferencePack(
        content_hash(benchmarks),
        (ReferenceEntry(reference.id, reference.title, reference.creator,
                        provenance=_provenance(reference.id)),),
        (Constraint("C-OBS-SCALE", "scale_reveal", principle.statement,
                    ConstraintStatus.OBSERVED, dimension=principle.dimension,
                    rationale="", provenance=_provenance(reference.id)),
         Constraint("C-INF-RELEVANCE", "principle_transfer", reference.relevance,
                    ConstraintStatus.INFERRED, dimension=principle.dimension,
                    rationale=f"transfer_mode={reference.transfer_mode}",
                    provenance=_provenance(reference.id)),
         Constraint("C-TGT-MAGNITUDE", "scale_change",
                    f"{signature['movement']} 时画面尺度变化落在期望区间",
                    ConstraintStatus.TARGET, dimension="motion", severity="must",
                    measurable=f"{magnitude['metric']} {magnitude['min']}-{magnitude['max']}"),
         Constraint("C-FBD-COPY", "shot_copying",
                    "禁止照搬参考片画面/角色/标识", ConstraintStatus.FORBIDDEN,
                    dimension="visual", rationale=f"benchmark avoid={list(reference.avoid)}")),
        note="S1 vertical over the P10-S artifacts")


def _brief(pack: ReferencePack, brief: CreativeBrief, thesis: CreativeThesis,
           treatment: Treatment, approved_hash: str = "") -> DirectorBrief:
    signature = _artifact("signature_shot.json")
    approval = ApprovalRecord(Lifecycle.APPROVED, "user", "2026-10-03T01:30:00Z",
                              "P10-S 方向确认", approved_hash) if approved_hash else \
        ApprovalRecord(Lifecycle.DRAFT)
    return DirectorBrief(
        DIRECTION, 1, SourceRef("user", "docs/p10/p10_s"), pack, approval,
        brief_ref=content_hash(brief), thesis_ref=content_hash(thesis),
        treatment_ref=content_hash(treatment),
        priorities=(Priority("P-VIS-SCALE", "visual",
                             f"{signature['shot_size']} / {signature['framing']} 承载尺度揭示",
                             "must", signature["narrative_role"],
                             ("C-OBS-SCALE", "C-TGT-MAGNITUDE"), ()),
                    Priority("P-MOT-PULLBACK", "motion",
                             f"{signature['movement']} 匹配尺度冲击", "must",
                             signature["motivation"]["reason"], ("C-TGT-MAGNITUDE",),
                             ("C-FBD-COPY",))),
        anti_patterns=(AntiPattern("A-COPY-FRAME", "逐帧复刻参考片的揭示镜头",
                                   f"{signature['composition']} 构图照搬会读成二创而非原创",
                                   ("C-FBD-COPY",)),))


def _approved_brief() -> tuple[DirectorBrief, dict[str, str], BenchmarkSet, CreativeThesis,
                               Treatment, CreativeBrief]:
    benchmarks, thesis, treatment, brief = _p10b_objects()
    pack = _pack(benchmarks)
    pack.validate()
    draft = _brief(pack, brief, thesis, treatment)
    draft.validate()
    approved = replace(draft, approval=ApprovalRecord(
        Lifecycle.APPROVED, "user", "2026-10-03T01:30:00Z", "P10-S 方向确认",
        draft.brief_hash()))
    approved.validate_for_approval()
    return approved, approved.content_pins(), benchmarks, thesis, treatment, brief


# S1-V1 real content hashes pin the existing P10b authority
def test_s1_v1_pins_equal_real_p10b_content_hashes():
    brief, pins, benchmarks, thesis, treatment, p10b_brief = _approved_brief()
    assert {k: v for k, v in pins.items() if k != "director_brief"} == {
        "brief": content_hash(p10b_brief), "thesis": content_hash(thesis),
        "benchmarks": content_hash(benchmarks), "treatment": content_hash(treatment)}
    assert pins["director_brief"] == brief.brief_hash()
    assert all(len(digest) == 64 for digest in pins.values())


# S1-V2 reference pack keeps real provenance and every epistemic class
def test_s1_v2_pack_is_traceable_to_the_real_artifacts():
    brief, _, _, _, _, _ = _approved_brief()
    pack = brief.reference_pack
    entry = pack.references[0]
    assert entry.provenance is not None
    assert (entry.provenance.uri, entry.provenance.retrieved_at) == (
        "docs/p10/p10_s/benchmark.json", RETRIEVED_AT)
    assert entry.provenance.content_hash == hashlib.sha256(
        (SPIKE / "benchmark.json").read_bytes()).hexdigest()
    assert [c.status for c in pack.constraints] == ["observed", "inferred", "target", "forbidden"]
    assert pack.constraints[2].measurable == "scale_change_ratio 0.65-0.75"
    assert all(c.provenance is not None for c in pack.constraints
               if c.status in (ConstraintStatus.OBSERVED, ConstraintStatus.INFERRED))


# S1-V3 round trip through a real file on disk
def test_s1_v3_brief_survives_a_real_file_round_trip(tmp_path):
    brief, pins, *_ = _approved_brief()
    path = tmp_path / "director_brief.json"
    path.write_text(json.dumps(brief.to_dict(), ensure_ascii=False, sort_keys=True, indent=2),
                    encoding="utf-8")
    restored = DirectorBrief.from_dict(json.loads(path.read_text(encoding="utf-8")))
    restored.validate_for_approval()
    assert restored == brief
    assert restored.brief_hash() == brief.brief_hash()
    assert restored.content_pins() == pins


# S1-V4 the brief pins land in a real P10a revision dir through the existing pin record
def test_s1_v4_pins_record_and_verify_in_a_real_revision_dir(tmp_path):
    _, pins, *_ = _approved_brief()
    store = tmp_path / "store"
    DirectionRepository(store).create_direction_state(PROJECT, DIRECTION, actor="user")
    record_content_pins(store, DIRECTION, 1, pins)
    verify_content_pins(store, DIRECTION, 1, dict(pins))
    recorded = json.loads((store / DIRECTION / "rev_1" / "content.json").read_text("utf-8"))["pins"]
    assert recorded == pins
    state_text = (store / DIRECTION / "rev_1" / "state.json").read_text(encoding="utf-8")
    assert "scale_reveal" not in state_text and "shot_copying" not in state_text


# S1-V5 editing approved content in place is refused at both boundaries
def test_s1_v5_in_place_edit_after_approval_is_refused(tmp_path):
    brief, pins, *_ = _approved_brief()
    store = tmp_path / "store"
    DirectionRepository(store).create_direction_state(PROJECT, DIRECTION, actor="user")
    record_content_pins(store, DIRECTION, 1, pins)
    tampered = replace(brief, reference_pack=replace(
        brief.reference_pack,
        constraints=tuple(
            replace(c, measurable="scale_change_ratio 0.9-1.0") if c.status is ConstraintStatus.TARGET
            else c for c in brief.reference_pack.constraints),
        note="偷偷把尺度区间改成 0.9-1.0"))
    with pytest.raises(DirectorBriefError) as exc:
        tampered.validate_for_approval()
    assert exc.value.code == "APPROVAL_VOID"
    with pytest.raises(ContentValidationError) as pin_exc:
        verify_content_pins(store, DIRECTION, 1, tampered.content_pins())
    assert pin_exc.value.code == "APPROVAL_VOID"
    assert tampered.brief_hash() != brief.brief_hash()
    verify_content_pins(store, DIRECTION, 1, pins)