"""Unit tests for explainer.visual_plan capability, rhythm-driven visual planning and highlight timing error < 200ms."""

import pytest
from pathlib import Path

from hevi.capabilities import get
from hevi.explainer.script import create_oral_script
from hevi.explainer.visual_plan import (
    SUPPORTED_TRANSITIONS,
    build_visual_plan,
    register_explainer_visual_plan_capability,
)
from hevi.explainer.voice import build_voiceover_package


@pytest.fixture(autouse=True)
def ensure_capability():
    register_explainer_visual_plan_capability()


def test_visual_plan_rhythm_and_highlight_timing_error(tmp_path: Path):
    article = (
        "量子力学是研究微观粒子运动规律的物理学分支。\n\n"
        "它的核心特征包括波粒二象性与量子纠缠效应。\n\n"
        "在量子计算中，量子比特能够处于0和1的叠加态。"
    )
    script = create_oral_script(article, title="量子力学")
    voice_dir = tmp_path / "voice"
    voiceover = build_voiceover_package(script, voice_dir)

    plan_dir = tmp_path / "plan"
    plan = build_visual_plan(script, voiceover, plan_dir, aspect="16:9")

    assert len(plan.scenes) == len(script.sections)
    assert plan.total_duration_ms > 0
    assert len(plan.all_highlights) > 0

    # 严格校验：高亮时间与词时间戳误差 < 200ms (WEVIDEO_TASK.md 核心硬指标)
    for hl in plan.all_highlights:
        assert hl.diff_from_audio_ms < 200, f"Highlight timing error {hl.diff_from_audio_ms}ms >= 200ms!"
        assert hl.start_ms >= 0
        assert hl.end_ms > hl.start_ms
        assert hl.term != ""


def test_diagram_layer_by_layer_unfolding(tmp_path: Path):
    article = (
        "光合作用的化学反应机制非常严密。\n\n"
        "第一步光反应吸收光能，第二步暗反应固定二氧化碳生成葡萄糖。\n\n"
        "最后释放出维持生物呼吸所必须的氧气。"
    )
    script = create_oral_script(article, title="光合作用")
    voiceover = build_voiceover_package(script, tmp_path / "voice_diag")

    plan = build_visual_plan(script, voiceover, tmp_path / "plan_diag", aspect="16:9")

    # 找到包含流程图逐层展开的场景
    diag_scenes = [s for s in plan.scenes if len(s.diagram_layers) > 1]
    assert len(diag_scenes) >= 1, "At least one scene should contain progressive diagram layers"

    scene = diag_scenes[0]
    layers = scene.diagram_layers
    assert len(layers) >= 2

    # 验证逐层展开的时间单调性与图像真实存在
    for i in range(len(layers)):
        img_p = Path(layers[i].image_path)
        assert img_p.is_file(), f"Diagram layer image {img_p} must exist"
        assert img_p.stat().st_size > 1000, "Image must have valid visual content"
        if i > 0:
            assert layers[i].appear_ms >= layers[i - 1].appear_ms


def test_presenter_layout_switching_and_transitions(tmp_path: Path):
    article = "第一段开头引言。\n\n第二段中间概念。\n\n第三段机制步骤。\n\n第四段总结回顾。"
    script = create_oral_script(article, title="布局测试")
    voiceover = build_voiceover_package(script, tmp_path / "voice_layout")

    plan = build_visual_plan(script, voiceover, tmp_path / "plan_layout")

    layouts = [s.layout for s in plan.scenes]
    assert "presenter_full" in layouts, "Should have presenter full-screen layout"
    assert "presenter_pip" in layouts, "Should have presenter PiP layout"

    for s in plan.scenes:
        assert s.transition_type in SUPPORTED_TRANSITIONS


def test_capability_explainer_visual_plan(tmp_path: Path):
    cap = get("explainer.visual_plan")
    assert cap is not None

    article = "测试统一能力规划输入。\n\n第二段要点。"
    script = create_oral_script(article, title="能力测试")
    voiceover = build_voiceover_package(script, tmp_path / "cap_voice")

    res = cap.render(
        params={
            "script": script.to_dict(),
            "voiceover": voiceover.to_dict(),
        },
        out_dir=tmp_path / "cap_plan",
        duration=10.0,
        aspect="16:9",
        seed=42,
    )

    assert res.duration_s > 0
    assert res.qa["scene_count"] == 2
    assert Path(res.qa["plan_file"]).is_file()
