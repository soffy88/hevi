"""S24：吸收 article2media 的审片/字级同步/一稿多发/文章账本/翻译校验/合规。"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hevi.studio import repurpose_s24 as s24


FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


def _clip(path: Path, *, duration: float = 6.0, subtitle: bool = True) -> Path:
    font = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    filters = []
    if subtitle:
        filters.append(
            f"drawtext=fontfile='{font}':text='八十亿人住在哪里':x=(w-text_w)/2:"
            "y=h*0.78:fontsize=28:fontcolor=white:box=1:boxcolor=black@0.42:boxborderw=8"
        )
    vf = ",".join(filters) if filters else "null"
    cmd = [
        FFMPEG, "-y", "-f", "lavfi", "-i", f"testsrc2=s=320x568:d={duration}:rate=24",
        "-f", "lavfi", "-i", f"sine=frequency=420:duration={duration}",
        "-vf", vf, "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-shortest", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr[-400:]
    return path


def test_review_delivery_passes_good_cues(tmp_path: Path) -> None:
    clip = _clip(tmp_path / "good.mp4")
    review = s24.review_delivery(
        clip,
        narration=[{"text": "八十亿人住在哪里", "start": 0.0, "end": 2.4}, {"text": "大部分住亚洲", "start": 2.5, "end": 4.6}],
        cues=[
            {"start": 0.0, "end": 2.5, "text": "八十亿人住哪里"},
            {"start": 2.5, "end": 4.6, "text": "大部分在亚洲"},
        ],
        subtitle_plan={"hard_cut": True, "band": {"x0": 0.05, "y0": 0.7, "x1": 0.95, "y1": 0.92}},
    )
    assert review["schema"] == s24.REVIEW_SCHEMA
    assert review["media_sha256"]
    assert review["pass"] is True, [c for c in review["checks"] if c["status"] == "fail"]
    assert review["counts"]["fail"] == 0
    assert review["retry"] == []


def test_review_delivery_flags_subtitle_and_speech_failures(tmp_path: Path) -> None:
    clip = _clip(tmp_path / "bad.mp4")
    review = s24.review_delivery(
        clip,
        narration=[{"text": "这是一句非常非常长的开场白用来测试语速和首句字数是否超限", "start": 0.0, "end": 5.0}],
        cues=[
            {"start": 0.0, "end": 0.2, "text": "太短"},
            {"start": 0.4, "end": 1.6, "text": "这一句字幕明显超过十三个字需要拆分"},
        ],
        subtitle_plan={"hard_cut": False},
        frame_check=False,
    )
    ids = {check["id"] for check in review["checks"] if check["status"] == "fail"}
    assert {"first_sentence_chars", "speech_rate_max", "subtitle_dwell", "subtitle_line_length",
            "subtitle_pause_hold", "subtitle_blink", "subtitle_hard_cut"} <= ids
    assert review["pass"] is False
    assert {item["node"] for item in review["retry"]} >= {"script", "narration", "subtitle"}


def test_review_overview_writes_png(tmp_path: Path) -> None:
    clip = _clip(tmp_path / "overview.mp4")
    review = s24.review_delivery(clip, narration=[{"text": "第一句", "start": 0, "end": 2.0}])
    out = s24.render_review_overview(review, tmp_path / "review-overview.png")
    assert out.is_file() and out.stat().st_size > 5000


def test_word_sync_uses_measured_words_and_html_overlay() -> None:
    plan = s24.word_sync_plan(
        transcript="八十亿人住在哪里大部分人住在亚洲",
        words=[
            {"text": "八十亿", "start": 0.2, "end": 1.0},
            {"text": "人", "start": 1.0, "end": 1.2},
            {"text": "住在", "start": 1.2, "end": 1.6},
            {"text": "哪里", "start": 1.6, "end": 2.0},
            {"text": "大部分", "start": 2.1, "end": 2.6},
            {"text": "人", "start": 2.6, "end": 2.8},
            {"text": "住在", "start": 2.8, "end": 3.1},
            {"text": "亚洲", "start": 3.1, "end": 3.6},
        ],
        shots=[
            {"id": "n", "kind": "number_roll", "trigger": "八十亿", "value": "80 亿", "label": "人口"},
            {"id": "l", "kind": "checklist", "items": [{"text": "亚洲最多", "trigger": "亚洲"}]},
            {"id": "c", "kind": "compare", "sides": [{"text": "亚洲", "trigger": "亚洲"}, {"text": "其他", "trigger": "哪里"}]},
            {"id": "q", "kind": "quote", "trigger": "大部分", "text": "大部分人在亚洲"},
        ],
        theme="signal",
    )
    assert plan["status"] == "measured"
    assert plan["text_in_image"] is False and plan["overlay"] == "html_css"
    numbers = {shot["id"]: shot["appear_at"] for shot in plan["shots"]}
    assert numbers["n"] == 0.2
    assert numbers["q"] == 2.1
    assert "画面内不生成任何文字" in plan["shots"][0]["image_prompt"]
    assert "--s24-accent:" in plan["css"]
    assert "s24-number" in plan["html"]


def test_word_sync_pending_without_audio() -> None:
    plan = s24.word_sync_plan(transcript="没有音频", shots=[{"id": 1, "kind": "quote", "text": "x"}])
    assert plan["status"] == "pending_alignment"
    assert plan["shots"] == []


def test_export_text_pack_cards_wechat_and_long_image(tmp_path: Path) -> None:
    sections = [
        {"heading": "第一件事", "body": "先说要紧的结论，再补细节。", "bullets": ["要点一", "要点二"]},
        {"heading": "第二件事", "body": "把动作写小，把结果写大。"},
    ]
    manifest = s24.export_text_pack(
        title="一稿多发怎么做", sections=sections, out_dir=tmp_path, theme="moss", author="作者",
    )
    assert manifest["schema"] == s24.EXPORT_SCHEMA
    cards = [Path(item) for item in manifest["paths"]["cards"]]
    assert len(cards) == 3 and all(card.is_file() for card in cards)
    from PIL import Image

    assert Image.open(cards[0]).size == (1080, 1440)
    long_image = Image.open(manifest["paths"]["long_image"])
    assert long_image.size[0] == 1080 and long_image.size[1] > 1440
    html_text = Path(manifest["paths"]["wechat_html"]).read_text(encoding="utf-8")
    assert "data:image/png;base64," in html_text
    assert "http://" not in html_text and "https://" not in html_text
    assert "复制到公众号" in html_text
    css = Path(manifest["paths"]["theme_css"]).read_text(encoding="utf-8")
    assert "--s24-accent" in css and "--s24-subtitle-bottom" in css
    assert manifest["wechat_images_base64"] >= 1
    assert Path(manifest["paths"]["caption"]).read_text(encoding="utf-8").strip()


def test_article_ledger_locks_and_verifies(tmp_path: Path) -> None:
    source = tmp_path / "input.md"
    source.write_text("# 标题\n\n第一段。\n\n第二段有 80 亿人。\n", encoding="utf-8")
    result = s24.ingest_article(str(source), tmp_path / "out", author="张三")
    ledger = json.loads(Path(result["ledger"]["path"]).read_text(encoding="utf-8"))
    assert ledger["schema"] == s24.LEDGER_SCHEMA
    assert result["ledger"]["block_count"] == 3
    blocks = ledger["blocks"]
    assert [block["kind"] for block in blocks] == ["heading", "paragraph", "paragraph"]
    same = s24.verify_article_render(blocks, [dict(block) for block in blocks])
    assert same["ok"] is True and same["mismatches"] == []
    tampered = [dict(block) for block in blocks]
    tampered[1]["text"] = "第一段被改。"
    bad = s24.verify_article_render(blocks, tampered)
    assert bad["ok"] is False and bad["mismatches"][0]["index"] == 1


def test_video_transcript_rights_gate() -> None:
    ok = s24.guard_video_transcript(url="https://example.com/v", rights_basis="self", author="我")
    assert ok["ok"] and ok["cookie_use"] is False and ok["author"] == "我"
    assert "不批量抓取" in ok["policy"] and "cookie" in ok["policy"]
    with pytest.raises(ValueError):
        s24.guard_video_transcript(url="https://example.com/v", rights_basis="unknown")
    with pytest.raises(ValueError):
        s24.guard_video_transcript(url="https://example.com/v", rights_basis="authorized")
    with pytest.raises(ValueError):
        s24.guard_video_transcript(url="https://example.com/v", rights_basis="self", bulk=True)


def test_localization_check_blocks_number_loss() -> None:
    ok = s24.check_localization(["增长 12%", "覆盖 80 亿人"], ["增长 12%", "覆盖 80 亿人"], source_lang="en", target_lang="zh")
    assert ok["ok"] is True and ok["counts"]["fail"] == 0
    bad = s24.check_localization(["增长 12%", "覆盖 80 亿人"], ["增长 12%", "覆盖很多人"])
    assert bad["ok"] is False
    kinds = {issue["kind"] for issue in bad["issues"]}
    assert "number_loss" in kinds and bad["number_loss"][0]["number"] == "80亿"
    short = s24.check_localization(["a", "b", "c"], ["a", "b"])
    assert short["block_count"] == {"source": 3, "translated": 2}
    assert short["missing_blocks"] == 1


def test_voice_tiers_require_self_authorization_and_confirmation() -> None:
    pack = s24.check_voice_tier("huayan", cloned=False)
    assert pack["ok"] is True and pack["tier"] == "pack"
    with pytest.raises(ValueError):
        s24.check_voice_tier("me", cloned=True, rights_basis="other")
    pending = s24.check_voice_tier("me", cloned=True, rights_basis="self", confirmed=False)
    assert pending["ok"] is False and pending["requires_confirmation"] is True
    done = s24.check_voice_tier("me", cloned=True, rights_basis="self", confirmed=True)
    assert done["ok"] is True


def test_font_licenses_are_all_open_and_listed() -> None:
    fonts = s24.font_licenses()
    assert fonts["entries"] and fonts["blocked"] == []
    assert all("OFL" in entry["license"] for entry in fonts["entries"])
    assert {"noto-sans-cjk", "fusion-pixel"} <= set(fonts["allowed"])


def test_stamp_aigc_writes_metadata_and_manifest(tmp_path: Path) -> None:
    clip = _clip(tmp_path / "aigc.mp4", duration=3.0, subtitle=False)
    manifest = s24.stamp_aigc(clip, tmp_path / "aigc-stamped.mp4")
    assert manifest["metadata_written"]["comment"] == f"AIGC: {s24.AIGC_LABEL}"
    assert Path(manifest["media"]).is_file()
    assert Path(tmp_path / "aigc-stamped.aigc.json").is_file()
    info = s24.probe_media(manifest["media"])
    assert info["duration_s"] > 0


def test_plan_repurpose_exposes_all_s24_blocks() -> None:
    plan = s24.plan_repurpose(format_id="explainer", topic="测试", lines=["第一句"])
    assert plan["schema"] == s24.SCHEMA
    assert plan["word_sync"]["text_in_image"] is False
    assert {option["id"] for option in plan["export_options"]} == {"cards_3x4", "wechat_html", "long_image"}
    assert plan["compliance"]["aigc"]["mp4_metadata"] is True
    assert plan["localization"]["merged_into"] == "localization_dub"
    assert plan["delivery_review"]["hard_limits"]["lufs"] == -14.0
