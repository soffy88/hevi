"""S18 style cards: eight self-made cards wired into series selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.ai_drama.assets import build_assets
from hevi.ai_drama.series import (
    character_sheet_markdown,
    create_series,
    inject_cast,
    makeup_shot_prompt,
    series_findings,
)
from hevi.ai_drama.style_cards import (
    STYLE_CARDS,
    apply_style_card,
    get_style_card,
    list_style_cards,
    style_prompt_for,
)

AST = {"id": "c1", "name": "阿澈", "body": "瘦高", "hair": "短发", "hair_part": "三七分",
       "eye_color": "深棕", "signature_detail": "左眼下小痣",
       "outfit": {"top": "白衬衫", "bottom": "深色长裤", "shoes": "黑皮鞋"},
       "outfits": [{"top": "白衬衫", "bottom": "深色长裤", "material": "棉", "color": "白",
                    "length": "常规", "shoes": "黑皮鞋"}],
       "accessories": ["细手绳"], "personality": "嘴硬心软",
       "voice": {"description": "偏低", "tts_params": {"pitch": -1}}}


def test_eight_builtin_cards_have_cover_and_makeup() -> None:
    assert len(STYLE_CARDS) == 8
    cards = list_style_cards()
    assert {card["id"] for card in cards} == {card["id"] for card in STYLE_CARDS}
    for card in cards:
        assert card["style_prompt"].strip()
        assert card["negative_prompt"].strip()
        assert len(card["palette"]) >= 3
        assert card["cover_path"] and Path(card["cover_path"]).is_file(), card["id"]
        assert card["makeup_path"] and Path(card["makeup_path"]).is_file(), card["id"]
        assert card["available"] is True


def test_apply_card_sets_reusable_prompt_and_references() -> None:
    series = create_series(title="卡片测试", genre="daily", cast=[AST], out_dir="/tmp/s18-card", style_card="anime_cel")
    assert series["style_card"] == "anime_cel"
    assert series["style"] == "anime_cel"
    assert "cel-shaded" in series["style_prompt"]
    assert Path(series["style_cover"]).is_file()
    assert Path(series["style_makeup_reference"]).is_file()
    assert series["style_palette"]
    assert style_prompt_for(series) == series["style_prompt"]
    # The style card itself must not raise a finding (character-bible findings
    # from the minimal test card are a different rule and out of scope here).
    assert not [f for f in series_findings({"characters": []}, series) if f["rule"] == "C-STYLE"]


def test_unknown_card_raises() -> None:
    series = create_series(title="x", genre="daily", cast=[AST], out_dir="/tmp/s18-card2")
    with pytest.raises(KeyError):
        apply_style_card(series, "does_not_exist")
    assert get_style_card("does_not_exist") is None


def test_episode_script_and_assets_carry_style_prompt() -> None:
    series = create_series(title="注入测试", genre="daily", cast=[AST], out_dir="/tmp/s18-card3",
                           style_card="guofeng_ink")
    script = {"style": series["style"], "characters": [{"id": "c1", "name": "阿澈"}]}
    merged = inject_cast(script, series)
    assert merged["style_card"] == "guofeng_ink"
    assert "ink wash" in merged["style_prompt"]
    assets = build_assets(merged)
    assert assets["style_prompt"] == merged["style_prompt"]
    assert any("ink wash" in str(img.get("render_prompt")) for img in assets["images"])


def test_character_sheet_lists_style_card_and_makeup_reference(read_series_fixture=None) -> None:
    series = create_series(title="设定集", genre="daily", cast=[AST], out_dir="/tmp/s18-card4",
                           style_card="retro_film")
    md = character_sheet_markdown(series)
    assert "风格卡" in md
    assert "复古胶片写实" in md
    assert "平光定妆参考" in md
    card = series["cast"][0]
    shot = makeup_shot_prompt(card, get_style_card("retro_film"))
    assert "35mm" in shot["render_prompt"]
    assert "画风" in shot["prompt"]
