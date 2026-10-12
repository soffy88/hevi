"""发布前套件（publishkit）单元测试。

单测用真实文件与真实 ffmpeg（合成一段几秒的测试片），不用 mock 产物；
E2E 真跑在 ``scripts/publishkit_e2e.py``。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hevi.layer4_legacy.publishkit.oprim_impl.contracts import (
    PLATFORMS,
    PLATFORMS_BY_ID,
    ScriptError,
)
from hevi.layer4_legacy.publishkit.oskill_impl.compliance import run_compliance
from hevi.layer4_legacy.publishkit.oskill_impl.fact_check import (
    build_source_ledger,
    extract_claims,
)
from hevi.layer4_legacy.publishkit.oskill_impl.platform_copy import (
    build_platform_copies,
    render_copy_md,
    topic_label,
)
from hevi.layer4_legacy.publishkit.oskill_impl.script_doc import parse_script

FFMPEG = "/home/soffy/.local/bin/ffmpeg"
FFPROBE = "/home/soffy/.local/bin/ffprobe"

TIMINGS = {
    "timings": [
        {"text": "为什么复利被称作世界第八大奇迹？", "start_s": 0.4, "end_s": 3.4},
        {"text": "答案藏在三个词里：时间、本金和收益率。", "start_s": 3.76, "end_s": 6.83},
        {"text": "复利，就是利息也能继续生利息。", "start_s": 7.18, "end_s": 9.8},
        {"text": "第一年赚的钱，第二年会一起参与增长。", "start_s": 10.15, "end_s": 13.38},
        {"text": "想让复利为你工作，据估算三步就够。", "start_s": 13.73, "end_s": 16.5},
        {"text": "越早开始越好，因为时间是最大的杠杆。", "start_s": 16.85, "end_s": 20.14},
    ]
}


@pytest.fixture
def timings_json(tmp_path: Path) -> Path:
    p = tmp_path / "timestamps.json"
    p.write_text(json.dumps(TIMINGS, ensure_ascii=False), encoding="utf-8")
    return p


# --- 文稿解析 ---------------------------------------------------------------


def test_parse_talkcraft_timings_gives_timed_lines(timings_json: Path) -> None:
    doc = parse_script(timings_json)
    assert doc.source_kind == "talkcraft_timestamps"
    assert len(doc.lines) == 6
    assert doc.timed
    assert doc.lines[0].start_s == 0.4
    # 章节必须来自真实时间戳
    assert doc.chapters
    assert doc.chapters[0][1] == pytest.approx(0.4)


def test_parse_scene_script(tmp_path: Path) -> None:
    p = tmp_path / "script.json"
    p.write_text(json.dumps([
        {"name": "00-intro", "segments": ["第一句开场白。", "第二句展开。"]},
        {"name": "01-body", "segments": ["第三句结论。"]},
    ], ensure_ascii=False), encoding="utf-8")
    doc = parse_script(p)
    assert doc.source_kind == "scene_script"
    assert len(doc.lines) == 3
    # 场景名是内部 id，不能当主题
    assert doc.topic == "第一句开场白"


def test_media_file_is_rejected_as_script(tmp_path: Path) -> None:
    fake_mp4 = tmp_path / "video.mp4"
    fake_mp4.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64)
    with pytest.raises(ScriptError, match="NOT_A_SCRIPT"):
        parse_script(fake_mp4)


def test_missing_script_raises(tmp_path: Path) -> None:
    with pytest.raises(ScriptError, match="SCRIPT_MISSING"):
        parse_script(tmp_path / "nope.json")


def test_empty_text_script_raises(tmp_path: Path) -> None:
    p = tmp_path / "script.md"
    p.write_text("   \n\n", encoding="utf-8")
    with pytest.raises(ScriptError, match="EMPTY_SCRIPT"):
        parse_script(p)


# --- 事实台账 ---------------------------------------------------------------


def test_claims_and_ledger_are_honest(timings_json: Path) -> None:
    doc = parse_script(timings_json)
    claims = extract_claims(doc)
    assert claims, "带数字/日期/引号的文稿必须抽出事实点"
    # 每条 claim 都必须指向一条真实的支撑句
    for claim in claims:
        assert 0 <= claim.line_index < len(doc.lines)
        assert claim.supported_by == doc.lines[claim.line_index].text

    ledger = build_source_ledger(doc, claims, checked_on="2026-10-12")
    payload = ledger.payload
    assert payload["claim_count"] == len(claims)
    assert payload["checked_on"] == "2026-10-12"
    # 未人工补链接时必须标 unsourced，不能假装已核实
    assert payload["status"] == "unsourced"
    assert payload["unsourced_count"] == len(claims)
    assert all(e["source_url"] == "" for e in payload["claims"])
    assert payload["manual_todo"]


def test_number_claim_extracted(tmp_path: Path) -> None:
    p = tmp_path / "s.md"
    p.write_text("去年这个数字是 240 倍。\n2024年3月5日上线。\n他说“很稳”。\n", encoding="utf-8")
    doc = parse_script(p)
    kinds = {c.kind for c in extract_claims(doc)}
    assert "number" in kinds
    assert "date" in kinds
    assert "quote" in kinds


# --- 八平台文案 -------------------------------------------------------------


def test_eight_platforms_within_limits(timings_json: Path) -> None:
    doc = parse_script(timings_json)
    copies = build_platform_copies(doc, checked_on="2026-10-12")
    assert len(copies) == len(PLATFORMS) == 8
    for copy in copies:
        spec = PLATFORMS_BY_ID[copy.platform]
        assert len(copy.title) <= spec.title_limit, (copy.platform, copy.title)
        assert len(copy.alt_title) <= spec.title_limit
        assert copy.body.strip()
        assert "__TITLE__" not in copy.body


def test_bilibili_chapters_use_real_timestamps(timings_json: Path) -> None:
    doc = parse_script(timings_json)
    copies = build_platform_copies(doc, checked_on="2026-10-12")
    bili = next(c for c in copies if c.platform == "bilibili")
    yt = next(c for c in copies if c.platform == "youtube")
    assert bili.chapters and yt.chapters
    times = [t for _name, t in bili.chapters]
    assert times == sorted(times)
    assert times[0] == pytest.approx(0.4)


def test_no_fabricated_chapters_without_timing(tmp_path: Path) -> None:
    p = tmp_path / "script.json"
    p.write_text(json.dumps([{"name": "00", "segments": ["一。", "二。"]}], ensure_ascii=False),
                 encoding="utf-8")
    doc = parse_script(p)
    copies = build_platform_copies(doc, checked_on="2026-10-12")
    bili = next(c for c in copies if c.platform == "bilibili")
    assert bili.chapters == ()  # 没有真实时间戳就不编时间码


def test_brand_only_used_when_provided(timings_json: Path) -> None:
    doc = parse_script(timings_json)
    without = next(c for c in build_platform_copies(doc, checked_on="2026-10-12")
                   if c.platform == "bilibili")
    assert "【" not in without.title

    from dataclasses import replace

    branded = replace(doc, brand="极客视界")
    with_brand = next(c for c in build_platform_copies(branded, checked_on="2026-10-12")
                      if c.platform == "bilibili")
    assert "【极客视界】" in with_brand.title


def test_xiaohongshu_respects_20_char_limit(tmp_path: Path) -> None:
    p = tmp_path / "script.md"
    p.write_text("这是一个非常非常长的主题标题需要被裁剪。\n第二句话讲清楚机制。\n", encoding="utf-8")
    doc = parse_script(p)
    copies = build_platform_copies(doc, checked_on="2026-10-12")
    xhs = next(c for c in copies if c.platform == "xiaohongshu")
    assert len(xhs.title) <= 20


def test_copy_md_has_all_platform_sections(timings_json: Path) -> None:
    doc = parse_script(timings_json)
    copies = build_platform_copies(doc, checked_on="2026-10-12")
    md = render_copy_md(doc, copies, checked_on="2026-10-12")
    for spec in PLATFORMS:
        assert f"## {spec.label}" in md
    assert "__TITLE__" not in md


def test_topic_label_drops_lead_in_clause() -> None:
    from hevi.layer4_legacy.publishkit.oprim_impl.contracts import ScriptDoc, ScriptLine

    doc = ScriptDoc(path="x", topic="你是否好奇，大语言模型究竟如何回答问题",
                    lines=(ScriptLine(0, "你是否好奇，大语言模型究竟如何回答问题"),))
    label = topic_label(doc)
    assert label.startswith("大语言模型")


# --- 合规 -------------------------------------------------------------------


def test_compliance_flags_investment_wording(timings_json: Path) -> None:
    from dataclasses import replace


    doc = parse_script(timings_json)
    copies = build_platform_copies(doc, checked_on="2026-10-12")
    bad = [replace(copies[0], body="这个方法必赚，赶紧抄作业。")]
    findings = {f.rule: f for f in run_compliance(doc, bad)}
    assert findings["no_investment_advice"].passed is False
    assert findings["no_investment_advice"].hits


def test_compliance_flags_buy_question(timings_json: Path) -> None:
    from dataclasses import replace

    doc = parse_script(timings_json)
    copies = build_platform_copies(doc, checked_on="2026-10-12")
    bad = [replace(copies[0], pinned_comment="你该不该买？")]
    findings = {f.rule: f for f in run_compliance(doc, bad)}
    assert findings["ending_question_is_experience"].passed is False


def test_compliance_passes_for_generated_copy(timings_json: Path) -> None:
    doc = parse_script(timings_json)
    copies = build_platform_copies(doc, checked_on="2026-10-12")
    findings = run_compliance(doc, copies)
    assert all(f.passed for f in findings), [(f.rule, f.hits) for f in findings if not f.passed]


# --- 真实媒体的交付 QA / 封面 ---------------------------------------------


@pytest.fixture(scope="module")
def real_clip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """用 ffmpeg 真合成一段 3 秒 640x360 带音轨的测试片（不是 mock 产物）。"""

    out = tmp_path_factory.mktemp("media") / "clip.mp4"
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=white:s=640x360:d=3",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)],
        check=True,
    )
    return out


def test_delivery_qa_measures_real_clip(real_clip: Path) -> None:
    from hevi.layer4_legacy.publishkit.omodul_impl.qa import run_delivery_qa

    cues = [{"index": 1, "start_s": 0.2, "end_s": 1.2, "text": "测试字幕"}]
    qa = run_delivery_qa(real_clip, caption_cues=cues, caption_source="unit-test cues")
    names = {c["name"]: c["passed"] for c in qa["checks"]}
    assert names["resolution_written"] and names["fps"] and names["audio_stream"]
    assert names["decode_clean"]
    assert names["loudness_measured"]
    # 响度必须是实测数值，不是占位
    assert qa["loudness"]["measured"] is True
    assert isinstance(qa["loudness"]["integrated_lufs"], float)
    assert names["subtitle_overflow"] is True
    assert qa["subtitle_overflow"]["cue_validation"]["cue_count"] == 1


def test_delivery_qa_rejects_overlapping_cues(real_clip: Path) -> None:
    from hevi.layer4_legacy.publishkit.omodul_impl.qa import run_delivery_qa

    cues = [
        {"index": 1, "start_s": 0.2, "end_s": 1.5, "text": "一"},
        {"index": 2, "start_s": 1.0, "end_s": 2.0, "text": "二"},
    ]
    qa = run_delivery_qa(real_clip, caption_cues=cues, caption_source="unit-test cues")
    validation = qa["subtitle_overflow"]["cue_validation"]
    assert validation["violations"]["overlaps"]
    assert qa["subtitle_overflow"]["passed"] is False


def test_delivery_qa_without_cues_is_unavailable_not_passed(real_clip: Path) -> None:
    from hevi.layer4_legacy.publishkit.omodul_impl.qa import run_delivery_qa

    qa = run_delivery_qa(real_clip, caption_source="none")
    so = qa["subtitle_overflow"]
    assert so["cue_validation"]["status"] == "unavailable"
    assert so["passed"] is False


def test_cover_ratios_are_exact(real_clip: Path, tmp_path: Path) -> None:
    from hevi.layer4_legacy.publishkit.omodul_impl.cover import build_covers, run_cover_qa

    covers = build_covers(real_clip, tmp_path, topic="测试标题很长很长", subtitle="副标题")
    qa = run_cover_qa(covers, topic="测试标题很长很长", video=real_clip)
    by_ratio = {c["ratio"]: c for c in qa["covers"]}
    for ratio, rw, rh in (("3x4", 3, 4), ("4x3", 4, 3), ("16x9", 16, 9)):
        entry = by_ratio[ratio]
        assert entry["width"] * rh == entry["height"] * rw, ratio
        assert entry["ratio_ok"] is True
    assert qa["missing_ratios"] == []
    assert qa["passed"] is True
    # 上游要求 AI 生成封面；本地零成本做不到，必须如实标注偏差
    assert qa["provenance"]["upstream_ai_cover_rule_met"] is False


def test_silence_split_uses_narration_end() -> None:
    from hevi.layer4_legacy.publishkit.omodul_impl.qa import split_silence

    segs = ["silence_start: 2.0", "silence_start: 33.0"]
    body, trailing = split_silence(segs, narration_end_s=32.0)
    assert body == ["silence_start: 2.0"]
    assert trailing == ["silence_start: 33.0"]
    # 字幕尾留白容差：结束点前 0.5s 内的静音算尾部，不算口播断句
    body2, trailing2 = split_silence(["silence_start: 31.8"], narration_end_s=32.0)
    assert body2 == [] and trailing2 == ["silence_start: 31.8"]
    # 结束点未知 → 全部视为需要关注，不默认放行
    assert split_silence(segs, narration_end_s=None) == (segs, [])


def test_parse_srt(tmp_path: Path) -> None:
    from hevi.layer4_legacy.publishkit.omodul_impl.qa import parse_srt

    srt = tmp_path / "字幕.srt"
    srt.write_text(
        "1\n00:00:00,200 --> 00:00:03,560\n第一句\n\n"
        "2\n00:00:03,560 --> 00:00:06,320\n第二句\n",
        encoding="utf-8",
    )
    cues = parse_srt(srt)
    assert len(cues) == 2
    assert cues[0]["start_s"] == pytest.approx(0.2)
    assert cues[1]["end_s"] == pytest.approx(6.32)
    assert cues[1]["text"] == "第二句"


# --- 外观层端到端（真实媒体） ---------------------------------------------


def test_adapter_builds_full_bundle(real_clip: Path, tmp_path: Path, timings_json: Path) -> None:
    from hevi.publishkit.adapter import generate_publish_bundle

    res = generate_publish_bundle(
        video_path=real_clip, script_path=timings_json, output_dir=tmp_path / "out",
        config={"topic": "复利为什么被称为世界第八大奇迹"},
    )
    bundle = Path(res.output_dir)
    assert bundle.name == "publish_bundle"
    for name in ("copy.md", "copy.json", "qa_report.json", "fact_sources.json",
                 "cover_qa.json", "compliance.json"):
        assert (bundle / name).is_file(), name
    copy_json = json.loads((bundle / "copy.json").read_text(encoding="utf-8"))
    assert len(copy_json["platforms"]) == 8
    for platform in copy_json["platforms"]:
        spec = PLATFORMS_BY_ID[platform["platform"]]
        assert platform["title_len"] <= spec.title_limit
        assert "__TITLE__" not in platform["body"]

    # 零成本约束下 LLM 未配置 → 必须标明降级，而不是假装用了 LLM
    assert res.llm_degraded is True
    assert res.llm_reason
    assert json.loads((bundle / "copy.json").read_text(encoding="utf-8"))["llm_degraded"] is True

    qa = json.loads((bundle / "qa_report.json").read_text(encoding="utf-8"))
    assert qa["sha256"]
    assert qa["probe"]["width"] == 640