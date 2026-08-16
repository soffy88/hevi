"""Round 3e(dramaclaw 全面落地)测试: 候选提升 / 修复 agent / 风格画像 / 草图编辑 / Xia 会话。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.director.assistant import EpisodeState, ShotState
from hevi.director.chat_assistant import (
    XiaAssistant,
    XiaSession,
    detect_intent,
    respond_repair,
    respond_status,
)
from hevi.director.promotion import (
    PROMOTE_FLOOR,
    PromotionCandidate,
    PromotionPool,
    score_and_promote_batch,
)
from hevi.director.repair_agents import (
    REPAIR_AGENTS,
    plan_repair,
    repair_decision,
)
from hevi.director.sketch_edit import (
    SketchEditOp,
    SketchEditorError,
    SketchEditResult,
    apply_sketch_edits,
    score_sketch_with_labels,
    structure_difference,
)
from hevi.style.style_analyzer import (
    analyze_reference_image,
    build_full_profile,
    merge_with_draft,
    save_profile,
)
from hevi.verdict.convergence import ConvergenceLog

# ---- ① 候选提升双轨 ----

def test_promotion_promote_gate():
    pool = PromotionPool()
    cand = PromotionCandidate(
        candidate_id="c1", kind="character", name="主角", source="freezone", score=0.9
    )
    pool.add_candidate(cand)
    asset, issues = pool.promote("c1")
    assert issues == []
    assert asset is not None and asset.kind == "character"
    assert cand.promoted
    # 同名冲突:再提一个同名 → 被拦
    pool.add_candidate(
        PromotionCandidate(
            candidate_id="c2", kind="character", name="主角",
            source="pool", score=0.95,
        )
    )
    _, issues2 = pool.promote("c2")
    assert any("conflict" in i for i in issues2)


def test_promotion_low_score_rejected():
    pool = PromotionPool()
    pool.add_candidate(
        PromotionCandidate(
            candidate_id="c1", kind="prop", name="剑",
            source="generated", score=0.4,
        )
    )
    asset, issues = pool.promote("c1")
    assert asset is None
    assert any("floor" in i for i in issues)


def test_promotion_reject_records_reason():
    pool = PromotionPool()
    pool.add_candidate(
        PromotionCandidate(
            candidate_id="c1", kind="scene", name="院落",
            source="generated", score=0.5,
        )
    )
    assert pool.reject("c1", "构图不合格")
    assert pool.candidates[0].rejected_reason == "构图不合格"
    assert pool.reject("nope", "x") is False


def test_promotion_batch_with_scorers():
    pool = PromotionPool()
    pool.add_candidate(
        PromotionCandidate(candidate_id="c1", kind="character", name="A", source="pool")
    )
    pool.add_candidate(
        PromotionCandidate(candidate_id="c2", kind="character", name="B", source="pool")
    )
    scorers = {
        "character": lambda payload: (0.8, "VLM 一致"),
    }
    results = score_and_promote_batch(pool, scorers=scorers)
    assert sum(1 for r in results if r["promoted"]) == 2
    assert all(r["score"] >= PROMOTE_FLOOR for r in results)


def test_promotion_roundtrip_json(tmp_path):
    pool = PromotionPool()
    pool.add_candidate(
        PromotionCandidate(
            candidate_id="c1", kind="voice", name="声线",
            source="generated", score=0.85,
        )
    )
    pool.promote("c1")
    p = tmp_path / "promo.json"
    pool.save(p)
    loaded = PromotionPool.load(p)
    assert len(loaded.candidates) == 1
    assert len(loaded.locked) == 1
    assert loaded.locked[0].kind == "voice"


# ---- ② 修复 agent 编排 ----

def test_plan_repair_known_diagnoses():
    failures = [
        {"shot_id": "s1", "diagnosis": "参考图角色错配"},
        {"shot_id": "s2", "diagnosis": "光照"},
    ]
    plan = plan_repair(failures, budget_limit=3)
    assert len(plan.actions) == 2
    assert plan.actions[0].agent == "character_fixer"
    assert plan.actions[1].lever == "prompt_lighting"


def test_plan_repair_unknown_diagnosis():
    plan = plan_repair([{"shot_id": "s1", "diagnosis": "怪问题"}])
    assert plan.actions[0].agent == "content_rewriter"
    assert "先定根因" in plan.actions[0].instruction


def test_plan_repair_budget_cap():
    failures = [{"shot_id": f"s{i}", "diagnosis": "光照"} for i in range(10)]
    plan = plan_repair(failures, budget_limit=3)
    assert len(plan.actions) == 3
    assert plan.budget_used == 3


def test_repair_decision_budget_exhausted_diverging():
    convergence = ConvergenceLog()
    convergence.add_round(episode_num=1, phase="rework", residual_count=1, fixed_count=0)
    convergence.add_round(episode_num=1, phase="rework", residual_count=3, fixed_count=0)
    convergence.add_round(episode_num=1, phase="rework", residual_count=5, fixed_count=0)
    plan = plan_repair(
        [{"shot_id": f"s{i}", "diagnosis": "光照"} for i in range(5)],
        budget_limit=3,
    )  # 预算 3/3 用尽
    decision = repair_decision(plan, convergence, episode_num=1, phase="rework")
    assert decision["budget_exhausted"]
    assert "降级交付" in decision["suggestion"]


def test_repair_agents_table_covers_common():
    assert "参考图角色错配" in REPAIR_AGENTS
    assert "动作" in REPAIR_AGENTS
    assert "运镜" in REPAIR_AGENTS


# ---- ③ 风格画像 ----

def _make_image(path: Path, color: tuple[int, int, int], size: tuple[int, int] = (32, 24)) -> Path:
    from PIL import Image

    Image.new("RGB", size, color).save(path)
    return path


def test_analyze_reference_image_palette():
    p = _make_image(Path("/tmp/x.png"), (200, 50, 50))
    profile = analyze_reference_image(p)
    assert profile.palette  # 有主色板
    assert profile.dominant_color.startswith("#")
    assert 0.3 < profile.brightness < 0.5  # 亮红 (200,50,50)/3*255 ≈ 0.39
    assert profile.warmth > 0.2  # 偏暖
    assert profile.saturation > 0.5  # 高饱和


def test_analyze_reference_image_cool_dark():
    p = _make_image(Path("/tmp/y.png"), (30, 30, 120))
    profile = analyze_reference_image(p)
    assert profile.warmth < 0
    assert profile.brightness < 0.5


def test_build_full_profile_with_vlm():
    p = _make_image(Path("/tmp/z.png"), (200, 200, 200))
    profile = build_full_profile(
        p, vlm_draft=lambda img: {"style": "cinematic", "lighting": "soft"}
    )
    assert profile.language["style"] == "cinematic"
    assert profile.palette  # 确定性画像保留


def test_merge_with_draft_and_save(tmp_path):
    p = _make_image(tmp_path / "a.png", (10, 200, 10))
    profile = analyze_reference_image(p)
    merged = merge_with_draft(profile, {"camera": "slow push-in"})
    assert merged.language["camera"] == "slow push-in"
    saved = save_profile(merged, tmp_path / "profile.json")
    assert saved.exists()
    data = __import__("json").loads(saved.read_text(encoding="utf-8"))
    assert data["palette"] == profile.palette


# ---- ④ 草图编辑子系统 ----

def _make_sketch(path: Path) -> Path:
    from PIL import Image

    Image.new("L", (80, 60), 200).save(path)
    return path


def test_apply_sketch_edits_crop_reframe():
    src = _make_sketch(Path("/tmp/sk.png"))
    result = apply_sketch_edits(
        src,
        Path("/tmp/sk_out.png"),
        ops=[
            SketchEditOp(op="crop", params={"box": [0, 0, 40, 30]}),
            SketchEditOp(op="reframe", params={"width": 60, "height": 60}),
            SketchEditOp(op="grayscale"),
        ],
    )
    assert isinstance(result, SketchEditResult)
    assert "crop" in result.applied and "reframe" in result.applied
    assert result.out_path.exists()


def test_apply_sketch_edits_unknown_op_warns():
    src = _make_sketch(Path("/tmp/sk2.png"))
    result = apply_sketch_edits(src, Path("/tmp/sk2_out.png"), [SketchEditOp(op="magic")])
    assert result.warnings
    assert result.applied == []


def test_apply_sketch_edits_missing_file():
    with pytest.raises(SketchEditorError):
        apply_sketch_edits(
            Path("/nope.png"),
            Path("/tmp/o.png"),
            [SketchEditOp(op="crop", params={"box": [0, 0, 1, 1]})],
        )


def test_structure_difference():
    a = _make_sketch(Path("/tmp/str_a.png"))
    b = _make_sketch(Path("/tmp/str_b.png"))  # 同构 → 差小
    assert structure_difference(a, b) < 0.05
    from PIL import Image

    Image.new("L", (80, 60), 0).save("/tmp/str_c.png")
    assert structure_difference(a, Path("/tmp/str_c.png")) > 0.2


def test_score_sketch_with_labels():
    s = score_sketch_with_labels(coverage=0.9, composition_ok=True, style_match=0.8)
    assert s["score"] > 1.0
    bad = score_sketch_with_labels(coverage=0.9, composition_ok=False, style_match=0.8)
    assert bad["score"] == 0.0
    invalid = score_sketch_with_labels(
        coverage=0.9, composition_ok=True, style_match=0.8, labels_valid=False
    )
    assert invalid["label_violations"]


# ---- ⑤ Xia 会话层 ----

def _session_with_state() -> XiaSession:
    return XiaSession(
        project_id="p1",
        episodes=[
            EpisodeState(
                episode_id="e1",
                shots=[
                    ShotState(index=1, status="done", passed=True),
                    ShotState(index=2, status="rework", passed=False, diagnosis="光照"),
                ],
            )
        ],
    )


def test_detect_intent():
    assert detect_intent("进度如何?") == "status"
    assert detect_intent("帮我推进下一步") == "advance"
    assert detect_intent("检查交付完整性") == "audit"
    assert detect_intent("修复失败的镜头") == "repair"
    assert detect_intent("提升候选") == "promote"


def test_respond_status_uses_audit():
    reply = respond_status(_session_with_state())
    assert "50.0%" in reply or "50%" in reply
    assert "下一步" in reply


def test_respond_repair_uses_agents():
    session = _session_with_state()
    reply = respond_repair(session)
    assert "修复计划" in reply
    assert "episode_fixer" in reply  # 光照 → episode_fixer


def test_xia_assistant_handle_and_persist(tmp_path):
    assistant = XiaAssistant()
    res = assistant.handle("p1", "进度如何?")
    assert res["intent"] == "status"
    assert res["turn"] == 1
    res2 = assistant.handle("p1", "修复失败的镜头")
    assert res2["intent"] == "repair"
    p = tmp_path / "xia.json"
    assistant.save(p)
    loaded = XiaAssistant.load(p)
    assert loaded.session("p1").turn_count == 2
