"""Phase B 内化测试: 配方卡 / 动效 StylePack / 节拍网格 / 声音设计 / 判例库 / token。"""

from __future__ import annotations

import pytest

from hevi.motion.beat_sync import (
    BeatSyncError,
    analyze_beat_grid,
    beat_number,
    beat_time,
    fit_beat_grid,
)
from hevi.motion.design_token import (
    DesignTokens,
    normalize_design_tokens,
    validate_tokens,
)
from hevi.motion.motion_stylepack import (
    MOTION_PRESETS,
    motion_voice_check,
    resolve_motion_preset,
)
from hevi.motion.recipe_card import (
    build_seed_library,
    find_card,
    save_library,
    validate_card,
    validate_library,
)
from hevi.motion.sound_design import (
    SfxPin,
    SoundDesign,
    build_bgm_volume_env,
    pick_sound_vocabulary,
    validate_sound_design,
)
from hevi.verdict.aesthetic_canon import (
    AestheticCanon,
    CanonError,
    CanonRule,
    build_self_check_report,
    default_canon,
    validate_canon,
)

# ---- recipe cards ----

def test_seed_library_covers_all_categories():
    from hevi.motion.recipe_card import CARD_CATEGORIES

    lib = build_seed_library()
    cats = set(CARD_CATEGORIES)
    assert len(lib) >= len(cats)
    for cat in cats:
        assert any(c.category == cat for c in lib.values()), cat
    assert validate_library(lib) == []


def test_recipe_card_validation():
    lib = build_seed_library()
    card = lib["spotlight-hero-card"]
    assert card.suggested_duration_s > 0
    assert validate_card(card) == []
    bad = lib["spotlight-hero-card"]
    assert find_card(lib, "spotlight-hero-card") is bad
    with pytest.raises(KeyError):
        find_card(lib, "nope")


def test_recipe_library_roundtrip(tmp_path):
    lib = build_seed_library()
    p = tmp_path / "cards.json"
    save_library(lib, p)
    from hevi.motion.recipe_card import load_library

    loaded = load_library(p)
    assert loaded.keys() == lib.keys()
    assert loaded["row-embed"] == lib["row-embed"]


# ---- motion stylepack ----

def test_motion_presets_resolution():
    assert MOTION_PRESETS
    # 高能活泼 → bold/playful;沉稳严肃 → enterprise
    bold = resolve_motion_preset(energy_axis=1.0, tone_axis=0.5)
    assert bold.name in {"bold", "playful"}
    ent = resolve_motion_preset(energy_axis=-1.0, tone_axis=-1.0)
    assert ent.name == "enterprise"
    named = resolve_motion_preset(energy_axis=0, tone_axis=0, name="luxury")
    assert named.name == "luxury"
    with pytest.raises(KeyError):
        resolve_motion_preset(energy_axis=0, tone_axis=0, name="nope")


def test_motion_voice_check():
    calm = resolve_motion_preset(energy_axis=-1.0, tone_axis=-1.0)
    assert motion_voice_check(calm, ["沉稳", "克制"]) == ""
    assert motion_voice_check(calm, ["高能", "动感"]) != ""
    assert motion_voice_check(MOTION_PRESETS[2], ["活力", "快"]) == ""


# ---- beat sync (pure math) ----

def test_fit_beat_grid_exact():
    # 100 BPM, t0=0.5, 20 拍,加 ±5ms 噪声
    import random

    rng = random.Random(42)
    period = 0.6  # 100 BPM
    times = [0.5 + i * period + rng.uniform(-0.005, 0.005) for i in range(20)]
    grid = fit_beat_grid(times)
    assert grid.bpm == pytest.approx(100.0, abs=0.5)
    assert grid.t0 == pytest.approx(0.5, abs=0.02)
    assert grid.period_s == pytest.approx(0.6, abs=0.005)
    assert grid.residual_ms <= 15.0
    assert grid.trusted


def test_fit_beat_grid_few_beats_raises():
    with pytest.raises(BeatSyncError):
        fit_beat_grid([0.0, 0.6, 1.2])


def test_beat_time_roundtrip():
    grid = fit_beat_grid([0.0 + i * 0.5 for i in range(8)])
    assert beat_time(grid, 3) == pytest.approx(1.5)
    assert beat_number(grid, 1.5) == pytest.approx(3.0)


def test_analyze_beat_grid_missing_file():
    with pytest.raises(BeatSyncError):
        analyze_beat_grid("/nonexistent/bgm.mp3")


# ---- sound design ----

def test_vocabulary_by_piece_type():
    assert "whoosh" in pick_sound_vocabulary("product_promo")
    assert pick_sound_vocabulary("unknown") == pick_sound_vocabulary("product_promo")


def test_sound_design_validation():
    good = SoundDesign(
        sfx_pins=[
            SfxPin(from_frame=10, src="whoosh.wav", volume=0.4, note="hero card"),
            SfxPin(from_frame=120, src="impact.wav", volume=0.5),
        ]
    )
    assert validate_sound_design(good) == []
    bad = SoundDesign(sfx_pins=[SfxPin(from_frame=-1, src="x.wav", volume=1.5)])
    issues = validate_sound_design(bad)
    assert any("volume" in i for i in issues)
    assert any("from_frame" in i for i in issues)
    assert validate_sound_design(SoundDesign(sfx_pins=[])) != []


def test_bgm_volume_env():
    design = SoundDesign(bgm_volume=0.34)
    env = build_bgm_volume_env(total_frames=900, fps=30, design=design)
    assert env[0] == (0.0, 0.0)
    assert env[1][1] == pytest.approx(0.34)  # 1s 淡入完成
    assert env[-1][1] == 0.0  # 片尾淡出


# ---- aesthetic canon ----

def test_canon_numbering_only_appends():
    canon = AestheticCanon()
    canon.add(CanonRule(code="R1", rule="a", precedent="", self_check="q"))
    with pytest.raises(CanonError):
        canon.add(CanonRule(code="R1", rule="b", precedent="", self_check="q"))  # 重号
    canon.add(CanonRule(code="R2", rule="c", precedent="", self_check="q"))  # 追加 OK
    canon.add(CanonRule(code="R3", rule="d", precedent="", self_check="q"))  # R3 > R2 允许
    with pytest.raises(CanonError):
        canon.add(CanonRule(code="R2", rule="e", precedent="", self_check="q"))  # 降序插入禁止
    assert len(canon.by_family("R")) == 3


def test_default_canon_full_report():
    canon = default_canon()
    assert validate_canon(canon) == []
    report = build_self_check_report(canon, {"R1": None, "Q1": "shot_0002/frame 12", "S1": None})
    assert "R1 ✓" in report
    assert "Q1 ✗(shot_0002/frame 12)" in report
    assert "S1 ✓" in report
    assert "Q2 ?" in report  # 未检


def test_canon_roundtrip_json(tmp_path):
    canon = default_canon()
    p = tmp_path / "canon.json"
    canon.save(p)
    loaded = AestheticCanon.load(p)
    assert loaded.rules == canon.rules


# ---- design tokens ----

def test_normalize_tokens():
    raw = {
        "font_families": ["Inter", "Inter"],
        "font_weights": [400, 700],
        "colors": ["#FF0000", "rgb(0, 128, 0)", "#ff0000"],
        "spacing": ["8px", 16],
        "radii": ["4px"],
        "font_sizes": ["14px"],
        "line_heights": [1.5],
    }
    tokens = normalize_design_tokens(raw, source="test")
    assert tokens.font_families == ["Inter"]  # 去重
    assert "#ff0000" in tokens.colors and "#008000" in tokens.colors
    assert 8.0 in tokens.spacing
    assert validate_tokens(tokens) == []


def test_validate_tokens_empty():
    issues = validate_tokens(DesignTokens())
    assert any("font" in i for i in issues)
    assert any("colors" in i for i in issues)
