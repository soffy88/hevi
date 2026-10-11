"""Unit and integration tests for ViralClone (3O architecture)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from hevi.layer4_legacy.viralclone.oprim_impl.specs import (
    DiversityRecord,
    ReferenceBreakdown,
    RhythmStats,
    SubtitleBox,
    TemplateSegment,
    TemplateSpec,
    VisualAnchor,
    WordToken,
    validate_template_spec,
)
from hevi.layer4_legacy.viralclone.oskill_impl.anchoring import (
    align_segments_to_word_timestamps,
    build_ass_subtitles,
    build_timeline_from_anchors,
)
from hevi.layer4_legacy.viralclone.oskill_impl.breakdown_math import (
    classify_sentence_semantic_role,
    compute_rhythm_stats,
    detect_subtitle_box_from_frames,
)
from hevi.layer4_legacy.viralclone.oskill_impl.diversity import (
    compute_frame_phash,
    compute_phash_hamming_distance,
    compute_text_similarity,
    compute_variant_diversity_matrix,
)
from hevi.layer4_legacy.viralclone.oskill_impl.watermark import (
    compute_watermark_spec,
    verify_watermark_in_frame,
)
from hevi.viralclone import (
    breakdown_reference_video,
    compile_and_render_template,
    draft_template_from_breakdown,
    generate_variant_matrix,
    produce_product_asset,
    produce_viralclone,
    reference_breakdown,
)


def test_oprim_specs_serialization() -> None:
    token = WordToken(word="hello", start_s=0.1, end_s=0.5, score=0.95)
    d = token.to_dict()
    assert d == {"word": "hello", "start_s": 0.1, "end_s": 0.5, "score": 0.95}

    anchor = VisualAnchor(
        event_type="punch_in",
        sentence_idx=0,
        word_offset_idx=2,
        relative_delay_s=0.1,
        duration_s=1.5,
        parameters={"zoom": 1.2},
    )
    seg = TemplateSegment(
        segment_id="seg_01",
        role="hook",
        narration_slot="hook_text",
        anchors=[anchor],
    )
    spec = TemplateSpec(
        template_id="test_tmpl",
        segments=[seg],
        default_slots={"hook_text": "Buy now!"},
    )
    serialized = spec.to_dict()
    assert serialized["template_id"] == "test_tmpl"
    assert serialized["segments"][0]["anchors"][0]["parameters"]["zoom"] == 1.2

    reconstructed = TemplateSpec.from_dict(serialized)
    assert reconstructed.template_id == "test_tmpl"
    assert len(reconstructed.segments) == 1
    assert reconstructed.segments[0].anchors[0].event_type == "punch_in"


def test_validate_template_spec() -> None:
    # Empty segments
    invalid = TemplateSpec(template_id="bad", segments=[])
    errors = validate_template_spec(invalid)
    assert "no_segments" in errors

    # Valid spec
    valid = TemplateSpec(
        template_id="good",
        segments=[
            TemplateSegment(
                segment_id="s1",
                role="hook",
                narration_slot="hook_line",
                anchors=[VisualAnchor(event_type="cut", sentence_idx=0)],
            )
        ],
    )
    assert validate_template_spec(valid) == []


def test_rhythm_math_and_stats() -> None:
    words = [
        WordToken("Hey", 0.1, 0.5),
        WordToken("there", 0.5, 1.0),
        WordToken("guys", 1.1, 1.5),
        WordToken("buy", 2.5, 3.0),
    ]
    cuts = [1.2, 2.8]
    stats = compute_rhythm_stats(
        duration_s=3.5,
        cut_timestamps_s=cuts,
        words=words,
        sentences=[{"text": "Hey there guys", "start_s": 0.1, "end_s": 1.5}],
        silences=[{"start_s": 1.5, "end_s": 2.5, "duration_s": 1.0}],
    )
    assert stats.shot_count >= 3
    assert stats.first_shot_duration_s == 1.2
    assert stats.speech_rate_wps > 0
    assert len(stats.silence_intervals) == 1


def test_semantic_sentence_classification() -> None:
    sents = [
        "Don't scroll past this amazing secret!",
        "It has titanium coated drivers and ultra long battery life.",
        "Laboratory tests prove it outlasts competitors by 50%.",
        "Order yours today with the link below.",
    ]
    roles = [
        classify_sentence_semantic_role(s, idx, len(sents))
        for idx, s in enumerate(sents)
    ]
    assert roles[0] == "hook"
    assert roles[1] == "selling_point"
    assert roles[2] == "proof"
    assert roles[3] == "cta"


def test_word_anchored_alignment() -> None:
    spec = TemplateSpec(
        template_id="tmpl_align",
        segments=[
            TemplateSegment(
                segment_id="seg_0",
                role="hook",
                narration_slot="hook",
                anchors=[VisualAnchor(event_type="cut", sentence_idx=0, word_offset_idx=0)],
            ),
            TemplateSegment(
                segment_id="seg_1",
                role="cta",
                narration_slot="cta",
                anchors=[VisualAnchor(event_type="punch_in", sentence_idx=1, word_offset_idx=1)],
            ),
        ],
    )
    slots = {"hook": "Stop looking.", "cta": "Click now."}
    sents = [
        {"text": "Stop looking.", "start_s": 0.0, "end_s": 1.2},
        {"text": "Click now.", "start_s": 1.5, "end_s": 2.5},
    ]
    words = [
        WordToken("Stop", 0.0, 0.5),
        WordToken("looking.", 0.5, 1.2),
        WordToken("Click", 1.5, 1.9),
        WordToken("now.", 1.9, 2.5),
    ]
    aligned = align_segments_to_word_timestamps(spec, slots, sents, words)
    assert len(aligned) == 2
    assert aligned[0]["start_s"] == 0.0
    assert aligned[0]["end_s"] == 1.2
    assert aligned[1]["anchors"][0]["start_s"] == 1.9  # offset 1 is "now."


def test_ass_karaoke_and_watermark_generation() -> None:
    words = [
        WordToken("Stop", 0.0, 0.5),
        WordToken("looking.", 0.5, 1.2),
    ]
    sents = [
        {"text": "Stop looking.", "start_s": 0.0, "end_s": 1.2},
    ]
    ass = build_ass_subtitles(
        words=words,
        sentences=sents,
        width=720,
        height=1280,
        watermark_text="AI生成",
        watermark_duration_s=2.5,
    )
    assert "[Script Info]" in ass
    assert "PlayResX: 720" in ass
    assert "PlayResY: 1280" in ass
    assert "Style: Watermark" in ass
    assert "AI生成" in ass
    assert "{\\k50}Stop" in ass


def test_watermark_spec_gb45438() -> None:
    # 720x1280 portrait (short edge = 720) -> font_size >= 36px (5% of 720)
    spec_portrait = compute_watermark_spec(720, 1280)
    assert spec_portrait.font_size_px >= 36
    assert spec_portrait.duration_s >= 2.0
    assert spec_portrait.ratio_to_short_edge >= 0.05

    # 1280x720 landscape (short edge = 720)
    spec_land = compute_watermark_spec(1280, 720)
    assert spec_land.font_size_px >= 36
    assert spec_land.duration_s >= 2.0


def test_diversity_hamming_and_matrix(tmp_path: Path) -> None:
    # Hash distance test
    h1 = "ffff0000ffff0000"
    h2 = "ffff0000ffff000f"
    dist = compute_phash_hamming_distance(h1, h2)
    assert dist == 4

    # Text similarity
    sim_same = compute_text_similarity("hello world", "hello world")
    assert sim_same == 1.0
    sim_diff = compute_text_similarity("completely distinct topic", "apple banana orange")
    assert sim_diff < 0.3

    # Diversity Matrix
    records = [
        {
            "variant_id": "v1",
            "frame_hashes": ["d650e929549eae27"],
            "script_text": "Brand new running shoes with maximum cushioning",
        },
        {
            "variant_id": "v2",
            "frame_hashes": ["ee996be6b21901ca"],
            "script_text": "Discover deep ocean creatures living at extreme depth",
        },
    ]
    comps, passed = compute_variant_diversity_matrix(
        records, min_phash_distance=5, max_text_similarity=0.8
    )
    assert passed is True
    assert len(comps) == 1
    assert comps[0].passed is True


def test_omodul_blocked_on_invalid_inputs(tmp_path: Path) -> None:
    # reference_breakdown with missing file
    res = reference_breakdown({}, {"video_path": "/nonexistent/video.mp4"}, tmp_path)
    assert res["status"] == "blocked"
    assert "INVALID_SOURCE_VIDEO" in res["reason"]
    assert res["cost"]["total_usd"] == 0.0

    # produce_product_asset with missing image
    res = produce_product_asset({}, {"product_image": "/nonexistent/img.png"}, tmp_path)
    assert res["status"] == "blocked"
    assert "INVALID_PRODUCT_IMAGE" in res["reason"]

    # generate_variant_matrix with empty variants
    res = generate_variant_matrix({}, {"variants": []}, tmp_path)
    assert res["status"] == "blocked"
    assert "NO_VARIANTS_SPECIFIED" in res["reason"]


def test_produce_viralclone_dispatcher(tmp_path: Path) -> None:
    res = produce_viralclone({}, {"action": "unknown_action"}, tmp_path)
    assert res["status"] == "blocked"
    assert "UNKNOWN_VIRALCLONE_ACTION" in res["reason"]


def test_real_media_reference_breakdown(tmp_path: Path) -> None:
    video = Path("artifacts/real_video/20261005T160434Z/artifacts/scene_interview_sub.mp4")
    if not video.is_file():
        pytest.skip("Real media test artifact not found")

    res = reference_breakdown({}, {"video_path": str(video), "sample_fps": 1.0}, tmp_path)
    assert res["status"] == "succeeded"
    assert (tmp_path / "breakdown.json").is_file()
    assert (tmp_path / "breakdown.md").is_file()
    assert (tmp_path / "contactsheet.jpg").is_file()

    breakdown_data = json.loads((tmp_path / "breakdown.json").read_text())
    assert breakdown_data["duration_s"] > 20.0
    assert len(breakdown_data["words"]) > 50
    assert breakdown_data["subtitle_box"] is not None
    assert breakdown_data["subtitle_box"]["relative_line_height"] > 0.04


def test_real_media_produce_product_asset(tmp_path: Path) -> None:
    img_path = tmp_path / "bottle.png"
    im = Image.new("RGB", (300, 300), color=(255, 255, 255))
    im.save(img_path)

    out_dir = tmp_path / "product_out"
    res = produce_product_asset(
        {},
        {
            "product_image": str(img_path),
            "product_title": "Smart Watch",
            "duration_s": 1.0,
            "width": 720,
            "height": 1280,
        },
        out_dir,
    )
    assert res["status"] == "succeeded"
    report = res["report"]
    assert Path(report["product_video"]).is_file()
    assert Path(report["cutout_png"]).is_file()
    assert report["resolution"] == "720x1280"


def test_real_media_compile_and_variants(tmp_path: Path) -> None:
    broll = Path("artifacts/real_video/20261005T160434Z/artifacts/scene_broll_720p.mp4")
    if not broll.is_file():
        pytest.skip("Real media test artifact not found")

    spec = TemplateSpec(
        template_id="tpl_e2e_test",
        aspect_ratio="16:9",
        width=1280,
        height=720,
        fps=25,
        segments=[
            TemplateSegment(
                segment_id="s1_hook",
                role="hook",
                narration_slot="hook_text",
                anchors=[VisualAnchor(event_type="cut", sentence_idx=0, word_offset_idx=0)],
            ),
            TemplateSegment(
                segment_id="s2_cta",
                role="cta",
                narration_slot="cta_text",
                anchors=[VisualAnchor(event_type="cut", sentence_idx=1, word_offset_idx=0)],
            ),
        ],
    )

    out_compile = tmp_path / "compile_out"
    res_compile = compile_and_render_template(
        {},
        {
            "template": spec.to_dict(),
            "slots": {
                "hook_text": "Look at this incredible space view right now.",
                "cta_text": "Explore more today.",
                "lang": "en",
            },
            "brolls": [str(broll.resolve())],
            "aspect_ratio": "16:9",
        },
        out_compile,
    )
    assert res_compile["status"] == "succeeded"
    rep = res_compile["report"]
    assert Path(rep["video_path"]).is_file()
    assert Path(rep["timeline_path"]).is_file()
    assert Path(rep["ass_path"]).is_file()
    assert rep["watermark_qa"]["passed"] is True
    assert rep["metadata_qa"]["has_implicit_watermark"] is True

    # Test Variant Matrix with 2 distinct variants
    out_variants = tmp_path / "variants_out"
    variants_input = [
        {
            "variant_id": "var_1",
            "template": spec.to_dict(),
            "slots": {
                "hook_text": "Deep sea exploration has never looked clearer.",
                "cta_text": "Dive in today.",
                "lang": "en",
            },
            "brolls": [str(broll.resolve())],
        },
        {
            "variant_id": "var_2",
            "template": spec.to_dict(),
            "slots": {
                "hook_text": "Ultra lightweight titanium running shoes for athletes.",
                "cta_text": "Claim discount now.",
                "lang": "en",
            },
            "brolls": [str(broll.resolve())],
        },
    ]
    res_var = generate_variant_matrix(
        {},
        {
            "variants": variants_input,
            "max_concurrency": 2,
            "min_phash_distance": 2,
            "max_text_similarity": 0.85,
        },
        out_variants,
    )
    assert res_var["status"] == "succeeded"
    assert res_var["report"]["variant_count"] == 2
    assert Path(res_var["report"]["diversity_matrix_json"]).is_file()

