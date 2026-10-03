"""Q1-Q3/Q5-Q9 收口验收。"""

import pytest

from hevi.creative.direction_content import (
    ContentValidationError,
    CreativeBrief,
    CreativeThesis,
    FactualClaim,
    HardRequirement,
    Treatment,
    TreatmentAlternative,
)
from hevi.creative.direction_plan.authority_pin import parse_pin, resolve_pin
from hevi.creative.direction_plan.models import (
    CameraSpec,
    Movement,
    PlanValidationError,
    SignatureShot,
    check_signature_unique,
)
from hevi.creative.direction_plan.tolerance import calibrate, default_tolerance_ms
from hevi.creative.direction_verify.cost import CostTable, default_cost_table
from hevi.creative.direction_verify.errors import VerifyError
from hevi.creative.direction_verify.memory import CreativeMemory, MemoryEntry
from hevi.director.script_identity import (
    ScriptUnit,
    build_translation_index,
    namespaced_unit_id,
)


# ── Q5 多语言单元对应 ──
def test_q5_namespace_and_index():
    assert namespaced_unit_id("scene1.line004", "zh") == "zh:scene1.line004"
    assert namespaced_unit_id("zh:scene1.line004", "en") == "en:scene1.line004"  # 不叠加

    index = build_translation_index(language="zh", pairs=[
        ("scene1.line001", "scene1.line001"), ("scene1.line002", "scene1.line002")])
    assert index.targets("scene1.line001") == ("zh:scene1.line001",)
    # 源删了一行 → 翻译侧对应缺失,必须能报出来
    assert index.missing_sources(("scene1.line001", "scene1.line999")) == ("scene1.line999",)


def test_q5_translation_never_infers_from_text():
    """译文文本与源文不同 → 自动按文本配对会错连,故 API 不提供该推断。"""
    source = [ScriptUnit("s1", "scene1", 0, "黑洞不是洞")]
    target = [ScriptUnit("t1", "scene1", 0, "A black hole is not a hole")]
    assert build_translation_index(language="en", pairs=[]).links == ()
    # 未经显式声明对应 → 索引为空(不猜),尽管两侧都有同位置的单元
    assert source[0].unit_id != target[0].unit_id


# ── Q6 容差标定 ──
def test_q6_defaults_and_floor():
    assert default_tolerance_ms("SYNC_NORMAL", 30) == 67  # ~2 帧
    assert default_tolerance_ms("EVENT_LOOSE", 30) == 250
    assert default_tolerance_ms("SYNC_STRICT", 30) == 125


def test_q6_calibration_requires_samples():
    with pytest.raises(PlanValidationError):
        calibrate("EVENT_LOOSE", [], fps=30)
    with pytest.raises(PlanValidationError):
        calibrate("EVENT_LOOSE", [10, 20], fps=30)  # <5 不猜


def test_q6_calibration_proposes_p95_with_floor():
    samples = [40, 55, 60, 70, 80, 90, 120, 200, 260, 410]
    calib = calibrate("EVENT_LOOSE", samples, fps=30)
    assert calib.sample_count == 10 and calib.proposed_ms == calib.p95_ms >= calib.p50_ms
    assert calib.floor_ms == 33  # 1 帧
    assert calib.apply(250) >= 250  # 只放宽需显式,不静默收紧


# ── Q7 签名镜头预算 ──
def test_q7_signature_budget_default_two():
    def shot(i: int) -> SignatureShot:
        sizes = ("extreme_wide", "wide", "medium", "close")
        return SignatureShot(f"S{i}", camera=CameraSpec(
            shot_size=sizes[i % len(sizes)],
            movement=Movement("pull_back" if i % 2 else "push_in", "extrinsic")),
            uniqueness_reason=f"u{i}")

    check_signature_unique([shot(1), shot(2)])  # 2 个 = 上限
    with pytest.raises(PlanValidationError) as exc:
        check_signature_unique([shot(1), shot(2), shot(3)])
    assert exc.value.code == "SIGNATURE_OVER_BUDGET"
    check_signature_unique([shot(1), shot(2), shot(3)], max_count=3)  # 可配置放宽


# ── Q9 成本表 ──
def test_q9_cost_table_estimate_takes_worst():
    table = default_cost_table()
    bound = table.estimate([("ShotPlan", "low"), ("Generate", "high"), ("TTS", "none")])
    assert bound.cost_class == "high" and bound.max_usd > 0
    assert table.estimate([("TTS", "none")]).cost_class == "none"


def test_q9_unconfigured_cost_class_fails_loud():
    with pytest.raises(VerifyError) as exc:
        CostTable({}).estimate([("Generate", "high")])
    assert exc.value.code == "COST_TABLE_UNCONFIGURED"


# ── Q1/Q2/Q3 决策落码 ──
def test_q1_short_form_needs_reason():
    alts3 = (TreatmentAlternative("T1", "s1"), TreatmentAlternative("T2", "s2"),
             TreatmentAlternative("T3", "s3"))
    base = {"thesis_ref": "t", "structure": "s", "alternatives": alts3,
            "selected": "T1", "selected_by_actor": "user", "selection_rationale": "r"}
    Treatment(**base).validate()  # K=3 无需理由
    two = (TreatmentAlternative("T1", "s1"), TreatmentAlternative("T2", "s2"))
    with pytest.raises(ContentValidationError):
        Treatment(**{**base, "alternatives": two}).validate()  # K=2 无理由 → 拒
    Treatment(**{**base, "alternatives": two, "short_form_reason": "≤30s spike"}).validate()


def test_q2_global_scope_explicitly_disabled():
    mem = CreativeMemory()
    with pytest.raises(VerifyError) as exc:
        mem.record(MemoryEntry("m", "preference", "c", "p", evidence=("v1",), scope="global"))
    assert exc.value.code == "MEMORY_SCOPE_GLOBAL_DISABLED"
    mem.record(MemoryEntry("m", "preference", "c", "p", evidence=("v1",), scope="user"))
    assert mem.suggest()[0].scope == "user"


def test_q3_structure_clone_still_forbidden():
    from hevi.creative.direction_content import (
        BenchmarkReference,
        BenchmarkSet,
        ExtractedPrinciple,
    )
    ref = BenchmarkReference(id="bm", title="t", uri="u", retrieved_at="r", reference_hash="h",
                             principles=(ExtractedPrinciple("BP1", "s"),))
    BenchmarkSet((ref,)).validate()
    with pytest.raises(ContentValidationError) as exc:
        BenchmarkSet((BenchmarkReference(id="bm", title="t", uri="u", retrieved_at="r",
                                         reference_hash="h",
                                         principles=(ExtractedPrinciple("BP1", "s"),),
                                         transfer_mode="structure_clone"),)).validate()
    assert exc.value.code == "BENCHMARK_TRANSFER_FORBIDDEN"


def test_brief_thesis_guards_still_hold():
    CreativeBrief("s", "o", "a").validate()
    CreativeThesis("l", "q", "e", "f").validate()
    with pytest.raises(ContentValidationError):
        CreativeThesis("l", "q", "e", "f", factual_claims=(FactualClaim("x"),)).validate()
    with pytest.raises(ContentValidationError):
        CreativeBrief("s", "o", "a", hard_requirements=(HardRequirement("H", "x", {}, "D"),)).validate()


def test_a13_pin_example_still_resolves():
    pin = parse_pin("provider", "wan@2.1")
    assert resolve_pin(pin, {"provider": {"wan@2.1": "h"}}).content_hash == "h"