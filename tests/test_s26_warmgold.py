"""S26：暖黑金图解 —— 零件、逐拍自检、拆对标、制作记忆、渲染预算、API。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hevi.api.main import app
from hevi.auth.dependencies import get_current_user
from hevi.explainer.warmgold import (
    beats,
    memory,
    parts,
    reference,
    render,
    scriptcheck,
    style,
    template,
)
from hevi.studio import tools as studio_tools
from hevi.studio.formats import FORMAT_BY_ID, resolve_format

ROOT = Path(__file__).resolve().parents[1]
SFX = ROOT / "assets" / "audio" / "sfx" / "ding.wav"


# ── 风格卡与零件库 ─────────────────────────────────────────────────────────


def test_style_card_colors_and_safety() -> None:
    card = style.style_card()
    assert card["id"] == "warm_gold_diagram"
    assert card["palette"]["background"].startswith("#")
    assert card["safety"] == {
        "top": 150,
        "bottom": 380,
        "right": 140,
        "left": 60,
        "width": 1080,
        "height": 1920,
    }
    assert style.inside_safe(540, 900)
    assert not style.inside_safe(1000, 900)  # 右安全区
    assert not style.inside_safe(540, 1600)  # 底安全区


def test_parts_library_has_at_least_eight_and_is_deterministic() -> None:
    assert len(parts.PARTS) >= 8
    for part in parts.PARTS:
        assert part.six_lines()["要证明的变化"]
        assert part.six_lines()["只改的条件"]
        one = parts.draw(part.id, {"seed": 5}, 0.55)
        two = parts.draw(part.id, {"seed": 5}, 0.55)
        assert one["items"] == two["items"]
        assert one["part_id"] == part.id
        assert one["sim_note"] in ("一次模拟", "示意")


def test_style_card_assets_exist() -> None:
    asset = ROOT / "assets" / "style_cards"
    assert (asset / "warm_gold.json").is_file()
    assert (asset / "warm_gold_cover.jpg").is_file()
    assert (asset / "warm_gold_makeup.jpg").is_file()
    manifest = json.loads((asset / "warm_gold_parts.json").read_text(encoding="utf-8"))
    assert manifest["count"] == len(parts.PARTS)


def test_warm_gold_substyle_is_registered_internal() -> None:
    fmt = FORMAT_BY_ID["explainer"]
    ids = [s.id for s in fmt.styles]
    assert "warm_gold" in ids
    assert fmt.default_style != "warm_gold"  # 黑盒通过前不做默认
    resolved = resolve_format(format_id="explainer", style_id="warm_gold", line_id=None, slots={})
    assert resolved["line_id"] == "warm_gold"
    assert resolved["style"] == "warm_gold"


# ── 逐拍 ───────────────────────────────────────────────────────────────────


def test_virtual_beats_and_beat_fields() -> None:
    script = template.build_10s("越着急，越看不清")
    data = beats.build_beats(script)
    assert data["source"] == "virtual"
    assert data["beats"]
    first = data["beats"][0]
    for key in ("bar", "beat", "t", "duration", "shot_id", "visual", "big", "small", "sfx"):
        assert key in first
    assert data["total_s"] > 0


def test_music_analysis_on_short_sfx() -> None:
    data = beats.analyze_music(SFX)
    assert data["bpm"] > 0
    assert data["beat_s"] > 0
    assert len(data["beats"]) >= 2
    assert data["source"] in ("measured", "estimate")


# ── 脚本自检 ───────────────────────────────────────────────────────────────


def _check(script: dict) -> dict:
    data = beats.build_beats(script)
    return scriptcheck.check_script(script, data, music_present=False)


def test_template_10s_passes_self_check() -> None:
    result = _check(template.build_10s("越着急，越看不清"))
    assert result["pass"], result["issues"]


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda s: s["shots"][0].update({"big": "你" * 60}), "S04"),
        (lambda s: s["shots"][0].update({"narration": "开场没有第二人称"}), "S10"),
        (lambda s: s.update({"anchor": {"object": "市场", "daily": True}}), "S11"),
        (lambda s: s["ending"].update({"cta": "like"}), "S07"),
        (lambda s: s["shots"][1].update({"small": "屏幕数字 42 没有出处"}), "S15"),
        (lambda s: s["shots"][0].update({"small": "保证你一定成功"}), "S09"),
        (lambda s: s["shots"][1].update({"example": {"visible_reading": "x"}}), "S05"),
    ],
)
def test_self_check_catches_each_failure(mutate, code) -> None:
    script = template.build_10s("越着急，越看不清")
    mutate(script)
    result = _check(script)
    assert not result["pass"]
    assert any(i["code"] == code for i in result["issues"]), result["issues"]


def test_banned_phrase_ngram_check() -> None:
    banned = ["你有没有过这种时候：三条队，你偏偏选了最慢的那条"]
    hit = scriptcheck.check_banned_phrases(
        "你有没有过这种时候：三条队，你偏偏选了最慢的那条。", banned
    )
    assert not hit["pass"] and hit["hits"][0]["exact"]
    clean = scriptcheck.check_banned_phrases("今天讲一个完全不同的抽样问题。", banned)
    assert clean["pass"]


# ── 拆对标 ─────────────────────────────────────────────────────────────────


def test_reference_ratios_use_user_provided_evidence(tmp_path: Path) -> None:
    payload = {
        "rights_declared": True,
        "interactions": {"likes": 1000, "shares": 400, "saves": 100, "comments": 20},
        "top_comments": ["每次都是我这条最慢"],
        "our_direction": "排队慢是抽样偏差，不是运气",
        "anchor": "收银台",
        "anchor_daily": True,
        "contrast": "你只看得见自己这条",
        "psych_chain": ["被说中", "想起谁", "卸下什么", "想做什么"],
    }
    report = reference.decompose(payload, tmp_path)
    assert report["coverage"]["video"] is False
    assert report["interactions"]["ratios"]["share_per_like"]["value"] == 0.4
    assert report["interactions"]["ratios"]["share_per_like"]["evidence"] == "用户提供"
    assert report["interactions"]["audience_use"]["use"] == "share"
    assert report["requires_confirmation"] is True
    json_path, html_path = reference.write_report(report, tmp_path)
    assert json_path.is_file() and html_path.is_file()


def test_reference_confirmation_gate() -> None:
    report = {"requires_confirmation": True}
    with pytest.raises(PermissionError):
        reference.require_confirmation(report, False)
    reference.require_confirmation(report, True)


def test_reference_requires_rights_declared_via_api() -> None:
    app.dependency_overrides[get_current_user] = lambda: {"id": "s26-test"}
    try:
        client = TestClient(app)
        r = client.post("/api/explainer/warmgold/reference", json={"payload": {"video_path": "x"}})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_user, None)


# ── 制作记忆 ───────────────────────────────────────────────────────────────


def test_memory_quotes_rules_and_injection(tmp_path: Path) -> None:
    memory.add_quote("u1", "warm_gold", "开头别喊口号，用我正在做的事", root=tmp_path)
    draft = memory.add_rule("u1", "warm_gold", "金字不要铺面", confirmed=False, root=tmp_path)
    assert draft["written"] is False
    memory.add_rule("u1", "warm_gold", "金字只画线", confirmed=True, root=tmp_path)
    memory.write_diary("u1", "warm_gold", episode="ep1", did="渲染第一版", root=tmp_path)
    block = memory.inject("u1", "warm_gold", root=tmp_path)
    assert "开头别喊口号" in block
    assert "金字只画线" in block
    assert "金字不要铺面" not in block
    assert memory.list_memory("u1", "warm_gold", root=tmp_path)["diary"][0]["did"] == "渲染第一版"


def test_memory_update_requires_confirmation(tmp_path: Path) -> None:
    entry = memory.add_quote("u1", "warm_gold", "原话", root=tmp_path)
    with pytest.raises(PermissionError):
        memory.update_entry(
            "u1", "warm_gold", entry["id"], text="改", root=tmp_path, confirmed=False
        )
    updated = memory.update_entry(
        "u1", "warm_gold", entry["id"], text="改", root=tmp_path, confirmed=True
    )
    assert updated["quote"] == "改"


# ── 渲染预算 ───────────────────────────────────────────────────────────────


def test_frame_plan_and_layout_checks() -> None:
    script = template.build_10s("越着急，越看不清")
    data = beats.build_beats(script)
    plan = render._frame_plan(data, 24)
    assert plan and plan[0]["i"] == 0
    assert all("span" in frame for frame in plan)
    issues = render._layout_issues(plan)
    assert not any(i["code"] == "R02" for i in issues)


def test_preflight_fails_on_bad_script() -> None:
    script = template.build_10s("越着急，越看不清")
    script["shots"][0]["big"] = "你" * 60
    data = beats.build_beats(script)
    result = render.preflight(script, data, Path("/tmp"))
    assert result["pass"] is False


# ── API / 工具注册 ─────────────────────────────────────────────────────────


def test_warmgold_tools_registered() -> None:
    ids = {spec.tool_id for spec in studio_tools.list_tools()}
    assert {
        "explainer.reference_breakdown",
        "explainer.beat_check",
        "explainer.warmgold_render",
    } <= ids


def test_api_parts_check_and_template() -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "s26-test",
        "email": "s26@example.com",
    }
    try:
        client = TestClient(app)
        parts_resp = client.get("/api/explainer/warmgold/parts")
        assert parts_resp.status_code == 200
        assert parts_resp.json()["count"] >= 8

        tpl = client.post(
            "/api/explainer/warmgold/template10", json={"sentence": "越着急，越看不清"}
        )
        assert tpl.status_code == 200
        assert tpl.json()["check"]["pass"] is True

        bad = template.build_10s("越着急，越看不清")
        bad["shots"][0]["big"] = "你" * 60
        check = client.post("/api/explainer/warmgold/check", json={"script": bad})
        assert check.status_code == 200
        assert check.json()["pass"] is False

        render_resp = client.post("/api/explainer/warmgold/render", json={"script": bad})
        assert render_resp.status_code == 422
    finally:
        app.dependency_overrides.pop(get_current_user, None)
