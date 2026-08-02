"""3O §3 Task 3.1:oskill.match_score_calculator(Hevi 侧暂驻)对位校验算法单测。

纯算法、stateless、确定性:同一输入恒得同一输出。
"""

from __future__ import annotations

from hevi.sourcing.match_score import calculate_stock_match_score


def test_perfect_semantic_match():
    meta = {"title": "夜雨中的古城墙", "description": "士兵举着火把", "tags": ["城墙", "夜雨"]}
    score = calculate_stock_match_score("夜雨中的古城墙,士兵举着火把", meta)
    assert score >= 0.2  # 语义有实质重合(标题/描述/标签命中)


def test_unrelated_scores_low():
    meta = {"title": "蓝天白云下的海滩", "description": "海浪与椰子树", "tags": ["海滩"]}
    score = calculate_stock_match_score("夜雨中的古城墙,士兵举着火把", meta)
    assert score < 0.3


def test_style_pack_keywords_boost():
    meta = {"title": "古城墙夜景", "tags": ["城墙"]}
    without = calculate_stock_match_score("夜雨中的古城墙", meta)
    with_kw = calculate_stock_match_score(
        "夜雨中的古城墙", meta, style_pack_keywords=["古城", "夜雨", "写实"]
    )
    assert with_kw >= without  # 关键词命中只增不减


def test_empty_inputs_return_zero():
    assert calculate_stock_match_score("", {}) == 0.0
    assert calculate_stock_match_score("   ", {"title": "x"}) == 0.0


def test_deterministic():
    meta = {"title": "古城墙", "tags": ["城墙"]}
    a = calculate_stock_match_score("夜雨古城墙", meta, style_pack_keywords=["古城"])
    b = calculate_stock_match_score("夜雨古城墙", meta, style_pack_keywords=["古城"])
    assert a == b


def test_score_bounded():
    meta = {"title": "abc", "description": "abc abc abc", "tags": ["abc"]}
    s = calculate_stock_match_score("abc", meta, style_pack_keywords=["abc", "def"])
    assert 0.0 <= s <= 1.0
