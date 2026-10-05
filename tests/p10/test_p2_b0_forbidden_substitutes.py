"""P2-B0 守卫:「禁止替代物」有了唯一的 canonical 判定原语。

审计结论:`forbidden_substitutes` 在 `p0/p1 VisualIntent` 里被声明、被赋值,
**全仓 0 个读取点**,`KNOWN_CONSTRAINTS` 与 `check_compatibility` 都没有它。
即一条已定义、从未执行的产品约束。

B0 把它接进 canonical compatibility seam,owner = p7。
本文件锁死四件事:

1. **owner 是 p7**,不是 p0/p1 —— 它们只是上游声明者;
2. **负向语义**:`substitute_kind` 落在禁止集合里 = 阻塞;
3. **fail-closed**:素材不自报 `substitute_kind` = **不可判定**(不是通过);
4. **零 blast radius**:没有 requirement 声明这条约束时,seam 行为完全不变。

以及 fail-OPEN 缺口:畸形取值必须在**构造期**失败,否则打错字符的
「禁止」会静默变成「允许」。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hevi.production.p7.asset_contract import AssetSemanticRole, MediaType
from hevi.production.p7.asset_requirement import (
    FORBIDDEN_SUBSTITUTES_SEPARATOR,
    KNOWN_CONSTRAINTS,
    AssetRequirement,
)
from hevi.production.p7.constraint_check import (
    OBSERVED_TO_CONSTRAINT,
    check_compatibility,
    check_forbidden_substitutes,
)

REPO = Path(__file__).resolve().parents[2]

#: p0/p1 VisualIntent 现在声明的真实值,逐字复制 —— 语义由它们定义。
P0_DECLARED = ("generic_stars", "title_card_only", "large_explanatory_text")
DECLARED_VALUE = FORBIDDEN_SUBSTITUTES_SEPARATOR.join(P0_DECLARED)


def _req(*, declare: bool = True, value: str = DECLARED_VALUE) -> AssetRequirement:
    constraints = (("forbidden_substitutes", value),) if declare else ()
    return AssetRequirement(media_type=MediaType.VIDEO,
                            semantic_role=AssetSemanticRole.SCENE,
                            constraints=constraints)


# ── 1. owner 是 p7 ──
def test_b0_constraint_key_is_registered_in_p7():
    assert "forbidden_substitutes" in KNOWN_CONSTRAINTS
    assert _req().unknown_constraints() == ()


def test_b0_seam_maps_the_provenance_field_to_the_constraint():
    """`substitute_kind` 是 provenance 事实,映射到禁止约束。"""
    assert OBSERVED_TO_CONSTRAINT["substitute_kind"] == "forbidden_substitutes"


def test_b0_substitute_kind_is_not_a_byte_probe_field():
    """不得污染字节观测词汇 —— 那个集合由 AST 守卫守着,且语义不同。"""
    from hevi.artifact.probes import OBSERVABLE_FIELDS

    assert "substitute_kind" not in OBSERVABLE_FIELDS, (
        "B0_DRIFT: substitute_kind 是 provenance(谁产出),不是字节探测事实")


def test_b0_owner_is_p7_not_the_intent_layer():
    """p0/p1 只声明;p7 拥有语义与判定。"""
    p7_dir = REPO / "hevi" / "production" / "p7"
    combined = "\n".join(p.read_text(encoding="utf-8")
                          for p in sorted(p7_dir.glob("*.py")))
    assert "check_forbidden_substitutes" in combined
    # 判定原语不得出现在 p0 —— 它是 canonical 层的事
    assert "check_forbidden_substitutes" not in (
        REPO / "hevi" / "production" / "p0_pipeline.py").read_text(encoding="utf-8")


def test_b0_p0_declaration_is_still_untouched():
    """B0 不改 p0/p1 的声明点 —— 接线是后续 slice 的事。"""
    p0 = (REPO / "hevi" / "production" / "p0_pipeline.py").read_text(encoding="utf-8")
    assert 'forbidden_substitutes=("generic_stars", "title_card_only", "large_explanatory_text")' \
        in p0


# ── 2. 负向语义 ──
@pytest.mark.parametrize("kind", P0_DECLARED)
def test_b0_forbidden_kind_is_blocked(kind):
    report = check_compatibility(_req(), {"substitute_kind": kind})
    assert report.blocked_keys == ("forbidden_substitutes",)
    assert report.compatible is False, "被禁止的替代物绝不能 compatible"


@pytest.mark.parametrize("kind", ["real_footage", "screencast", "interview", "aerial"])
def test_b0_allowed_kind_passes(kind):
    report = check_compatibility(_req(), {"substitute_kind": kind})
    assert report.blocked_keys == ()
    assert report.undecidable_keys == ()
    assert report.compatible is True


def test_b0_blocking_outcome_records_both_sides():
    """阻塞必须留下「期望」与「实测」,否则事后无法审计为什么被拒。"""
    report = check_compatibility(_req(), {"substitute_kind": "generic_stars"})
    outcome = next(o for o in report.outcomes if o.key == "forbidden_substitutes")
    assert outcome.expected == DECLARED_VALUE
    assert outcome.observed == "generic_stars"
    assert outcome.satisfied is False
    assert outcome.blocking is True
    assert "generic_stars" in str(outcome.to_dict())


# ── 3. fail-closed ──
@pytest.mark.parametrize("observed", [{}, {"substitute_kind": None}, {"substitute_kind": ""},
                                      {"substitute_kind": "   "}])
def test_b0_missing_self_report_is_undecidable_not_a_pass(observed):
    """**B0 的核心**。素材不自报种类 → 不可判定 → 拒绝,而不是默认放行。

    这是与 `artifact_exists == success` 同类的陷阱:「没说不」被当成「说是」。
    """
    report = check_compatibility(_req(), observed)
    assert report.blocked_keys == ()
    assert report.undecidable_keys == ("forbidden_substitutes",)
    assert report.compatible is False, (
        "缺 substitute_kind 必须 fail-closed;放行等于没有这条约束")
    outcome = next(o for o in report.outcomes if o.key == "forbidden_substitutes")
    assert outcome.satisfied is None
    assert outcome.blocking is False, "不可判定不是「阻塞」,但 compatible 已为 False"


def test_b0_undecidable_and_blocked_are_distinguishable():
    undecidable = check_compatibility(_req(), {})
    blocked = check_compatibility(_req(), {"substitute_kind": "generic_stars"})
    assert undecidable.compatible is blocked.compatible is False
    assert undecidable.undecidable_keys and not undecidable.blocked_keys
    assert blocked.blocked_keys and not blocked.undecidable_keys


def test_b0_predicate_returns_none_when_nothing_declared():
    assert check_forbidden_substitutes(DECLARED_VALUE, None) is None
    assert check_forbidden_substitutes(DECLARED_VALUE, "") is None


def test_b0_predicate_is_order_and_whitespace_insensitive_on_the_forbidden_side():
    reordered = FORBIDDEN_SUBSTITUTES_SEPARATOR.join(reversed(P0_DECLARED))
    assert check_forbidden_substitutes(reordered, "title_card_only") is False
    assert check_forbidden_substitutes(reordered, "real_footage") is True


def test_b0_predicate_does_not_match_by_substring():
    """`star` 不得因为 `generic_stars` 含 `star` 而被误判为禁止项。"""
    assert check_forbidden_substitutes(DECLARED_VALUE, "star") is True
    assert check_forbidden_substitutes(DECLARED_VALUE, "stars") is True


# ── 4. 零 blast radius ──
def test_b0_requirement_without_the_constraint_is_unaffected():
    """没有声明这条约束时,seam 不得凭空多出 outcome。"""
    report = check_compatibility(_req(declare=False), {})
    assert report.outcomes == ()
    assert report.compatible is True, "未声明的约束不得产生任何判定"


def test_b0_existing_constraints_still_work_alongside():
    requirement = AssetRequirement(
        media_type=MediaType.VIDEO, semantic_role=AssetSemanticRole.SCENE,
        constraints=(("query", "black hole"),
                     ("forbidden_substitutes", DECLARED_VALUE),
                     ("duration", "4.0")))
    report = check_compatibility(requirement, {"substitute_kind": "real_footage",
                                               "duration": 5.0})
    assert report.compatible is True
    keys = {o.key for o in report.outcomes}
    assert keys == {"forbidden_substitutes", "duration"}, "query 是检索意图,不是判定项"


def test_b0_reader_returns_declared_values_in_order():
    assert _req().forbidden_substitutes() == P0_DECLARED
    assert _req(declare=False).forbidden_substitutes() == ()


def test_b0_content_hash_covers_the_constraint():
    """约束必须进 fingerprint —— 否则「换了约束」与「没换」无法区分。"""
    assert _req().content_hash() != _req(declare=False).content_hash()
    assert _req(value="generic_stars").content_hash() != _req().content_hash()


# ── 5. fail-OPEN 缺口:畸形取值必须构造期失败 ──
@pytest.mark.parametrize("value", [
    "",                                  # 空
    "generic_stars,",                    # 尾随分隔符
    ",generic_stars",                    # 前导分隔符
    "generic_stars,,title_card_only",    # 空 token
    "Generic_Stars",                     # 大写
    "generic stars",                     # 空格
    "generic-stars",                     # 非法字符
    "generic_stars;title",               # 错误分隔符
    "标题卡",                             # 非 ASCII
])
def test_b0_malformed_value_fails_at_construction(value):
    """静默丢弃畸形 token 会把「禁止」变成「允许」—— 必须在构造期拒绝。"""
    with pytest.raises(ValueError, match="FORBIDDEN_SUBSTITUTE"):
        _req(value=value)


def test_b0_malformed_value_is_not_silently_dropped():
    """反证:若解析器容错,这一条会通过 —— 它是本守卫存在的原因。"""
    try:
        parsed = AssetRequirement(
            media_type=MediaType.VIDEO, semantic_role=AssetSemanticRole.SCENE,
            constraints=(("forbidden_substitutes", "Generic_Stars,real_footage"),)
        ).forbidden_substitutes()
    except ValueError:
        return  # 期望路径
    raise AssertionError(
        f"B0_FAIL_OPEN: 畸形取值被静默解析成 {parsed!r};"
        " 'Generic_Stars' 被丢弃 = 禁止项消失 = fail-OPEN")


def test_b0_valid_values_round_trip():
    for value in (DECLARED_VALUE, "generic_stars", "a", "x_1-y".replace("-", "_")):
        assert _req(value=value).forbidden_substitutes() == tuple(value.split(","))


# ── 6. 守卫是可失败的,不是装饰 ──
def test_b0_guard_detects_a_missing_checker(monkeypatch):
    """把 checker 摘掉 → seam 必须变成「不可判定」而不是「通过」。"""
    from hevi.production.p7 import constraint_check as cc

    monkeypatch.delitem(cc._CHECKS, "forbidden_substitutes")
    report = cc.check_compatibility(_req(), {"substitute_kind": "generic_stars"})
    assert report.compatible is False, "checker 缺失时不得放行"
    outcome = next(o for o in report.outcomes if o.key == "forbidden_substitutes")
    assert outcome.satisfied is None and "no checker" in outcome.detail


def test_b0_registry_points_at_the_real_predicate():
    """注册表不得静默指向别处 —— 换成写反的谓词必须被发现。"""
    from hevi.production.p7 import constraint_check as cc

    assert cc._CHECKS["forbidden_substitutes"] is check_forbidden_substitutes


def test_b0_blocking_test_has_teeth(monkeypatch):
    """把谓词换成恒真(=禁止项被判成允许)→ `test_b0_forbidden_kind_is_blocked`
    的断言必须不再成立。这证明那条测试不是摆设。"""
    from hevi.production.p7 import constraint_check as cc

    monkeypatch.setitem(cc._CHECKS, "forbidden_substitutes",
                        lambda expected, observed: True)
    inverted = check_compatibility(_req(), {"substitute_kind": "generic_stars"})
    assert inverted.blocked_keys == (), "谓词被写反时确实会放行 —— 所以守卫有必要"
    assert inverted.compatible is True
    # 真实谓词仍然正确
    assert check_forbidden_substitutes(DECLARED_VALUE, "generic_stars") is False