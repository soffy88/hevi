"""P10b acceptance: B1-B7 content contracts + P10a hookup + authority boundary."""

import ast
from pathlib import Path

import pytest

from hevi.creative.direction_content import (
    BenchmarkReference,
    BenchmarkSet,
    ContentValidationError,
    CreativeBrief,
    CreativeThesis,
    ExtractedPrinciple,
    FactualClaim,
    HardRequirement,
    ReviewRefusal,
    Treatment,
    TreatmentAlternative,
    build_review_pack,
    content_hash,
    record_content_pins,
    verify_content_pins,
)
from hevi.creative.direction_state import DirectionRepository


def _brief(**kw):
    base = {"subject": "black hole scale", "objective": "awe", "audience": "general"}
    return CreativeBrief(**{**base, **kw})


def _thesis(**kw):
    base = {"logline": "l", "central_question": "q", "emotional_arc": "a", "audience_effect": "e"}
    return CreativeThesis(**{**base, **kw})


def _benchmark(**kw):
    ref = BenchmarkReference(id="bm1", title="t", uri="u", retrieved_at="r",
                             reference_hash="h",
                             principles=(ExtractedPrinciple("BP1", "s", "cinematography"),),
                             **kw)
    return BenchmarkSet((ref,))


def _treatment(**kw):
    alts = (TreatmentAlternative("T1", "s1", "r1"), TreatmentAlternative("T2", "s2", "r2"),
            TreatmentAlternative("T3", "s3", "r3"))
    base = {"thesis_ref": "th1", "structure": "3-act", "alternatives": alts,
            "comparison_criteria": ("pace",), "comparison_matrix": {"T1": {"pace": "fast"}},
            "selected": "T1", "selected_by_actor": "user", "selection_rationale": "fits scale"}
    return Treatment(**{**base, **kw})


# B1
def test_b1_hardreq_assertion_or_h():
    ok = _brief(hard_requirements=(HardRequirement("HR1", "dur<=30s",
                                                   {"type": "duration_lte", "value_ms": 30000}, "D"),))
    ok.validate()
    with pytest.raises(ContentValidationError):
        _brief(hard_requirements=(HardRequirement("HR2", "must thrill", {}, "D"),)).validate()
    _brief(hard_requirements=(HardRequirement("HR3", "must thrill", {}, "H"),)).validate()


# B4
def test_b4_thesis_four_part_and_fact_pin():
    _thesis().validate()
    with pytest.raises(ContentValidationError):
        _thesis(logline="").validate()
    with pytest.raises(ContentValidationError):
        _thesis(factual_claims=(FactualClaim("holes discovered 2019"),)).validate()
    _thesis(factual_claims=(FactualClaim("M87 imaged 2019", "canon:fact12"),)).validate()


# B3
def test_b3_benchmark_provenance():
    _benchmark().validate()
    with pytest.raises(ContentValidationError):
        _benchmark(transfer_mode="structure_clone").validate()
    with pytest.raises(ContentValidationError):
        BenchmarkSet((BenchmarkReference(id="x", title="t"),)).validate()
    assert _benchmark().principle_ids() == {"BP1"}


# B2
def test_b2_treatment_k_criteria_selection():
    _treatment().validate()
    with pytest.raises(ContentValidationError):  # K=2 无理由
        _treatment(alternatives=(TreatmentAlternative("T1", "s1"), TreatmentAlternative("T2", "s2"))).validate()
    _treatment(alternatives=(TreatmentAlternative("T1", "s1"),),
               short_form_reason="spike single candidate").validate()
    with pytest.raises(ContentValidationError):  # 标准晚于打分
        _treatment(comparison_criteria=(), comparison_matrix={"T1": {"pace": "x"}}).validate()
    with pytest.raises(ContentValidationError):
        _treatment(selected="T9").validate()
    with pytest.raises(ContentValidationError):
        _treatment(selection_rationale="").validate()


# B5 review pack diff + refusal reason
def test_b5_review_pack():
    base = {"brief": "h1", "thesis": "h1", "benchmarks": "h1", "treatment": "h1"}
    new = {"brief": "h1", "thesis": "h2", "benchmarks": "h1", "treatment": "h1"}
    pack = build_review_pack(base_pins=base, new_pins=new, base_revision=1, new_revision=2,
                             rerun_cost_class="medium", benchmark_provenance=("BP1",),
                             refusals=(ReviewRefusal("D18", "too vague", "user", "c-r"),))
    assert set(pack.changed_groups) == {"thesis"} and pack.pack_hash
    assert pack.refusals[0].reason == "too vague"


# B6 state hookup: pins per revision, drift -> APPROVAL_VOID, P10a untouched
def test_b6_revision_pins_and_void(tmp_path):
    repo = DirectionRepository(tmp_path / "store")
    repo.create_direction_state("p", "d")
    pins = {"brief": content_hash(("b",)), "thesis": content_hash(("t",)),
            "benchmarks": content_hash(("m",)), "treatment": content_hash(("r",))}
    record_content_pins(tmp_path / "store", "d", 1, pins)
    verify_content_pins(tmp_path / "store", "d", 1, dict(pins))
    tampered = dict(pins, thesis=content_hash(("t2",)))
    with pytest.raises(ContentValidationError) as exc:
        verify_content_pins(tmp_path / "store", "d", 1, tampered)
    assert exc.value.code == "APPROVAL_VOID"
    with pytest.raises(ContentValidationError):
        record_content_pins(tmp_path / "store", "d", 1, {"brief": "h"})
    # P10a state files carry no content: content.json sits beside state files
    names = {p.name for p in (tmp_path / "store" / "d" / "rev_1").iterdir()}
    assert {"state.json", "meta.json", "content.json"} <= names
    assert not (tmp_path / "store" / "d" / "rev_1" / "state.json").read_text().__contains__("thesis")


# B7 authority boundary: no Canon/Style/Asset/Provider imports
def test_b7_no_authority_imports():
    mods = ["models.py", "review_pack.py", "errors.py", "__init__.py"]
    banned = ("layer4_legacy", "production.p6", "production.p7", "providers.registry",
              "provider_policy", "studio.timeline", "narrative.revision")
    pkg = Path(__file__).resolve().parents[2] / "hevi" / "creative" / "direction_content"
    for mod in mods:
        tree = ast.parse((pkg / mod).read_text(encoding="utf-8"))
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
            elif isinstance(node, ast.Import):
                imports.update(a.name for a in node.names)
        hits = [i for i in imports if i.startswith("hevi.") and any(b in i for b in banned)]
        assert not hits, f"{mod}: {hits}"
