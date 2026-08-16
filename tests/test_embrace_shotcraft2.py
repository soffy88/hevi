"""Round 3 二轮对照(shotcraft sequences + final-review)测试。"""

from __future__ import annotations

from hevi.assembly.promo_video_workflow import PromoConfig, PromoInput, promo_video_workflow
from hevi.motion.sequence import (
    PROMO_ENERGY_ARC,
    PlannedShot,
    find_sequence_pattern,
    plan_sequence,
)
from hevi.verdict.final_review import (
    FINAL_REVIEW_CHECKS,
    render_review_report,
    run_final_review,
    save_review_result,
)

# ---- 序列模式(能量弧)----

def test_sequence_pattern_segments():
    assert len(PROMO_ENERGY_ARC.segments) == 4
    roles = [s.role for s in PROMO_ENERGY_ARC.segments]
    assert roles == ["brand_open", "hero", "feature_climb", "launch_peak"]
    assert find_sequence_pattern("promo-energy-arc") is PROMO_ENERGY_ARC


def test_plan_sequence_allocation_order():
    shots = plan_sequence(
        PROMO_ENERGY_ARC, total_duration_s=30.0, fps=30, feature_count=3
    )
    # 顺序:brand_open → hero → feature/breath 交错 → launch_peak
    assert shots[0].role == "brand_open"
    assert shots[1].role == "hero"
    assert shots[-1].role == "launch_peak"
    # start_frame 连续递增
    frames = [s.start_frame for s in shots]
    assert frames == sorted(frames)
    # hold/rest 预算内先划走
    assert shots[0].hold_frames > 0
    assert shots[1].hold_frames == 0  # hero 段无 hold_at_end
    assert any(s.rest_frames > 0 for s in shots)  # 功能段批量收尾静止
    # 呼吸字卡存在且能量低
    breath = [s for s in shots if s.role == "breath"]
    assert 2 <= len(breath) <= 4
    assert all(b.energy == "low" for b in breath)


def test_plan_sequence_feature_energy_alternates():
    shots = [s for s in plan_sequence(
        PROMO_ENERGY_ARC, total_duration_s=30.0, fps=30, feature_count=4
    ) if s.role == "feature_climb"]
    assert len(shots) == 4
    energies = [s.energy for s in shots]
    assert energies[0] == "high" and energies[1] == "medium"
    assert energies[2] == "high" and energies[3] == "medium"


def test_plan_sequence_total_budget_respected():
    shots = plan_sequence(
        PROMO_ENERGY_ARC, total_duration_s=60.0, fps=30, feature_count=5
    )
    assert shots[-1].start_frame + shots[-1].duration_frames <= 60 * 30 + 1


def test_plan_sequence_zero_duration():
    assert plan_sequence(PROMO_ENERGY_ARC, total_duration_s=0, fps=30, feature_count=1) == []


def test_planned_shot_to_dict():
    shot = PlannedShot(
        role="hero", index=1, start_frame=100, duration_frames=60,
        energy="medium", purpose="立传", candidate_cards=("spotlight-hero-card",),
    )
    d = shot.to_dict()
    assert d["role"] == "hero" and d["start_frame"] == 100


# ---- promo workflow 用序列模式 ----

def test_promo_workflow_uses_sequence_plan(tmp_path):
    cfg = PromoConfig(
        product_name="Acme", energy_axis=1.0, tone_axis=0.5,
        features=["a", "b", "c"], target_duration_s=30.0,
    )
    res = __import__("asyncio").run(promo_video_workflow(cfg, PromoInput(), tmp_path))
    assert res["status"] == "completed"
    plan = res["plan"]
    # 既有断言保持:头尾卡在位
    assert "spotlight-hero-card" in plan["shot_cards"]
    assert "outro-wordmark-settle" in plan["shot_cards"]
    # 新增:序列分配存在
    assert len(plan["sequence_plan"]) >= 6  # brand+hero+3feature(+breath)+peak
    roles = [s["role"] for s in plan["sequence_plan"]]
    assert roles[0] == "brand_open"
    assert roles[-1] == "launch_peak"


# ---- 成片独立终检协议 ----

def test_review_checks_structure():
    groups = {c[0] for c in FINAL_REVIEW_CHECKS}
    assert groups == {"P", "F", "V", "S", "B", "D"}
    codes = [c[1] for c in FINAL_REVIEW_CHECKS]
    assert len(codes) == len(set(codes))  # 编号唯一


def test_final_review_missing_inputs_unverifiable():
    result = run_final_review({})  # 无任何输入
    assert result.missing_inputs
    assert result.unverifiable
    assert not result.passed
    assert all(c["state"] == "unverifiable" for c in result.checks)


def test_final_review_with_inputs_and_verdicts():
    inputs = {
        "final_mp4": True, "keyframes": True, "brief": True, "decision_table": True,
        "visual_direction": True, "shot_mapping": True, "card_library": True,
        "demo_tsx": True, "reference_preview": True, "final_storyboard": True,
        "aesthetic_rules": True, "data_policy": True,
    }
    verdicts = {code: True for _, code, _, _ in FINAL_REVIEW_CHECKS}
    result = run_final_review(inputs, verdicts=verdicts)
    assert not result.missing_inputs
    assert not result.unverifiable
    assert result.passed
    assert all(c["state"] == "pass" for c in result.checks)


def test_final_review_fail_and_conflict():
    inputs = {"brief": True, "shot_mapping": True, "final_storyboard": True}
    result = run_final_review(
        inputs,
        verdicts={"P1": True, "F1": False},
        conflicts=["library.json 的 style-key 与 demo TSX 的变体不一致"],
    )
    assert any(c["code"] == "F1" and c["state"] == "fail" for c in result.checks)
    assert result.conflicts
    assert not result.passed


def test_review_report_render():
    result = run_final_review({"brief": True}, verdicts={"P1": True})
    report = render_review_report(result)
    assert "P1" in report
    assert "无法验证" in report  # 多数项缺输入


def test_save_review_result(tmp_path):
    result = run_final_review({"brief": True})
    p = save_review_result(result, tmp_path / "review.json")
    assert p.exists()
    assert "passed" in p.read_text(encoding="utf-8")
