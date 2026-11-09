"""Series, topics, beats, cost gate, segment gate, i18n, review and canvas."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from hevi.ai_drama.beats import beats_to_script, build_beats, revise_beat, validate_beats
from hevi.ai_drama.compile import compile_storyboard
from hevi.ai_drama.cost_gate import build_plan, gate
from hevi.ai_drama.credits import CreditLedger
from hevi.ai_drama.i18n import apply_bilingual, write_srt
from hevi.ai_drama.review import review_episodes
from hevi.ai_drama.rules import check_script, check_storyboard, summarise
from hevi.ai_drama.schema import normalize_script, normalize_storyboard
from hevi.ai_drama.segment_gate import detect_text_artifacts, voice_similarity
from hevi.ai_drama.series import (
    annotate_assets,
    card_findings,
    check_episode_consistency,
    compare_to_anchor,
    create_series,
    inject_cast,
)
from hevi.ai_drama.topics import GENRE_LIBRARY, suggest_topics

CAST = [
    {"id": "c1", "name": "阿远", "hair": "短发", "hair_part": "三七分", "eye_color": "深棕",
     "signature_detail": "左眼下一颗小痣",
     "outfit": {"top": "浅色卫衣", "bottom": "深色长裤", "shoes": "白色帆布鞋"},
     "accessories": ["手绳"], "personality": "嘴硬心软",
     "voice": {"description": "偏低、克制", "piper_voice": "zh_CN-huayan-medium.onnx", "pitch_semitones": -1.0}},
    {"id": "c2", "name": "小满", "hair": "马尾", "hair_part": "中分", "eye_color": "黑色",
     "signature_detail": "右耳一枚小耳钉",
     "outfit": {"top": "针织开衫", "bottom": "牛仔裤", "shoes": "棕色短靴"},
     "accessories": ["小耳钉"], "personality": "直率",
     "voice": {"description": "明亮、温和", "piper_voice": "zh_CN-huayan-medium.onnx", "pitch_semitones": 1.5}},
]


@pytest.fixture()
def series(tmp_path: Path) -> dict:
    return create_series(title="测试系列", genre="tsundere", cast=CAST, out_dir=tmp_path / "series")


def _idea(series: dict, pov: bool = False) -> dict:
    topics = suggest_topics(series, pov=pov)
    return next(i for i in topics["ideas"] if i["id"] == topics["recommended"])


def test_series_card_and_injection(series: dict) -> None:
    assert not [f for f in card_findings(series["cast"][0]) if f["severity"] == "blocker"]
    script = normalize_script({
        "title": "t", "style": "anime",
        "characters": [{"id": "c1", "name": "阿远"}],
        "scenes": [{"name": "房间", "int_ext": "内", "day_night": "日", "beats": [
            {"event": "x", "action": ["△他抬手"], "dialogue": [{"speaker": "c1", "text": "嗯。"}]}]}],
    })
    merged = inject_cast(script, series)
    char = merged["characters"][0]
    assert char["character_card"]["hair"] == "短发"
    assert "三七分" in char["look"]
    assert merged["series_id"] == series["series_id"]


def test_character_card_missing_field_is_flagged() -> None:
    bad = dict(CAST[0])
    bad["hair"] = ""
    findings = card_findings(bad)
    assert any(f["rule"] == "C-CARD" and "hair" in f["message"] for f in findings)


def test_compare_to_anchor_same_and_different(tmp_path: Path) -> None:
    anchor = tmp_path / "anchor.png"
    img = Image.new("RGB", (256, 256), (220, 200, 180))
    draw = ImageDraw.Draw(img)
    draw.rectangle((80, 20, 180, 110), fill=(40, 30, 30))
    draw.rectangle((60, 130, 200, 240), fill=(30, 90, 160))
    img.save(anchor)
    same = tmp_path / "same.png"
    img.save(same)
    obj = compare_to_anchor(same, anchor)
    assert obj["passed"] and obj["face"] > 0.99
    diff = Image.new("RGB", (256, 256), (30, 30, 30))
    ImageDraw.Draw(diff).ellipse((40, 40, 120, 120), fill=(255, 255, 0))
    diff_path = tmp_path / "diff.png"
    diff.save(diff_path)
    obj2 = compare_to_anchor(diff_path, anchor)
    assert obj2["clothing"] < obj["clothing"] or not obj2["passed"]


def test_prompt_fields_and_consistency(tmp_path: Path) -> None:
    from hevi.ai_drama.assets import build_assets

    seeded = create_series(title="s", genre="tsundere", cast=CAST, out_dir=tmp_path / "s")
    idea = _idea(seeded)
    script = normalize_script(beats_to_script(idea, build_beats(idea, CAST), CAST))
    merged = inject_cast(script, seeded)
    assets = annotate_assets(build_assets(merged), seeded)
    identity = next(i for i in assets["images"] if i["kind"] == "character_identity")
    assert identity["card_fields"]
    assert "角色卡固定项" in identity["prompt"]
    report = check_episode_consistency(assets, seeded, out_dir=tmp_path)
    # No pixels rendered yet: prompt checks still run, no visual failure.
    assert "C-PROMPT" not in {f["rule"] for f in report["findings"]}


def test_topics_three_ideas_and_hook(series: dict) -> None:
    result = suggest_topics(series)
    assert result["passed"]
    assert len(result["ideas"]) == 3
    assert len({i["genre"] for i in result["ideas"]}) == 3
    for idea in result["ideas"]:
        assert idea["genre"] in GENRE_LIBRARY
        assert idea["hook_first_2s"]
        assert len(idea["hook_first_2s"]) <= 24
    assert result["recommended"] in {i["id"] for i in result["ideas"]}
    assert result["recommendation_reason"]


def test_beats_five_revise_one_and_pov(series: dict) -> None:
    idea = _idea(series)
    beats = build_beats(idea, series["cast"])
    assert len(beats) == 5
    assert beats[0]["end_s"] <= 2.0
    assert 15.0 <= beats[-1]["end_s"] <= 20.5
    patched = revise_beat(beats, 2, {"picture": "只改这一拍"})
    assert patched[2]["picture"] == "只改这一拍"
    assert all(patched[i] == beats[i] for i in (0, 1, 3, 4))
    pov_beats = build_beats(idea, series["cast"], pov=True)
    assert not [f for f in validate_beats(pov_beats, pov=True, lead_id="c1") if f["severity"] == "blocker"]
    for beat in pov_beats:
        assert any(term in beat["picture"] for term in ("手", "袖", "鞋"))


def test_pov_script_and_storyboard_pass(series: dict) -> None:
    idea = _idea(series, pov=True)
    beats = build_beats(idea, series["cast"], pov=True)
    script = inject_cast(normalize_script(beats_to_script(idea, beats, series["cast"], pov=True)), series)
    assert summarise(check_script(script))["passed"]
    sb = normalize_storyboard(compile_storyboard(script))
    findings = summarise(check_storyboard(sb, script))
    assert findings["passed"], [f for f in findings["findings"] if f["severity"] == "blocker"]
    assert (script.get("pov") or {}).get("viewer") == "c1"


def test_cost_plan_and_gate(series: dict, tmp_path: Path) -> None:
    idea = _idea(series)
    script = inject_cast(normalize_script(beats_to_script(idea, build_beats(idea, series["cast"]), series["cast"])), series)
    sb = normalize_storyboard(compile_storyboard(script))
    ledger = CreditLedger(tmp_path / "ledger.jsonl", episode_id="e", cap_cny=1.0)
    plan = build_plan(sb, script, provider="offline", ledger=ledger)
    assert plan["first_segment_only"] is True
    assert plan["aspect"] == "9:16" and plan["resolution"] == "1080x1920"
    assert plan["credits_estimate"] == 0
    assert gate(plan, ledger=ledger)["allowed"]
    plan["estimated_cny"] = 10.0
    assert not gate(plan, ledger=ledger)["allowed"]


def test_text_detector(tmp_path: Path) -> None:
    flat = tmp_path / "flat.png"
    Image.new("RGB", (320, 320), (40, 60, 80)).save(flat)
    assert detect_text_artifacts(flat)["passed"]
    texty = tmp_path / "text.png"
    img = Image.new("RGB", (640, 480), (245, 245, 245))
    draw = ImageDraw.Draw(img)
    draw.text((40, 40), "GARBLED TEXT 123 ERROR", fill=(10, 10, 10))
    draw.text((40, 120), "SUBTITLE MADE OF LETTERS", fill=(10, 10, 10))
    img.save(texty)
    result = detect_text_artifacts(texty)
    assert result["method"] in ("tesseract-tsv", "edge-band-fallback")
    assert not result["passed"]


def _tone(path: Path, freq: float, seconds: float = 1.2) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    f"sine=frequency={freq}:duration={seconds}", str(path)], check=True)
    return path


def test_voice_similarity_same_vs_different(tmp_path: Path) -> None:
    a = _tone(tmp_path / "a.wav", 220)
    b = _tone(tmp_path / "b.wav", 220)
    c = _tone(tmp_path / "c.wav", 880)
    assert voice_similarity(a, b)["passed"]
    assert not voice_similarity(a, c)["passed"]


def test_i18n_no_llm_and_injected_llm(series: dict) -> None:
    edit = {"subtitles": [{"text": "你好", "start_s": 0, "end_s": 1, "kind": "said"}]}
    apply_bilingual(edit, "en")
    assert edit["translation"]["status"] == "llm_unavailable"
    assert edit["subtitles"][0]["secondary"] == "你好"

    class Fake:
        def __call__(self, messages, **kwargs):
            return {"content": '{"0": "Hello"}'}

    edit2 = {"subtitles": [{"text": "你好", "start_s": 0, "end_s": 1, "kind": "said"}]}
    apply_bilingual(edit2, "en", llm=Fake())
    assert edit2["subtitles"][0]["secondary"] == "Hello"
    path = write_srt(edit2, Path("/tmp/s16_i18n.srt"), lang="secondary")
    assert "Hello" in path.read_text(encoding="utf-8")


def test_review_returns_best_genre_and_three_ideas(series: dict) -> None:
    report = review_episodes(series, [
        {"title": "a", "genre": "tsundere", "views": 1000},
        {"title": "b", "genre": "tsundere", "views": 2000},
        {"title": "c", "genre": "magic_backfire", "views": 100},
    ])
    assert report["best_genre"] == "tsundere"
    assert len(report["next_ideas"]) == 3
    assert report["conclusion"]


def test_canvas_tools_thread_state(series: dict, tmp_path: Path) -> None:
    import asyncio

    from hevi.ai_drama.canvas_nodes import ALL_TOOLS, run_canvas_tool

    assert "drama.series_topics" in ALL_TOOLS
    topics = asyncio.run(run_canvas_tool("drama.series_topics", {"topic": "测试", "series": series}, {}))
    assert topics["status"] == "ok"
    beats = asyncio.run(run_canvas_tool("drama.series_beats", {"out_dir": str(tmp_path)}, {"topics": topics}))
    assert beats["status"] == "ok" and len(beats["beats"]) == 5
    draft = beats_to_script(beats["idea"], beats["beats"], CAST)
    script = asyncio.run(run_canvas_tool("drama.stage_script", {
        "out_dir": str(tmp_path), "series": series, "ai_drama_state": {"input": {"script": draft}},
    }, {}))
    assert script["status"] == "ok"
    assert script["ai_drama_state"]["script"]["series_id"] == series["series_id"]


def test_studio_tools_registered() -> None:
    from hevi.studio.tools import get_tool

    for tool_id in ("drama.series_topics", "drama.stage_script", "drama.stage_publish"):
        assert get_tool(tool_id) is not None


def test_render_worker_contract() -> None:
    from hevi.ai_drama.render_worker import (
        DRAMA_RENDER_CLASS,
        describe,
        drama_line_of,
        is_drama_render_task,
    )
    from hevi.tasks.repository import DEFAULT_EXCLUSIVE_RESOURCE_CLASSES, exclusive_resource_classes

    assert DRAMA_RENDER_CLASS in DEFAULT_EXCLUSIVE_RESOURCE_CLASSES
    assert DRAMA_RENDER_CLASS in exclusive_resource_classes()
    assert is_drama_render_task({"resource_class": DRAMA_RENDER_CLASS})
    assert is_drama_render_task({"config_json": {"options": {"line_id": "ai_drama"}}})
    assert not is_drama_render_task({"config_json": {"line_id": "explainer"}})
    assert drama_line_of({"line_id": "ai_drama"}) == "ai_drama"
    assert describe()["resource_class"] == DRAMA_RENDER_CLASS


def test_handdraw_general_topic_does_not_use_kids_template() -> None:
    from hevi.layer4_legacy.handdraw.general_storyboards import (
        build_general_storyboard,
        is_kids_topic,
    )
    from hevi.layer4_legacy.handdraw.line import _match_topic_spec

    assert not is_kids_topic("复利为什么反直觉")
    assert is_kids_topic("小朋友为什么要刷牙")
    spec = _match_topic_spec("复利为什么反直觉", "auto")
    assert spec["audience"] == "general"
    text = json.dumps(spec["pages"], ensure_ascii=False)
    assert "小朋友" not in text
    kids = _match_topic_spec("小朋友为什么要刷牙", "auto")
    assert kids.get("audience") != "general"
    general = build_general_storyboard("城市里的树怎么降温")
    assert len(general["pages"]) == 4


def test_consistency_fails_when_portrait_drifts(tmp_path: Path) -> None:
    from hevi.ai_drama.assets import build_assets

    seeded = create_series(title="s", genre="tsundere", cast=CAST, out_dir=tmp_path / "s")
    idea = _idea(seeded)
    script = normalize_script(beats_to_script(idea, build_beats(idea, CAST), CAST))
    merged = inject_cast(script, seeded)
    assets = annotate_assets(build_assets(merged), seeded)
    anchor = tmp_path / "anchor.png"
    img = Image.new("RGB", (256, 256), (210, 190, 170))
    ImageDraw.Draw(img).rectangle((60, 20, 190, 120), fill=(40, 30, 30))
    img.save(anchor)
    for card in seeded["cast"]:
        card["anchor_image"] = str(anchor)
        card["portrait_image"] = str(anchor)
    identity = next(i for i in assets["images"] if i["kind"] == "character_identity")
    identity["path"] = str(tmp_path / "drift.png")
    Image.new("RGB", (256, 256), (20, 20, 20)).save(identity["path"])
    report = check_episode_consistency(assets, seeded, out_dir=tmp_path)
    assert any(f["rule"] == "C-VISUAL" for f in report["findings"])
