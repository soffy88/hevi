"""Unit tests for Comic Narration line and pipeline.

Tests run fast using the fake keyframe engine and no heavy ML weights.  The
full-pipeline test disables the OCR gate (``qa_ocr=False``) for speed; the OCR
similarity primitive itself is unit-tested directly.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import cv2
import numpy as np
import pytest

from hevi.layer4_legacy.comicnarr.omodul_impl.comicnarr_pipeline import (
    comic_narration_workflow,
)
from hevi.layer4_legacy.comicnarr.oprim_impl.contracts import ComicScene, ComicScript
from hevi.layer4_legacy.comicnarr.oprim_impl.ken_burns import (
    CAMERA_MOVES,
    build_ken_burns_filter,
)
from hevi.layer4_legacy.comicnarr.oprim_impl.postprocess import (
    apply_style_postprocess,
    is_grayscale,
)
from hevi.layer4_legacy.comicnarr.oprim_impl.subtitle import (
    build_comic_ass,
    build_srt_content,
    format_ass_time,
    format_srt_time,
    wrap_subtitle_text,
)
from hevi.layer4_legacy.comicnarr.oprim_impl.subtitle_ocr import text_similarity
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
from hevi.layer4_legacy.keyframe.oprim_impl.style_presets import (
    DEFAULT_STYLE,
    STYLE_PRESETS,
    get_style_preset,
    list_style_presets,
)
from hevi.layer4_legacy.zerolines.oprim_impl.specs import (
    LINE_SPECS,
    ZERO_LINES,
    ZeroLineRequest,
)
from hevi.studio.production_catalog import CANONICAL_LINES

_TERMINAL = "。！？…!?"


def _style_line(ass_text: str) -> list[str]:
    for line in ass_text.splitlines():
        if line.startswith("Style: ComicSub"):
            return [p.strip() for p in line[len("Style: ") :].split(",")]
    raise AssertionError("no ComicSub style line found")


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


def test_shared_style_presets() -> None:
    assert DEFAULT_STYLE == "guofeng_anime"
    assert set(list_style_presets()) >= {"comic_color", "manga_bw", "guofeng_anime"}

    required_fields = (
        "style_tokens",
        "negative_prompt",
        "subtitle_style",
        "bgm_mood",
        "transition",
        "postprocess",
    )
    for name in ("comic_color", "manga_bw", "guofeng_anime"):
        preset = STYLE_PRESETS[name]
        for field in required_fields:
            assert getattr(preset, field), f"{name}.{field} must be non-empty"

    # guofeng_anime is non-photoreal and is the comic_narration default.
    guofeng = STYLE_PRESETS["guofeng_anime"]
    for token in ("photorealistic", "photo", "3d", "realistic"):
        assert token in guofeng.negative_prompt
    assert "comic_narration" in guofeng.default_for

    # comicnarr templates re-export the exact shared objects.
    assert COMIC_STYLES["guofeng_anime"] is STYLE_PRESETS["guofeng_anime"]
    assert get_style_template("unknown-style").name == DEFAULT_STYLE
    assert get_style_preset("").name == DEFAULT_STYLE


def test_script_sentence_split_and_char_limits() -> None:
    long_text = (
        "这是一段非常非常长的文字，它超过了三十个字符的长度，我们需要把它切分成短句子。"
        "第二句也很长，包含了逗号和各种分词标志。最后一句。"
    )
    splits = _split_text_to_sentences(long_text, max_chars=30)
    assert len(splits) >= 3
    for s in splits:
        assert len(s) <= 30
        assert s[-1] in _TERMINAL

    # No character is dropped (punctuation normalisation aside).
    strip_punct = lambda t: re.sub(r"[^\w\u4e00-\u9fff]", "", t)  # noqa: E731
    assert "".join(strip_punct(s) for s in splits) == strip_punct(long_text)

    script, channel = generate_comic_script(topic="为什么猫总爱把东西推下桌？")
    assert channel == "deterministic_rule_fallback"
    assert 6 <= len(script.scenes) <= 14
    for sc in script.scenes:
        assert len(sc.narration) <= 30
        assert sc.narration[-1] in _TERMINAL
        assert sc.visual_desc
    assert script.character_desc_zh
    assert script.character_desc_en
    assert script.character_tokens

    # The third acceptance story (guofeng / Three Kingdoms) is available.
    script3, _ = generate_comic_script(topic="三国演义·草船借箭")
    assert 6 <= len(script3.scenes) <= 14
    assert "诸葛" in script3.character_desc_zh


def test_texts_mode_roundtrip() -> None:
    lines = [
        "第一句测试内容。",
        "第二句测试内容。",
        "第三句测试内容。",
        "第四句测试内容。",
        "第五句测试内容。",
        "第六句测试内容。",
    ]
    script, channel = generate_comic_script(topic="", raw_texts=lines)
    assert channel == "user_input_texts"
    assert len(script.scenes) == 6
    joined = "".join(sc.narration for sc in script.scenes)
    assert joined == "".join(lines)
    for sc in script.scenes:
        assert sc.narration[-1] in _TERMINAL


def test_prompt_builder_and_style_templates() -> None:
    style_color = get_style_template("comic_color")
    assert "vibrant" in style_color.style_tokens or "comic" in style_color.style_tokens
    assert style_color.bgm_mood == "bright"

    style_bw = get_style_template("manga_bw")
    assert "black and white" in style_bw.style_tokens
    assert "color" in style_bw.negative_prompt

    style_guofeng = get_style_template("guofeng_anime")
    assert style_guofeng.postprocess == "none"
    assert "anime" in style_guofeng.style_tokens.lower()

    # Protagonist present -> character tokens appended after the scene.
    prompt_en, neg = build_scene_prompt(
        visual_desc_zh="一只胖乎乎的橘猫坐在书桌边，盯着水杯",
        character_desc_en="chubby ginger cat",
        style=style_color,
        character_tokens=("橘猫",),
        use_llm=False,
    )
    assert "chubby ginger cat" in prompt_en
    assert style_color.style_tokens in prompt_en
    assert prompt_en.index("glass") < prompt_en.index("chubby ginger cat")
    assert neg == style_color.negative_prompt

    # Protagonist NOT in the scene -> character tokens must be omitted.
    prompt_no_char, _ = build_scene_prompt(
        visual_desc_zh="繁华古朴的明代宫廷殿堂，官员正在呈送名贵蟋蟀",
        character_desc_en="young scholar in cyan Hanfu robe",
        style=style_bw,
        character_tokens=("书生", "成名"),
        use_llm=False,
    )
    assert "scholar" not in prompt_no_char
    assert "cricket" in prompt_no_char

    # No colour-bleeding identity token in the curated fallback characters.
    from hevi.layer4_legacy.comicnarr.oskill_impl.script_planner import FALLBACK_SCRIPTS

    for tmpl in FALLBACK_SCRIPTS.values():
        assert "emerald" not in tmpl["character_desc_en"].lower()


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
    style_fields = _style_line(ass_bottom)
    font_size = int(style_fields[2])
    bold = style_fields[7]
    border_style = int(style_fields[15])
    outline = int(style_fields[16])
    assert font_size >= 52
    assert bold == "-1"  # bold
    assert border_style == 1
    assert outline >= 4

    # Long captions must be wrapped with an explicit \N and lose no characters.
    long_text = "你一定见过这样的场景：猫咪坐在桌边，盯着杯子，然后伸出一只小爪子。"
    ass_long = build_comic_ass(cues=[(0.0, 5.0, long_text)], bubble=False)
    assert "\\N" in ass_long
    assert wrap_subtitle_text(long_text).replace("\\N", "") == long_text

    # manga bubble: white text on a black box (contrasting).
    ass_bubble = build_comic_ass(cues=cues, style_name="manga_bw", bubble=True)
    bf = _style_line(ass_bubble)
    assert bf[3] == "&H00FFFFFF"  # primary (white)
    assert bf[5] == "&H00000000"  # outline / box (black)
    assert int(bf[15]) == 3

    # comic_color bubble: dark text on a coloured box (contrasting).
    cf = _style_line(build_comic_ass(cues=cues, style_name="comic_color", bubble=True))
    assert cf[3] != cf[5]


def test_postprocess_manga_bw(tmp_path: Path) -> None:
    # A saturated colour image must become truly grayscale.
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    img[:, :32] = (0, 0, 255)  # red
    img[:, 32:] = (0, 255, 0)  # green
    p = tmp_path / "color.png"
    cv2.imwrite(str(p), img)
    assert not is_grayscale(cv2.imread(str(p)))

    apply_style_postprocess(p, "manga_bw")
    out = cv2.imread(str(p))
    assert is_grayscale(out)
    # The pass must preserve shape and not blank the image.
    assert out.shape == (64, 64, 3)
    assert out.std() > 1.0

    # "none" is a no-op.
    apply_style_postprocess(p, "none")


def test_ocr_text_similarity() -> None:
    assert text_similarity("猫咪看着杯子。", "猫咪看着杯子。") == 1.0
    assert text_similarity("猫咪看着杯子", "猫咪盯着杯子") >= 0.6
    assert text_similarity("", "任意文字") == 0.0
    # A fully invisible subtitle (empty OCR) is not readable.
    assert text_similarity("", "猫咪看着杯子。") < 0.6


def test_fake_engine_resolution_and_generation(tmp_path: Path) -> None:
    engine = resolve_keyframe_engine("fake")
    assert engine.name == "fake"
    assert engine.available()

    out_file = tmp_path / "test_fake.png"
    res = engine.generate("test prompt", width=512, height=512, seed=123, output_path=out_file)
    assert res.path.is_file()
    assert res.engine == "fake"
    assert res.seed == 123


def test_comicnarr_workflow_with_fake_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Mock the (heavy) OpenCLIP candidate scorer; this is a unit test of the
    # pipeline wiring, not of CLIP.  The real scorer is exercised by the E2E.
    def _fast_score(image_path, *, prompt_en=None):
        return {
            "composite_score": 0.5,
            "clip_score": 0.5,
            "sharpness": 0.5,
            "exposure": 0.5,
            "bad_image": False,
            "bad_reason": "ok",
        }

    monkeypatch.setattr(
        "hevi.layer4_legacy.comicnarr.omodul_impl.comicnarr_pipeline.score_keyframe",
        _fast_score,
    )

    input_data = {
        "texts": [
            "第一句测试内容。",
            "第二句测试内容。",
            "第三句测试内容。",
            "第四句测试内容。",
            "第五句测试内容。",
            "第六句测试内容。",
        ],
        "style": "comic_color",
        "keyframe_engine": "fake",
        "base_seed": 42,
        "width": 360,
        "height": 640,
        "fps": 12,
        "qa_ocr": False,
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

    # Verify script.json keeps the full text (no truncation).
    script_data = json.loads(Path(result["script_path"]).read_text(encoding="utf-8"))
    assert len(script_data["scenes"]) == 6
    joined = "".join(sc["narration"] for sc in script_data["scenes"])
    assert joined == "".join(input_data["texts"])

    # QA motion must be measured *within* a shot, not across shots.
    qa = json.loads(Path(result["qa_path"]).read_text(encoding="utf-8"))
    assert "within_shot_differences" in qa["motion"]
    assert qa["motion"]["mean_within_shot_difference"] > 1.0
    assert qa["subtitle_readability"]["enabled"] is False

    # Verify breakpoint resume: second run reuses generated frames without error
    result2 = comic_narration_workflow({}, input_data, tmp_path)
    assert result2["status"] == result["status"]
