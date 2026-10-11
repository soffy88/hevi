"""Unit tests for Comic Narration line and pipeline.

Tests run fast (<15s) using fake keyframe engine without heavy ML weights.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hevi.layer4_legacy.comicnarr.omodul_impl.comicnarr_pipeline import (
    comic_narration_workflow,
)
from hevi.layer4_legacy.comicnarr.oprim_impl.contracts import ComicScene, ComicScript
from hevi.layer4_legacy.comicnarr.oprim_impl.ken_burns import (
    CAMERA_MOVES,
    build_ken_burns_filter,
)
from hevi.layer4_legacy.comicnarr.oprim_impl.subtitle import (
    build_comic_ass,
    build_srt_content,
    format_ass_time,
    format_srt_time,
)
from hevi.layer4_legacy.comicnarr.oprim_impl.templates import (
    COMIC_STYLES,
    get_style_template,
)
from hevi.layer4_legacy.comicnarr.oskill_impl.prompt_builder import (
    build_scene_prompt,
)
from hevi.layer4_legacy.comicnarr.oskill_impl.script_planner import (
    _split_text_to_sentences,
    generate_comic_script,
)
from hevi.layer4_legacy.keyframe.oprim_impl.registry import resolve_keyframe_engine
from hevi.layer4_legacy.zerolines.oprim_impl.specs import (
    LINE_SPECS,
    ZERO_LINES,
    ZeroLineRequest,
)
from hevi.studio.production_catalog import CANONICAL_LINES


def test_line_registration() -> None:
    assert "comic_narration" in ZERO_LINES
    assert "comic_narration" in LINE_SPECS
    assert "comic_narration" in CANONICAL_LINES

    # Topic input is valid
    req_topic = ZeroLineRequest("comic_narration", topic="测试主题")
    assert not req_topic.validate()

    # Texts input is also valid
    req_texts = ZeroLineRequest("comic_narration", texts=("第一句。", "第二句。"))
    assert not req_texts.validate()

    # Empty input fails validation
    req_empty = ZeroLineRequest("comic_narration")
    assert req_empty.validate()


def test_script_sentence_split_and_char_limits() -> None:
    long_text = "这是一段非常非常长的文字，它超过了三十个字符的长度，我们需要把它切分成短句子。第二句也很长，包含了逗号和各种分词标志。最后一句。"
    splits = _split_text_to_sentences(long_text, max_chars=30)
    assert len(splits) >= 3
    for s in splits:
        assert len(s) <= 30

    script, channel = generate_comic_script(topic="为什么猫总爱把东西推下桌？")
    assert 6 <= len(script.scenes) <= 14
    for sc in script.scenes:
        assert len(sc.narration) <= 30
        assert sc.visual_desc
    assert script.character_desc_zh
    assert script.character_desc_en


def test_prompt_builder_and_style_templates() -> None:
    style_color = get_style_template("comic_color")
    assert "vibrant" in style_color.style_tokens or "comic" in style_color.style_tokens
    assert style_color.bgm_mood == "bright"

    style_bw = get_style_template("manga_bw")
    assert "black and white" in style_bw.style_tokens
    assert "color" in style_bw.negative_prompt

    prompt_en, neg = build_scene_prompt(
        visual_desc_zh="橘猫在书桌上推翻了水杯",
        character_desc_en="chubby ginger cat",
        style=style_color,
        use_llm=False,
    )
    assert "chubby ginger cat" in prompt_en
    assert style_color.style_tokens in prompt_en
    assert neg == style_color.negative_prompt


def test_ken_burns_camera_filters() -> None:
    for move in CAMERA_MOVES:
        vf = build_ken_burns_filter(move=move, duration=4.0, width=1080, height=1920, fps=25)
        assert "crop=1080:1920" in vf
        assert "fps=25" in vf
        assert "yuv420p" in vf
        if move in ("push", "pull"):
            assert "eval=frame" in vf
        elif move in ("pan_l", "pan_r"):
            assert "force_original_aspect_ratio=increase" in vf


def test_subtitle_generation() -> None:
    cues = [
        (0.0, 3.25, "猫咪看着杯子。"),
        (3.25, 7.1, "然后轻轻伸出了爪子。"),
    ]
    srt = build_srt_content(cues=cues)
    assert "00:00:00,000 --> 00:00:03,250" in srt
    assert "猫咪看着杯子。" in srt

    ass_bottom = build_comic_ass(cues=cues, width=1080, height=1920, bubble=False)
    assert "[Script Info]" in ass_bottom
    assert "Dialogue: 0,0:00:00.00,0:00:03.25,ComicSub" in ass_bottom

    ass_bubble = build_comic_ass(cues=cues, width=1080, height=1920, bubble=True)
    assert "ComicSub,WenQuanYi Zen Hei" in ass_bubble


def test_fake_engine_resolution_and_generation(tmp_path: Path) -> None:
    engine = resolve_keyframe_engine("fake")
    assert engine.name == "fake"
    assert engine.available()

    out_file = tmp_path / "test_fake.png"
    res = engine.generate("test prompt", width=512, height=512, seed=123, output_path=out_file)
    assert res.path.is_file()
    assert res.engine == "fake"
    assert res.seed == 123


def test_comicnarr_workflow_with_fake_engine(tmp_path: Path) -> None:
    input_data = {
        "topic": "为什么猫总爱把东西推下桌",
        "style": "comic_color",
        "keyframe_engine": "fake",
        "base_seed": 42,
        "width": 1080,
        "height": 1920,
        "fps": 25,
    }
    result = comic_narration_workflow({}, input_data, tmp_path)
    assert Path(result["final_mp4"]).is_file()
    assert Path(result["script_path"]).is_file()
    assert Path(result["record_path"]).is_file()
    assert Path(result["qa_path"]).is_file()
    assert Path(result["contact_sheet"]).is_file()
    assert Path(result["subtitles_path"]).is_file()

    # Check frames directory contains keyframes and loser candidates
    frames = list((tmp_path / "frames").glob("*.png"))
    assert len(frames) >= 10  # Winners + losers

    # Verify script.json
    script_data = json.loads(Path(result["script_path"]).read_text(encoding="utf-8"))
    assert len(script_data["scenes"]) >= 6

    # Verify breakpoint resume: second run reuses generated frames without error
    result2 = comic_narration_workflow({}, input_data, tmp_path)
    assert result2["status"] == result["status"]
