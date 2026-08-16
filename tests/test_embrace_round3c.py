"""Round 3c(三库二轮对照)测试: story_to_animation + env preflight + story_cli。"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.assembly.story_to_animation_workflow import (
    StoryConfig,
    StoryInput,
    build_story_plan,
    segment_story,
    story_to_animation_workflow,
)
from hevi.ingest.preflight import PreflightReport, check_env

# ---- story_to_animation(手绘日记漫画)----

def test_segment_story_chinese_sentences():
    sentences = segment_story("王生慕道赴崂山。跪求道士收留,初遭拒绝后以死相誓!终获准入观。")
    # 句号/感叹号切分;逗号不切;一句一拍
    assert len(sentences) == 3
    assert "王生慕道赴崂山" in sentences[0]
    assert "以死相誓" in sentences[1]
    assert "终获准入观" in sentences[2]


def test_segment_story_short_sentence_kept():
    sentences = segment_story("第一句很长。短。尾句很长。")
    assert len(sentences) == 3  # 短句也是完整句,独立一拍
    assert sentences[1] == "短。"


def test_build_story_plan_text_mode():
    cfg = StoryConfig(out_path=Path("/o.mp4"), mode="plan", transition="cut")
    plan = build_story_plan(cfg, StoryInput(text="第一句。第二句。"))
    assert len(plan.beats) == 2
    assert plan.beats[0].mode == "reveal"
    assert plan.canvas == (1080, 1440, 30)
    assert "text→bw→color" in plan.composition_hint


def test_build_story_plan_images_mode():
    cfg = StoryConfig(out_path=Path("/o.mp4"), mode="full", transition="page-flip")
    plan = build_story_plan(cfg, StoryInput(images=[Path("a.jpg"), Path("b.jpg")]))
    assert len(plan.beats) == 2
    assert plan.beats[0].page_index == 0
    assert "page-flip" in plan.composition_hint


def test_build_story_plan_bad_args():
    cfg = StoryConfig(out_path=Path("/o.mp4"), mode="nope")
    with pytest.raises(ValueError):
        build_story_plan(cfg, StoryInput(text="x"))
    cfg2 = StoryConfig(out_path=Path("/o.mp4"), transition="bad")
    with pytest.raises(ValueError):
        build_story_plan(cfg2, StoryInput(text="x"))


def test_story_workflow_requires_input(tmp_path):
    res = __import__("asyncio").run(
        story_to_animation_workflow(
            StoryConfig(out_path=tmp_path / "o.mp4"),
            StoryInput(),
            tmp_path,
        )
    )
    assert res["status"] == "failed"


def test_story_workflow_plan(tmp_path):
    res = __import__("asyncio").run(
        story_to_animation_workflow(
            StoryConfig(out_path=tmp_path / "o.mp4", mode="plan"),
            StoryInput(text="山中有道观。一少年求道。"),
            tmp_path,
        )
    )
    assert res["status"] == "completed"
    assert len(res["plan"]["beats"]) == 2
    assert (tmp_path / "story_plan.json").exists()


# ---- env preflight ----

def test_preflight_structure():
    report = check_env()
    assert isinstance(report, PreflightReport)
    assert isinstance(report.can_proceed, bool)
    assert isinstance(report.missing_binaries, list)
    # 本环境必有 av/PIL(依赖),PyAV 抽帧不受 ffmpeg 缺失影响
    assert report.whisper_available is True  # faster-whisper 在依赖里


def test_preflight_local_path_not_blocked_by_ytdlp(monkeypatch):
    def _no_which(name: str) -> None:
        return None

    monkeypatch.setattr("hevi.ingest.preflight.shutil.which", _no_which)
    report = check_env(require_url_tools=False)  # 本地摄入哲学:yt-dlp 缺失不阻断
    assert "yt-dlp" in report.missing_binaries
    assert report.can_proceed is False  # ffmpeg/ffprobe 也缺 → 阻断(都依赖系统工具)


def test_preflight_to_dict_and_save(tmp_path):
    report = check_env()
    d = report.to_dict()
    assert "can_proceed" in d
    report.save(tmp_path / "preflight.json")
    assert (tmp_path / "preflight.json").exists()


# ---- story_cli ----

def test_story_cli_plan(tmp_path, capsys):
    from hevi.skills.story_cli import main

    rc = main([
        "--text", "一句故事。",
        "--mode", "plan",
        "--out-dir", str(tmp_path),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "beats: 1" in out
