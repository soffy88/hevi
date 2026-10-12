"""Unit tests for DRAMAKEY pipeline (fast, using fake engine, <30s runtime).

Covers:
- Keyframe engine registry and resolution
- Prompt translation and domain fallback
- Novel chapter splitting (chapter headings & length chunking)
- Character alias fusing and dossier creation
- Shot budgeting for target duration
- Image quality scoring and bad-image detection
- Face consistency gate branches
- End-to-end rendering pipeline with fake engine
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from hevi.layer4_legacy.keyframe.omodul_impl.video_render import (
    RenderConfig,
    render_dramakey_pipeline,
)
from hevi.layer4_legacy.keyframe.oprim_impl.character_card import CharacterCard
from hevi.layer4_legacy.keyframe.oprim_impl.cloud_stub_engine import CloudStubKeyframeEngine
from hevi.layer4_legacy.keyframe.oprim_impl.contracts import KeyframeResult
from hevi.layer4_legacy.keyframe.oprim_impl.face_gate import (
    compute_face_cosine,
    verify_character_face,
)
from hevi.layer4_legacy.keyframe.oprim_impl.fake_engine import FakeKeyframeEngine
from hevi.layer4_legacy.keyframe.oprim_impl.image_score import (
    compute_exposure_score,
    compute_laplacian_sharpness,
    detect_bad_image,
    score_keyframe,
)
from hevi.layer4_legacy.keyframe.oprim_impl.registry import (
    get_engine,
    register_engine,
    resolve_keyframe_engine,
)
from hevi.layer4_legacy.keyframe.oskill_impl.prompt_translator import zh_shot_to_sd_prompt
from hevi.layer4_legacy.script2video.oprim_impl.character_fuse import (
    are_aliases,
    fuse_characters_to_cards,
)
from hevi.layer4_legacy.script2video.oprim_impl.novel_split import split_chapters
from hevi.layer4_legacy.script2video.oskill_impl.shot_budget import shot_budget_for_duration
from hevi.production.novel2video_workflow import (
    Novel2VideoConfig,
    Novel2VideoInput,
    novel2video_workflow,
)


def test_engine_registry_and_resolution() -> None:
    fake_engine = get_engine("fake")
    assert isinstance(fake_engine, FakeKeyframeEngine)
    assert fake_engine.name == "fake"
    assert fake_engine.available() is True

    # Cloud stub is unavailable by default
    cloud_engine = get_engine("cloud_stub")
    assert isinstance(cloud_engine, CloudStubKeyframeEngine)
    assert cloud_engine.available() is False

    # Resolution via dict or default
    resolved_fake = resolve_keyframe_engine({"engine": "fake"})
    assert resolved_fake.name == "fake"

    # Register custom engine
    register_engine("custom_fake", engine=FakeKeyframeEngine)
    assert get_engine("custom_fake").name == "fake"


def test_fake_engine_generation(tmp_path: Path) -> None:
    engine = FakeKeyframeEngine()
    out_file = tmp_path / "test_fake.png"
    result = engine.generate(
        "an ancient Taoist master",
        width=256,
        height=256,
        seed=777,
        output_path=out_file,
    )
    assert isinstance(result, KeyframeResult)
    assert result.path.is_file()
    assert result.seed == 777
    assert result.width == 256
    assert result.height == 256
    assert result.engine == "fake"


def test_prompt_translation_rule_fallback() -> None:
    shot = {
        "visual_desc": "王生在崂山深处拜见老道长，月夜烛光",
        "visible_chars": ["王生", "老道长"],
    }
    cards = [
        CharacterCard(
            id="wang_sheng",
            name="王生",
            appearance_en_tokens="young Chinese scholar in Hanfu",
        ),
        CharacterCard(
            id="lao_dao_zhang",
            name="老道长",
            appearance_en_tokens="venerable Taoist master with long white beard",
        ),
    ]

    prompt_en, neg = zh_shot_to_sd_prompt(shot, character_cards=cards)
    assert "young Chinese scholar in Hanfu" in prompt_en
    assert "venerable Taoist master with long white beard" in prompt_en
    assert "mountains" in prompt_en or "Taoist" in prompt_en or "moonlit" in prompt_en
    assert "blurry" in neg


def test_split_chapters_headings_and_subdivision() -> None:
    text = (
        "第1回 崂山问道\n王生少慕仙术，往登崂山。\n\n"
        "第二章 纸月照酒\n师尊剪纸如镜，悬于壁上，光照一室。\n\n"
        "第三节 穿壁功成\n老道曰：归宜洁持，否则不灵。"
    )
    chapters = split_chapters(text, max_chapter_len=500)
    assert len(chapters) == 3
    assert "第1回" in chapters[0][0]
    assert "第二章" in chapters[1][0]
    assert "第三节" in chapters[2][0]

    # Test long chapter subdivision
    long_text = "第一回 漫漫求索\n" + ("仙山无尽岁月长。" * 100)
    subdivided = split_chapters(long_text, max_chapter_len=150)
    assert len(subdivided) > 1
    assert "第1节" in subdivided[0][0]


def test_character_fusion_and_alias_matching() -> None:
    assert are_aliases("王生", "王七") is True
    assert are_aliases("王生", "书生") is True
    assert are_aliases("老道长", "师父") is True
    assert are_aliases("王生", "老道长") is False

    raw_characters = [
        {"name": "王生", "description": "好仙术，携书箱"},
        {"name": "王七", "description": "故家子，排行第七"},
        {"name": "书生", "description": "年轻秀才"},
        {"name": "老道长", "description": "白须垂胸，仙风道骨"},
    ]
    cards = fuse_characters_to_cards(raw_characters)
    assert len(cards) == 2

    wang_card = next(c for c in cards if c.name == "王生")
    assert "王七" in wang_card.aliases or "书生" in wang_card.aliases
    assert wang_card.gender == "male"
    assert wang_card.age_band == "young"

    dao_card = next(c for c in cards if c.name == "老道长")
    assert dao_card.age_band == "elderly"
    assert "venerable" in dao_card.appearance_en_tokens


def test_shot_budget_for_duration() -> None:
    assert shot_budget_for_duration(30.0) == 8
    assert shot_budget_for_duration(60.0) == 15
    assert shot_budget_for_duration(90.0) == 22
    assert shot_budget_for_duration(0.0) == 1


def test_bad_image_detection_and_scoring(tmp_path: Path) -> None:
    # 1. Solid black image
    black_path = tmp_path / "black.png"
    Image.new("RGB", (64, 64), color=(0, 0, 0)).save(black_path)
    is_bad, reason = detect_bad_image(black_path)
    assert is_bad is True
    assert reason in ("solid_color", "all_black")

    # 2. Solid color image
    solid_path = tmp_path / "solid_red.png"
    Image.new("RGB", (64, 64), color=(255, 0, 0)).save(solid_path)
    is_bad, reason = detect_bad_image(solid_path)
    assert is_bad is True
    assert reason == "solid_color"

    # 3. Normal textured image
    normal_path = tmp_path / "normal.png"
    arr = np.random.randint(0, 255, (64, 64, 3), dtype=np.uint8)
    Image.fromarray(arr).save(normal_path)
    is_bad, _ = detect_bad_image(normal_path)
    assert is_bad is False

    sharpness = compute_laplacian_sharpness(normal_path)
    assert sharpness > 0.0
    exposure = compute_exposure_score(normal_path)
    assert exposure > 0.0

    score = score_keyframe(normal_path, prompt_en="random noise")
    assert score["bad_image"] is False
    assert score["composite_score"] > 0.0


def test_face_gate_cosine_and_verification() -> None:
    emb1 = np.ones(128, dtype=np.float32)
    emb2 = np.ones(128, dtype=np.float32)
    emb_diff = -np.ones(128, dtype=np.float32)

    cos_same = compute_face_cosine(emb1, embedding_b=emb2)
    assert pytest.approx(cos_same, rel=1e-3) == 1.0

    cos_opp = compute_face_cosine(emb1, embedding_b=emb_diff)
    assert pytest.approx(cos_opp, rel=1e-3) == -1.0

    # Verification with no reference embedding always passes
    passed, sim, det = verify_character_face(
        "/dev/null", ref_embedding=None, threshold=0.35
    )
    assert passed is True
    assert det is False


def test_render_dramakey_pipeline_fake_engine(tmp_path: Path) -> None:
    shots = [
        {
            "idx": 0,
            "text": "王生至崂山，见一观宇甚幽。",
            "visual_desc": "青年书生站在道观门前",
            "visible_chars": ["王生"],
            "camera_move": "push",
        },
        {
            "idx": 1,
            "text": "老道长端坐蒲团，神态肃穆。",
            "visual_desc": "白发长须老道士端坐道观大殿",
            "visible_chars": ["老道长"],
            "camera_move": "pan_r",
        },
    ]

    cfg = RenderConfig(
        engine="fake",
        target_width=360,
        target_height=640,
        fps=15,
        kf_width=256,
        kf_height=256,
        steps=1,
        enable_tts=True,
        enable_subtitles=True,
    )

    result = render_dramakey_pipeline(
        shots=shots,
        output_dir=tmp_path / "render_run",
        config=cfg,
    )

    final_mp4 = Path(result["final_mp4"])
    assert final_mp4.is_file()
    assert final_mp4.stat().st_size > 10_000

    qa_report = result["qa_report"]
    assert len(qa_report["shot_records"]) == 2
    assert Path(result["characters_path"]).is_file()
    assert Path(result["qa_path"]).is_file()
    assert Path(result["record_path"]).is_file()
    assert Path(result["contact_sheet"]).is_file()

    # Check keyframes folder has loser candidate as well
    kf_dir = tmp_path / "render_run" / "keyframes"
    losers = list(kf_dir.glob("*_loser_*.png"))
    assert len(losers) >= 2


def test_novel2video_workflow_render_flag(tmp_path: Path) -> None:
    text = (
        "第一回 崂山拜师\n"
        "王生邑之故家子也，少慕仙术。闻崂山多仙，负笈往游。\n"
        "登一顶，有观宇甚幽。一道士坐蒲团上，白发垂领，神光爽迈。"
    )

    # 1. render=False should only write report JSON (backward compatibility)
    out_dir_plan = tmp_path / "plan_only"
    res_plan = asyncio.run(
        novel2video_workflow(
            Novel2VideoConfig(render=False),
            Novel2VideoInput(novel_text=text),
            output_dir=out_dir_plan,
        )
    )
    assert res_plan["status"] == "completed"
    assert Path(res_plan["report_path"]).is_file()
    assert "final_mp4" not in res_plan

    # 2. render=True should execute rendering pipeline
    out_dir_render = tmp_path / "rendered"
    res_render = asyncio.run(
        novel2video_workflow(
            Novel2VideoConfig(
                render=True,
                engine="fake",
                target_width=360,
                target_height=640,
                fps=15,
                kf_width=256,
                kf_height=256,
                target_duration_s=8.0,
            ),
            Novel2VideoInput(novel_text=text),
            output_dir=out_dir_render,
        )
    )
    assert Path(res_render["final_mp4"]).is_file()
    assert Path(res_render["qa_path"]).is_file()
    assert Path(res_render["record_path"]).is_file()


def test_subtitle_wrapping_and_safe_margins(tmp_path: Path) -> None:
    import subprocess
    import cv2
    from hevi.layer4_legacy.keyframe.omodul_impl.video_render import split_text_into_cues, _format_ass_time
    from hevi.layer4_legacy.talkcraft.omodul_impl._media import FFMPEG

    long_sentence = "登一高顶，有道观甚幽，老道长坐蒲团上，白发垂领，神光爽迈。"
    cues = split_text_into_cues(long_sentence, start_time=0.0, end_time=6.0, max_chars_per_line=14, max_lines=2)
    assert len(cues) >= 2, "Long sentence must be split into multiple cues"

    for _, _, cue_text in cues:
        lines = cue_text.split("\n")
        assert len(lines) <= 2, f"Each cue must have <= 2 lines, got {len(lines)}"
        for l in lines:
            assert len(l) <= 14, f"Line exceeds 14 chars: {l} (len={len(l)})"

    # Render a 1080x1920 test frame and verify subtitle pixels do not touch left or right edges (>= 6% margin)
    blank_png = tmp_path / "blank.png"
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=1080x1920:d=1", "-vframes", "1", str(blank_png)],
        check=True,
    )

    ass_path = tmp_path / "test_sub.ass"
    ass_events = []
    for st, et, ctext in cues:
        atext = ctext.replace("\n", r"\N")
        ass_events.append(f"Dialogue: 0,{_format_ass_time(st)},{_format_ass_time(et)},Default,,0,0,0,,{atext}")

    ass_content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,WenQuanYi Zen Hei,42,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,70,70,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(ass_events) + "\n"
    ass_path.write_text(ass_content, encoding="utf-8")

    out_png = tmp_path / "rendered_sub.png"
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-i", str(blank_png), "-vf", f"subtitles='{ass_path}'", "-vframes", "1", str(out_png)],
        check=True,
    )

    img = cv2.imread(str(out_png))
    assert img is not None
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    coords = np.column_stack(np.where(gray > 20))
    assert len(coords) > 0, "Subtitles must be rendered and visible"

    min_x = int(coords[:, 1].min())
    max_x = int(coords[:, 1].max())
    margin_left = min_x
    margin_right = w - 1 - max_x

    # Subtitles must not touch edges and maintain >= 6% margin
    assert margin_left >= w * 0.06, f"Left margin {margin_left}px < {w * 0.06}px (6%)"
    assert margin_right >= w * 0.06, f"Right margin {margin_right}px < {w * 0.06}px (6%)"


def test_subject_alignment_and_moon_keyword(tmp_path: Path) -> None:
    from hevi.layer4_legacy.keyframe.oprim_impl.image_score import verify_subject_alignment
    from hevi.layer4_legacy.keyframe.oskill_impl.prompt_translator import zh_shot_to_sd_prompt

    shot_moon = {
        "text": "顷刻之间，纸化为一轮皎洁明月，月华流转，映照整座大殿。",
        "visual_desc": "石壁上的素纸化作一轮巨大的皎洁明亮圆月，柔和纯白月华流转洒满大殿，神奇玄妙",
        "visible_chars": [],
    }
    prompt_en, neg = zh_shot_to_sd_prompt(shot_moon)
    assert "moon" in prompt_en.lower(), f"Prompt must contain moon keyword, got: {prompt_en}"
    assert "person" in neg, "Negative prompt for solo moon shot should exclude person"

    # Test dummy image alignment check
    dummy_img = tmp_path / "dummy_moon.png"
    arr = np.ones((128, 128, 3), dtype=np.uint8) * 180
    Image.fromarray(arr).save(dummy_img)

    align = verify_subject_alignment(
        dummy_img,
        text_zh=shot_moon["text"],
        prompt_en=prompt_en,
    )
    assert "moon" in align["required_subjects"]
    assert align["keywords_present"] is True
    assert len(align["missing_keywords"]) == 0

