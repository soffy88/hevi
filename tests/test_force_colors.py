"""勢力色注册表测试 —— SPEC §6.2 五规则 + G0 撞色修正(裁决 2026-07-21)。"""

import pytest

from hevi.tongjian.force_colors import (
    ForceColor,
    all_force_ids,
    check_same_screen_clash,
    get_force_color,
)


def test_get_and_rgb():
    han = get_force_color("han")
    assert han.name == "韩"
    assert han.hex == "#e06040"
    assert han.rgb == (224, 96, 64)


def test_unknown_force_raises_not_silent():
    # §6.2a:未登记不许静默造色
    with pytest.raises(KeyError):
        get_force_color("wu")


def test_successor_explicit():
    # §6.2c 继承显式:韩赵魏 successor_of 晋
    for fid in ("han", "zhao", "wei"):
        assert get_force_color(fid).successor_of == "jin"


def test_g0_fix_wei_no_longer_clashes_with_qi():
    # 裁决 6.2b:魏原深绿与齐绿撞色 → 改赭黄/金后同屏不撞
    assert get_force_color("wei").hex != "#4a8050"
    assert check_same_screen_clash(["wei", "qi"]) == []


def test_g0_fix_wei_clears_chu_orange_brown():
    # 修正取亮金而非暗赭,同时避开楚橙棕
    assert check_same_screen_clash(["wei", "chu"]) == []


def test_three_partition_colors_mutually_distinct():
    # 韩赵魏三分治色须两两可辨(B1a/B2 坐标锚定的前提)
    assert check_same_screen_clash(["han", "zhao", "wei"]) == []


def test_tier_budget_focus_colors_le_8():
    # §6.2d:高饱和主色(tier0)预算 ≤ 6–8
    tier0 = [f for f in all_force_ids() if get_force_color(f).tier == 0]
    assert len(tier0) <= 8


def test_clash_checker_surfaces_residual_qin_chu():
    # checker 的价值 = 如实暴露残留撞色(秦/楚 皆土色,设计性近撞,另议)
    clashes = check_same_screen_clash(["qin", "chu"])
    assert clashes and clashes[0][2] < 60  # 被暴露,不被隐藏


def test_model_shape():
    fc = ForceColor(force_id="x", name="X", hex="#010203")
    assert fc.rgb == (1, 2, 3)
    assert fc.tier == 0
