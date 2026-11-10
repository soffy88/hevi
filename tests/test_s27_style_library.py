"""S27: handraw-style library integration, covers, article planning, locks."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from hevi.ai_drama.style_cards import list_all_style_cards, list_style_cards
from hevi.api.main import app
from hevi.studio import repurpose_s24 as s24
from hevi.style_library import article, catalog, consistency, cover, integrations

LIVING_NAMES = ["Gemma Correll", "Wes Anderson", "Quentin Blake", "几米", "早稻", "蔡皋", "Tango"]


def test_index_counts_and_credit_policy() -> None:
    counts = catalog.counts()
    assert counts["styles"] == 370
    assert counts["layouts"] == 170
    assert counts["colors"] == 36
    assert counts["styles_removed_credit"] == 184
    index = catalog.load_index()
    blob = json.dumps(index, ensure_ascii=False)
    for name in LIVING_NAMES:
        assert name not in blob, name
    # Deceased masters and non-personal labels stay.
    assert catalog.get_style("FA-002")["reference"] == "Saul Steinberg"
    assert catalog.get_style("FI-001")["reference"] == "Apple / 苹果"
    assert catalog.get_style("FA-001")["credit_removed"] is True
    assert catalog.get_style("FA-001")["reference"] == ""


def test_search_by_id_name_category_and_use_case() -> None:
    by_id = catalog.search("styles", query="FA-001", limit=5)
    assert by_id["styles"][0]["id"] == "FA-001"
    by_legacy = catalog.search("styles", query="001", limit=10)
    assert any(s["id"] == "FA-001" for s in by_legacy["styles"])
    by_cat = catalog.search("styles", category="FE", limit=500)
    assert by_cat["total"] == 68
    by_use = catalog.search("layouts", use_case="知识讲解", limit=500)
    assert by_use["total"] > 0
    layouts = catalog.search("layouts", category="comic-storyboard", limit=500)
    assert layouts["total"] == 71
    colors = catalog.search("colors", limit=100)
    assert colors["total"] == 36


def test_recommend_is_deterministic_and_explains_itself() -> None:
    one = catalog.recommend("孩子睡前为什么怕黑")
    two = catalog.recommend("孩子睡前为什么怕黑")
    assert one["style"]["id"] == two["style"]["id"]
    assert one["locked"]["style_id"] == one["style"]["id"]
    assert one["reason"].strip()
    assert one["theme_color"]["id"].startswith("C-")


def test_selector_is_offline_and_attributed() -> None:
    html = catalog.selector_html()
    assert "yang0/handraw-style" in html
    assert "FA-001" in html
    assert "<script src=" not in html  # no network dependency
    assert len(html) < 200_000


def test_theme_palette_contrast() -> None:
    for color_id in ("C-01", "C-15", "C-27", "C-30", "C-32"):
        pal = catalog.theme_palette(color_id)
        assert pal["accent"].startswith("#")
        assert pal["background"] != pal["ivory"]
        assert pal["gold"] != pal["background"]


def test_cover_plan_and_three_sizes(tmp_path: Path) -> None:
    source = {
        "title": "为什么越催孩子越慢",
        "shots": [
            {"big": "催，是把孩子的时钟拨快", "small": "你越急，他越不知道先做哪一步。"},
            {"big": "先让他自己说出下一步", "small": "时间感是练出来的，不是催出来的。"},
        ],
        "summary": "孩子的时间感和优先级还在长；催促只会把选择变得更多。",
    }
    plan = cover.plan_cover(source, style_id="FB-001", theme_color_id="C-30")
    assert plan["summary"]
    assert plan["audience"]
    assert plan["metaphor"]
    assert plan["title"]
    manifest = cover.render_covers(plan, tmp_path)
    assert set(manifest["covers"]) == {"9:16", "3:4", "16:9"}
    assert manifest["ok"] is True
    for path in manifest["covers"].values():
        assert Path(path).is_file()
        with Image.open(path) as img:
            assert img.width > 0 and img.height > 0


def test_article_plan_and_export(tmp_path: Path) -> None:
    md = """# 平均工资涨了，为什么你更穷

平均工资被少数高薪拉高，中位数几乎不动。

## 第一个原因：你在的分位数没变
分布是长尾的，平均数对极端值敏感。

## 第二个原因：生活成本结构不同
房租、教育和医疗的涨幅不是同一张表。

## 怎么做
先看中位数和行业分位，再看平均数。
"""
    plan = article.plan_article(md, style_id="FA-001", theme_color_id="C-03", points=3)
    assert 2 <= len(plan["slots"]) <= 5
    assert len({s["layout"]["id"] for s in plan["slots"]}) >= 1
    manifest = article.export_article(md, tmp_path, style_id="FA-001", theme_color_id="C-03")
    assert Path(manifest["markdown"]).is_file()
    assert Path(manifest["wechat_html"]).is_file()
    assert len(manifest["images"]) == len(plan["slots"])
    html = Path(manifest["wechat_html"]).read_text(encoding="utf-8")
    assert "data:image/png;base64," in html
    assert "yang0" not in html  # data source credited elsewhere, not inside body copy


def test_drift_check_flags_outlier_and_plans_only_that_frame(tmp_path: Path) -> None:
    frames = []
    for i, rgb in enumerate([(20, 20, 20), (22, 22, 22), (240, 230, 210)]):
        path = tmp_path / f"f{i}.png"
        Image.new("RGB", (160, 90), rgb).save(path)
        frames.append(path)
    report = consistency.check_frames(frames, threshold=0.1, seconds_per_frame=1 / 24)
    assert report["method"] == "color_only"
    assert report["rerender"] == [2]
    plan = consistency.plan_rerender(report)
    assert plan["frame_count"] == 1
    assert plan["runs"][0]["start_frame"] == 2


def test_handdraw_accepts_library_style_and_theme(tmp_path: Path) -> None:
    from hevi.layer4_legacy.handdraw.illustrator import build_scene_illustration

    path = tmp_path / "fa001.png"
    meta = build_scene_illustration(
        "growth_curves", path, style_id="FA-001", size=(400, 400), theme_color_id="C-05"
    )
    assert path.is_file()
    assert meta["style_id"] == "FA-001"
    assert meta["base_recipe"] == "1"
    assert meta["theme_color_id"] == "C-05"


def test_comic_style_and_layout_routing() -> None:
    preset = integrations.comic_style("FE-001", "C-15")
    assert preset.name == "hw_FE-001"
    assert "Cinnabar" in preset.style_tokens or "theme color" in preset.style_tokens
    assert integrations.layout_for_stage("storyboard")["id"] == "SB-001"
    assert integrations.layout_for_stage("knowledge")["category"] == "infographic"


def test_ai_drama_merge_keeps_eight_builtins_and_adds_library() -> None:
    builtin = list_style_cards()
    merged = list_all_style_cards()
    assert len(builtin) == 8
    assert len(merged) == 8 + 370
    ids = [card["id"] for card in merged]
    assert len(ids) == len(set(ids))
    library = next(card for card in merged if card["id"] == "hw_FA-001")
    assert library["source"] == "handraw"
    assert library["available"] is False


def test_canvas_style_lock_touches_only_visual_nodes() -> None:
    nodes = [
        {"node_id": "script", "node_type": "text", "config": {"text": "稿子"}},
        {"node_id": "img", "node_type": "image", "config": {}},
        {"node_id": "video", "node_type": "video", "config": {"prompt": "x"}},
    ]
    out = integrations.apply_style_to_nodes(nodes, style_id="FA-001", theme_color_id="C-05")
    assert out["affected"] == ["img", "video"]
    assert out["nodes"][0]["config"] == {"text": "稿子"}
    assert out["nodes"][1]["config"]["style_lock"]["style_id"] == "FA-001"


def test_s24_uses_library_theme_and_layout(tmp_path: Path) -> None:
    manifest = s24.export_text_pack(
        title="测试",
        sections=[{"heading": "一", "body": "正文。"}, {"heading": "二", "body": "第二段。"}],
        out_dir=tmp_path,
        theme="C-05",
        layout_id="SC-016",
    )
    assert manifest["layout"]["id"] == "SC-016"
    assert manifest["library_color_id"] == "C-05"
    assert Path(manifest["paths"]["long_image"]).is_file()


def test_warmgold_themed_palette(tmp_path: Path) -> None:
    script = {
        "bpm": 120,
        "shots": [
            {"id": "s1", "beats": 4, "big": "一句话", "small": "解释。", "visual": "gauge"},
        ],
    }
    themed = integrations.warmgold_script(script, theme_color_id="C-15", layout_id="IG-009")
    assert themed["palette"]["accent"] != "#C8A96A"
    assert themed["layout_id"] == "IG-009"
    assert themed["style_lock"]["theme_color_id"] == "C-15"


def test_public_api_endpoints() -> None:
    client = TestClient(app)
    assert client.get("/api/style-library/meta").status_code == 200
    res = client.get("/api/style-library/search", params={"q": "FA-001"})
    assert res.status_code == 200
    assert res.json()["styles"][0]["id"] == "FA-001"
    selector = client.get("/api/style-library/selector")
    assert selector.status_code == 200
    assert "yang0/handraw-style" in selector.text
    preview = client.get("/api/style-library/preview/FA-001.svg")
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/svg+xml")
    rec = client.get("/api/style-library/recommend", params={"topic": "孩子怕黑"})
    assert rec.status_code == 200
    assert rec.json()["reason"]
