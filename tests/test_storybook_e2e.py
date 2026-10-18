"""End-to-End integration test for complete storybook workflow (3 章节原创绘本全流程端到端真实渲染).

验收指标：
1. 3 章节原创故事 (9 个镜头)
2. 自审轮 (storyplan.critique)
3. 漫画格分镜表 (storyboard.preview_sheet)
4. 水彩手绘动画 + 5 种绘本转场 (transitions.storybook: page_flip, wet_brush, torn_paper, pencil_sketch, watercolor_bloom)
5. 本地配音 + 中英双语字幕 + BGM 自动避让与留白 (storybook.voice_align)
6. 最终交付 MP4 时长 ≥ 30 秒 (ffprobe 验证)
7. 字幕与音轨逐句对齐误差 < 150ms 测试通过。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from hevi.storyplan.storybook_pipeline import (
    create_three_chapter_storybook,
    run_storybook_e2e_pipeline,
)


def test_three_chapter_story_structure():
    """验证 3 章节原创故事数据结构与多角色台词规范。"""
    plan, script_lines, shot_defs = create_three_chapter_storybook()
    assert plan.title == "小狐狸与微光森林的奇迹"
    assert len(script_lines) == 9
    assert len(shot_defs) == 9

    roles = {line.speaker_role for line in script_lines}
    assert "narrator" in roles
    assert "fox" in roles
    assert "bear" in roles
    assert "flower" in roles

    # 包含章节间的安静留白标记
    quiet_breaks = [line for line in script_lines if line.is_quiet_break]
    assert len(quiet_breaks) >= 2


@pytest.mark.slow
def test_storybook_e2e_full_pipeline_render_and_verification(tmp_path: Path):
    """运行完整端到端管线真实渲染（禁止 mock），验证时长 ≥ 30 秒及对齐指标。"""
    out_dir = tmp_path / "storybook_delivery"

    # 执行端到端管线
    summary = run_storybook_e2e_pipeline(out_dir, seed=2026)

    # 1. 验证最终交付 MP4 真实生成
    final_mp4 = Path(summary["final_mp4"])
    assert final_mp4.is_file()
    assert final_mp4.stat().st_size > 500000  # 文件大小真实

    # 2. ffprobe 严格检验视频时长 ≥ 30 秒
    cmd_probe = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(final_mp4),
    ]
    real_duration = float(subprocess.check_output(cmd_probe).decode().strip())
    assert real_duration >= 30.0, f"Delivered video duration {real_duration}s < 30.0s"

    # 3. 验证漫画格分镜预览图
    sheet_png = Path(summary["sheet_png"])
    assert sheet_png.is_file()
    with Image.open(sheet_png) as im:
        assert im.size == (1920, 1080)

    # 4. 验证中英双语字幕文件与音轨逐句对齐（误差 < 150ms）
    srt_path = Path(summary["subtitles_srt"])
    assert srt_path.is_file()
    srt_content = srt_path.read_text(encoding="utf-8")
    assert "小草尖上有一颗圆滚滚的种子" in srt_content
    assert "Look! On the tip of the grass" in srt_content
    assert summary["max_alignment_error_ms"] < 150.0

    # 5. 验证自审报告与自检门通过
    assert summary["critique_score"] >= 80.0
    revised_plan_file = out_dir / "revised_plan.json"
    assert revised_plan_file.is_file()

    # 6. 验证母带音频与避让混音
    master_wav = Path(summary["master_wav"])
    assert master_wav.is_file()
    assert summary["transitions_count"] == 8
