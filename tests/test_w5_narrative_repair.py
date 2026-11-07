"""W5：叙事检查补环（反应 C8 / 动作衔接 C9）+ 蒙太奇阶段清单 + 修复路由补码。

离线纯规则测试，不调用任何付费链。
"""

from __future__ import annotations

from itertools import pairwise

from hevi.quality import (
    FailureCode,
    GatePolicy,
    QualityEvaluation,
    QualityEvidence,
    RepairBudget,
    RepairController,
    apply_repair_decision,
)
from hevi.quality.taxonomy import normalize_failure, severity_for
from hevi.storyplan.autofill import autofill_story_plan
from hevi.storyplan.check import run_story_check
from hevi.storyplan.model import BEAT_KINDS, ChangeStage, StoryBeat


def _check(report, check_id: str):
    return next(c for c in report.checks if c.check_id == check_id)


def _shots(plan):
    return [sh for seq in plan.shots.sequences for sc in seq.scenes for sh in sc.shots]


# ── 1. 反应环 C8 ──────────────────────────────────────────────────────────

def test_reaction_is_valid_beat_kind():
    assert "reaction" in BEAT_KINDS
    beat = StoryBeat(beat_id="b_react", phase="reaction", summary="主角开心拍手")
    assert beat.phase == "reaction"


def test_c8_passes_when_reaction_follows_result():
    plan = autofill_story_plan("小水滴去哪儿了", aspect="16:9")
    phases = [b.phase for b in plan.narrative.beats]
    assert "reaction" in phases and phases.index("reaction") > phases.index("result")
    report = run_story_check(plan)
    assert _check(report, "C8_REACTION_BEAT").status == "PASS"


def test_c8_warns_when_reaction_missing_but_does_not_fail():
    plan = autofill_story_plan("小水滴去哪儿了", aspect="16:9")
    plan.narrative.beats = [b for b in plan.narrative.beats if b.phase != "reaction"]
    report = run_story_check(plan)
    c8 = _check(report, "C8_REACTION_BEAT")
    assert c8.status == "WARN"
    # WARN 不打爆计划：其余检查全绿时整体仍 passed
    assert report.passed is True


def test_c8_warns_when_reaction_precedes_result():
    plan = autofill_story_plan("小水滴去哪儿了", aspect="16:9")
    beats = plan.narrative.beats
    reaction = next(b for b in beats if b.phase == "reaction")
    rest = [b for b in beats if b.phase != "reaction"]
    plan.narrative.beats = [reaction, *rest]
    report = run_story_check(plan)
    assert _check(report, "C8_REACTION_BEAT").status == "WARN"


def test_c8_legacy_plan_without_reaction_does_not_crash():
    # 存量计划（只有 cause/process/result 三拍，类 kids 六拍的 solution+recap
    # 结构映射）不应报错崩溃，只得到 WARN。
    plan = autofill_story_plan("小熊为什么洗手", aspect="9:16")
    plan.narrative.beats = [
        StoryBeat(beat_id="b1", phase="cause", summary="起因", expectation="问题"),
        StoryBeat(beat_id="b2", phase="process", summary="尝试", expectation="办法"),
        StoryBeat(beat_id="b3", phase="result", summary="解决与复述", expectation="回应"),
    ]
    report = run_story_check(plan)
    assert _check(report, "C8_REACTION_BEAT").status == "WARN"

    # 完全无 beats 的空计划也不崩溃
    plan.narrative.beats = []
    report = run_story_check(plan)
    assert _check(report, "C8_REACTION_BEAT").status in {"PASS", "WARN"}


# ── 2. 跨镜动作衔接 C9 ────────────────────────────────────────────────────

def test_c9_passes_on_autofill_plan():
    plan = autofill_story_plan("小水滴去哪儿了", aspect="16:9")
    report = run_story_check(plan)
    assert _check(report, "C9_ACTION_CONTINUITY").status == "PASS"


def test_c9_warns_on_start_end_mismatch():
    plan = autofill_story_plan("小水滴去哪儿了", aspect="16:9")
    shots = _shots(plan)
    shots[1].start_state = "主角突然出现在完全不同的姿势与位置"
    report = run_story_check(plan)
    c9 = _check(report, "C9_ACTION_CONTINUITY")
    assert c9.status == "WARN"
    assert shots[1].shot_id in c9.message
    # WARN 级：不单独把整份计划打成 FAIL
    assert report.passed is True


def test_c9_skips_undeclared_states_and_cross_scene():
    plan = autofill_story_plan("小水滴去哪儿了", aspect="16:9")
    shots = _shots(plan)
    # 未声明 start_state 时不比对
    shots[1].start_state = ""
    report = run_story_check(plan)
    assert _check(report, "C9_ACTION_CONTINUITY").status == "PASS"
    # 跨场景不比对（新场景状态可重置）
    shots[1].start_state = "任意新场景起始状态"
    shots[1].scene_id = "scene_2"
    shots[2].scene_id = "scene_2"
    shots[2].start_state = shots[1].end_state
    report = run_story_check(plan)
    assert _check(report, "C9_ACTION_CONTINUITY").status == "PASS"


# ── 3. 蒙太奇阶段清单 change_stages ───────────────────────────────────────

def test_change_stages_generate_corresponding_beats():
    stages = [
        {"name": "种子", "target_state": "种子埋进土里", "description": "一颗种子落入泥土"},
        ChangeStage(name="发芽", target_state="嫩芽破土而出"),
        {"name": "开花", "target_state": "花朵完全绽放"},
    ]
    plan = autofill_story_plan("小种子长大", aspect="16:9", change_stages=stages)
    beats = plan.narrative.beats
    assert len(beats) == 3
    for beat, stage_name in zip(beats, ["种子", "发芽", "开花"], strict=True):
        assert stage_name in beat.summary
        assert stage_name in beat.semantic_refs
    assert beats[0].phase == "cause"
    assert beats[-1].phase == "result"
    # 时间轴单调且铺满
    assert beats[0].start_ms == 0
    assert beats[-1].end_ms >= beats[0].end_ms
    for prev, curr in pairwise(beats):
        assert curr.start_ms >= prev.start_ms
    # 阶段清单作为中间产物保留在计划上
    assert plan.narrative.change_stages is not None
    assert [s.name for s in plan.narrative.change_stages] == ["种子", "发芽", "开花"]
    assert plan.narrative.change_stages[0].target_state == "种子埋进土里"


def test_no_change_stages_keeps_percentage_beats():
    plan = autofill_story_plan("小水滴去哪儿了", aspect="16:9")
    assert plan.narrative.change_stages is None
    beats = plan.narrative.beats
    total = beats[-1].end_ms
    assert [b.phase for b in beats] == ["cause", "process", "result", "reaction"]
    assert beats[0].start_ms == 0 and beats[0].end_ms == int(total * 0.3)
    assert beats[1].start_ms == int(total * 0.3) and beats[1].end_ms == int(total * 0.75)
    assert beats[2].start_ms == int(total * 0.75)


def test_change_stage_model_defaults_backward_compatible():
    stage = ChangeStage(name="萌芽")
    assert stage.target_state == "" and stage.description == ""
    # 旧 JSON（无 change_stages 字段）可正常反序列化
    plan = autofill_story_plan("小水滴去哪儿了", aspect="16:9")
    data = plan.model_dump()
    data["narrative"].pop("change_stages", None)
    from hevi.storyplan.model import StoryPlan

    restored = StoryPlan(**data)
    assert restored.narrative.change_stages is None


# ── 4. 修复路由补码 ───────────────────────────────────────────────────────

def _failed(code: FailureCode, scope: str = "shot:S01") -> QualityEvidence:
    return QualityEvidence(code=code, scope=scope, passed=False)


def _cinema_policy() -> GatePolicy:
    return GatePolicy(
        profile="cinema",
        required_failures=set(FailureCode),
        advisory_failures=set(),
        allow_checker_failure=False,
    )


def _decide(code: FailureCode):
    controller = RepairController(RepairBudget(max_attempts=1, max_cost_usd=10.0))
    evaluation = QualityEvaluation.from_evidence([_failed(code)], _cinema_policy())
    controller.observe(evaluation)
    return controller.decide(evaluation)


def test_missing_shot_decides_insert_shot_and_executor_records_intent():
    decision = _decide(FailureCode.MISSING_SHOT)
    assert decision.should_repair
    assert decision.actions[0].kind == "insert_shot"
    assert decision.actions[0].reason == FailureCode.MISSING_SHOT
    patch = apply_repair_decision(decision, current_provider="p", current_seed=0)
    assert patch.consumed
    assert patch.insert_shots and patch.insert_shots[0]["after_shot_index"] == 1
    assert patch.insert_shots[0]["reason"] == "MISSING_SHOT"


def test_action_discontinuity_decides_adjust_cut_and_executor_records_intent():
    decision = _decide(FailureCode.ACTION_DISCONTINUITY)
    assert decision.should_repair
    assert decision.actions[0].kind == "adjust_cut"
    assert decision.actions[0].reason == FailureCode.ACTION_DISCONTINUITY
    patch = apply_repair_decision(decision, current_provider="p", current_seed=0)
    assert patch.consumed
    assert patch.cut_adjustments and patch.cut_adjustments[0]["shot_index"] == 1
    assert patch.cut_adjustments[0]["reason"] == "ACTION_DISCONTINUITY"


def test_new_failure_codes_taxonomy_and_aliases():
    assert severity_for(FailureCode.MISSING_SHOT) == 4.0
    assert severity_for(FailureCode.ACTION_DISCONTINUITY) == 3.0
    assert normalize_failure("缺镜") == FailureCode.MISSING_SHOT
    assert normalize_failure("叙事缺口") == FailureCode.MISSING_SHOT
    assert normalize_failure("动作衔接断裂") == FailureCode.ACTION_DISCONTINUITY
    # 裸「动作」别名仍指向 ACTION_MISSING，不被新别名劫持
    assert normalize_failure("动作") == FailureCode.ACTION_MISSING
