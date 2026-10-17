"""Unit tests for Explainer State Machine, Voice Approval Gate and Incremental Recompute."""

import pytest
from pathlib import Path

from hevi.explainer.script import create_oral_script
from hevi.explainer.state_machine import (
    ApprovalRequiredError,
    ExplainerProject,
    PipelineState,
    StateTransitionError,
)


def test_voice_approval_gate_blocks_plan_and_render(tmp_path: Path):
    article = "第一段关于黑洞的简介。\n\n第二段黑洞视界的物理特性解释。"
    script = create_oral_script(article, title="黑洞探索")
    proj = ExplainerProject(project_id="p_gate_01", script=script)

    assert proj.state == PipelineState.SCRIPT
    assert proj.voice_approved is False

    # 1. 尝试跳过配音直接进入视觉规划，必须被确认闸拦截
    with pytest.raises(ApprovalRequiredError, match="voice has not been approved"):
        proj.advance_to_plan({"scenes": []})

    # 2. 合成配音但未人工/闸门确认，依旧拦截
    proj.synthesize_voice(out_dir=tmp_path / "voice_01")
    assert proj.voiceover_package is not None
    assert proj.voice_approved is False

    with pytest.raises(ApprovalRequiredError, match="voice has not been approved"):
        proj.advance_to_plan({"scenes": []})

    # 3. 执行确认，成功解锁后续流程
    proj.approve_voice()
    assert proj.state == PipelineState.VOICE_APPROVED
    assert proj.voice_approved is True

    proj.advance_to_plan({"scenes": [{"id": "scene_0"}]})
    assert proj.state == PipelineState.PLAN

    proj.advance_to_render({"mp4_path": "/fake/video.mp4"})
    assert proj.state == PipelineState.RENDER


def test_state_rollback_and_approval_revocation(tmp_path: Path):
    article = "段落一测试。\n\n段落二测试。"
    script = create_oral_script(article, title="回退测试")
    proj = ExplainerProject(project_id="p_rollback_01", script=script)

    proj.synthesize_voice(out_dir=tmp_path / "voice_02")
    proj.approve_voice()
    proj.advance_to_plan({"scenes": ["s1"]})
    assert proj.state == PipelineState.PLAN

    # 回退至 SCRIPT
    proj.rollback_to(PipelineState.SCRIPT)
    assert proj.state == PipelineState.SCRIPT
    assert proj.voice_approved is False
    assert proj.visual_plan_data is None

    # 再次未确认直接进 plan 必须被拦
    with pytest.raises(ApprovalRequiredError):
        proj.advance_to_plan({"scenes": ["s1"]})


def test_incremental_partial_recomputation(tmp_path: Path):
    article = (
        "第一段：地球是太阳系从内向外的第三颗行星。\n\n"
        "第二段：火星表面覆盖着大量氧化铁呈现红色。\n\n"
        "第三段：木星是太阳系中体积最大的气态巨行星。"
    )
    script = create_oral_script(article, title="行星对比")
    proj = ExplainerProject(project_id="p_inc_01", script=script)

    # 初始全量合成
    pkg1 = proj.synthesize_voice(out_dir=tmp_path / "voice_inc")
    assert len(pkg1.sections) == 3
    sec0_art = pkg1.sections["sec_00"]
    sec1_art = pkg1.sections["sec_01"]
    sec2_art = pkg1.sections["sec_02"]

    # 只修改第二段（index 1），第一段和第三段文本完全不变
    diff = proj.update_script_section(
        section_index=1,
        out_dir=tmp_path / "voice_inc",
        new_oral_text="比方说，火星这颗红色星球的大气非常稀薄，大部分由二氧化碳组成。",
    )

    assert diff["modified_ids"] == ["sec_01"]
    assert "sec_00" in diff["unchanged_ids"]
    assert "sec_02" in diff["unchanged_ids"]

    # 校验增量重算效果：
    # sec_00 与 sec_02 应直接命中缓存，保持原音频文件和 sha256；
    # sec_01 必须生成了新的 text_hash 与不同的 audio 产物
    pkg2 = proj.voiceover_package
    assert pkg2 is not None
    assert pkg2.sections["sec_00"].sha256 == sec0_art.sha256
    assert pkg2.sections["sec_00"].audio_path == sec0_art.audio_path
    assert pkg2.sections["sec_02"].sha256 == sec2_art.sha256
    assert pkg2.sections["sec_02"].audio_path == sec2_art.audio_path

    assert pkg2.sections["sec_01"].text_hash != sec1_art.text_hash
    assert Path(pkg2.full_audio_path).is_file()

    # 状态必须重置回 SCRIPT 且 voice_approved=False
    assert proj.state == PipelineState.SCRIPT
    assert proj.voice_approved is False
