"""Phase C 内化测试: remotion 契约 / promo 八阶段 / 引导共创 / 线稿分镜 / 导演助理。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.assembly.guided_co_creation import (
    CHECKPOINTS,
    CoCreationState,
    next_questions,
)
from hevi.assembly.promo_video_workflow import (
    PromoConfig,
    PromoInput,
    promo_video_workflow,
)
from hevi.assembly.remotion_render_workflow import (
    CONTRACT_ITEMS,
    RemotionConfig,
    RemotionInput,
    check_render_contract,
    remotion_render_workflow,
)
from hevi.director.assistant import (
    EpisodeState,
    ShotState,
    audit_production,
)
from hevi.director.sketch_storyboard import (
    SketchCandidate,
    SketchStoryboardError,
    color_consistency_check,
    run_visual_gate,
    select_best_sketch,
)

# ---- render contract ----

def test_contract_items_complete():
    assert len(CONTRACT_ITEMS) == 5
    assert "safe_area" in CONTRACT_ITEMS
    assert "one_move_per_shot" in CONTRACT_ITEMS


def test_check_render_contract():
    ok = RemotionConfig(
        project_dir=Path("/tmp"), composition_id="X", output_path=Path("/tmp/o.mp4")
    )
    assert check_render_contract(ok) == []
    bad_shake = RemotionConfig(
        project_dir=Path("/tmp"),
        composition_id="X",
        output_path=Path("/tmp/o.mp4"),
        props={"shake": True},
    )
    assert check_render_contract(bad_shake) != []
    assert check_render_contract(RemotionConfig(
        project_dir=Path("/tmp"), composition_id="X", output_path=Path("/tmp/o.mp4"), width=0
    )) != []


def test_render_workflow_fails_gracefully_missing_project(tmp_path):
    cfg = RemotionConfig(
        project_dir=tmp_path / "nope",
        composition_id="X",
        output_path=tmp_path / "o.mp4",
    )
    res = __import__("asyncio").run(remotion_render_workflow(cfg, RemotionInput(), tmp_path))
    assert res["status"] == "failed"


def test_render_workflow_does_not_accept_zero_exit_without_artifact(tmp_path, monkeypatch):
    project = tmp_path / "remotion"
    project.mkdir()
    (project / "package.json").write_text("{}", encoding="utf-8")

    class _Process:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(
        "hevi.assembly.remotion_render_workflow.subprocess.run",
        lambda *a, **k: _Process(),
    )
    cfg = RemotionConfig(
        project_dir=project,
        composition_id="X",
        output_path=tmp_path / "missing.mp4",
    )
    res = __import__("asyncio").run(
        remotion_render_workflow(cfg, RemotionInput(), tmp_path / "run")
    )
    assert res["status"] == "failed"
    assert "no media artifact" in res["error"]


# ---- promo workflow ----

def test_promo_workflow_plan(tmp_path):
    cfg = PromoConfig(
        product_name="Acme", energy_axis=1.0, tone_axis=0.5, features=["a", "b", "c"]
    )
    res = __import__("asyncio").run(promo_video_workflow(cfg, PromoInput(), tmp_path))
    assert res["status"] == "completed"
    plan = res["plan"]
    assert plan["motion_preset"] in {"bold", "playful"}
    assert "spotlight-hero-card" in plan["shot_cards"]
    assert "outro-wordmark-settle" in plan["shot_cards"]
    assert plan["sound_design"]["sfx_pins"] >= 1
    assert "final_review" in plan["stages_passed"]
    # 终检报告格式
    assert "R1 ✓" in plan["final_review"] or "R1 ?" in plan["final_review"]


def test_promo_workflow_requires_product_name(tmp_path):
    cfg = PromoConfig(product_name="  ")
    res = __import__("asyncio").run(promo_video_workflow(cfg, PromoInput(), tmp_path))
    assert res["status"] == "failed"


# ---- guided co-creation ----

def test_co_creation_checkpoint_flow():
    state = CoCreationState()
    assert state.current_stage == "product_brief"
    q = next_questions(state)
    assert 1 <= len(q) <= 3
    state.confirm()
    assert state.current_stage == "requirements"
    # 逐级确认到完成
    while not state.done:
        state.confirm()
    assert state.done
    assert len(state.confirmed) == len(CHECKPOINTS)


def test_co_creation_delegate():
    state = CoCreationState()
    state.delegate()
    assert state.autonomous
    assert state.done
    assert next_questions(state) == []


# ---- sketch storyboard ----

def test_sketch_gate_selects_best():
    cands = [
        SketchCandidate(
            path=Path("a.png"), beat_id="b1", coverage=0.9, composition_ok=True, style_match=0.8
        ),
        SketchCandidate(
            path=Path("b.png"), beat_id="b1", coverage=1.0, composition_ok=False, style_match=0.9
        ),
        SketchCandidate(
            path=Path("c.png"), beat_id="b1", coverage=0.5, composition_ok=True, style_match=0.9
        ),
    ]
    chosen = select_best_sketch(cands)
    assert chosen is not None and chosen.path.name == "a.png"  # b 构图不合规排除
    result = run_visual_gate(cands, coverage_floor=0.6, style_floor=0.5)
    assert result.passed
    assert result.chosen == chosen


def test_sketch_gate_rejects_low_coverage():
    cands = [SketchCandidate(path=Path("x.png"), beat_id="b1", coverage=0.4, composition_ok=True)]
    result = run_visual_gate(cands, coverage_floor=0.6)
    assert not result.passed
    assert "coverage_below_floor" in result.failure_codes


def test_color_consistency_check(tmp_path):
    from PIL import Image

    sk = tmp_path / "sketch.png"
    col = tmp_path / "color.png"
    Image.new("L", (32, 32), 200).save(sk)
    Image.new("L", (32, 32), 180).save(col)  # 同构,亮度微差
    assert color_consistency_check(sk, col)
    other = tmp_path / "other.png"
    Image.new("L", (32, 32), 0).save(other)  # 全黑,结构完全不同
    assert not color_consistency_check(sk, other)
    with pytest.raises(SketchStoryboardError):
        color_consistency_check(tmp_path / "missing.png", col)


# ---- director assistant ----

def test_audit_progress_and_suggestions():
    episodes = [
        EpisodeState(
            episode_id="e1",
            shots=[
                ShotState(index=1, status="done", passed=True),
                ShotState(index=2, status="done", passed=True),
                ShotState(index=3, status="rework", passed=False, diagnosis="光照"),
            ],
        )
    ]
    result = audit_production(episodes)
    assert result.progress_pct == pytest.approx(66.7, abs=0.1)
    assert any("未通过" in c for c in result.completeness)
    assert any("一次只改一个变量" in s for s in result.suggestions)


def test_audit_empty_episode():
    result = audit_production([EpisodeState(episode_id="e1")])
    assert result.progress_pct == 0.0
    assert any("无镜头" in c for c in result.completeness)


def test_audit_all_done():
    episodes = [
        EpisodeState(
            episode_id="e1",
            shots=[ShotState(index=i, status="done", passed=True) for i in range(5)],
        )
    ]
    result = audit_production(episodes)
    assert result.progress_pct == 100.0
    assert result.summary.startswith("5/5")
