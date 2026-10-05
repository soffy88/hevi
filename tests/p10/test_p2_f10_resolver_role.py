"""P2-F10 守卫:`AssetResolver` 的最终角色已冻结,不得回退。

冻结内容(见 docs/p10/p2_f10_decision.md 与 resolver.py 模块 docstring):

1. **不产候选** —— 它从不构造 `AssetCandidate`,结构上无法参与 P1 selection;
2. **不产 admission** —— `usable` 是「p7 决策 ACCEPTED」,不是 `ready_for_generation`;
3. **不在生产路径** —— 生产模块不得 import 它。

这三条每一条都对应一种 P1 结构性倒退的复发方式。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hevi.creative.autonomous import resolver as resolver_module
from hevi.creative.autonomous.resolver import (
    RESOLVER_ROLE,
    AssetResolver,
    ExecutionReadyResolution,
    assert_resolver_is_not_production_authority,
)

REPO = Path(__file__).resolve().parents[2]
AUTONOMOUS_PKG = REPO / "hevi" / "creative" / "autonomous"
RESOLVER_SRC = AUTONOMOUS_PKG / "resolver.py"

#: 不得 import resolver 的生产目录。`creative/autonomous` 是 adapter 层,豁免。
PRODUCTION_TREES = ("hevi/production", "hevi/execution", "hevi/ops", "hevi/missions",
                    "hevi/acquisition", "hevi/renderers", "hevi/explainer")

FROZEN_NAMES = ("AssetResolver", "ExecutionReadyResolution")


# ── 1. 不产候选 ──
def test_f10_resolver_module_never_constructs_a_candidate():
    """它一旦构造 AssetCandidate,就能参与 selection —— 那是被否决的。"""
    tree = ast.parse(RESOLVER_SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "AssetCandidate":
            raise AssertionError(
                f"RESOLVER_OVERREACH:{node.id} referenced at line {node.lineno}; "
                "candidates are produced by Acquirers and chosen by select_candidate")
        if isinstance(node, ast.Attribute) and node.attr in (
                "select_candidate", "admit_generation", "ready_for_generation"):
            raise AssertionError(
                f"RESOLVER_OVERREACH:{node.attr} referenced at line {node.lineno}; "
                "AssetResolver must not reach into selection or admission")


def test_f10_resolver_has_no_scoring_or_ranking_surface():
    for name in resolver_module.FORBIDDEN_METHODS:
        assert not hasattr(AssetResolver, name)
    # 构造时就挂不上打分/排序函数(AttributeError 来自 __init__ 的显式检查,
    # TypeError 来自 Python 本身拒收未知 kwarg —— 两者都表示「挂不上」)。
    with pytest.raises((AttributeError, TypeError)):
        AssetResolver(rank_candidates=lambda *a, **k: None)  # type: ignore[call-arg]


# ── 2. 不产 admission ──
def test_f10_usable_is_not_generation_admission():
    """`usable` 说「p7 ACCEPTED」,不说「这个资产可以生成」。"""
    ready = ExecutionReadyResolution(
        requirement_id="VIDEO/SCENE", decision_state="ACCEPTED",
        provider_id="p", obtained_source="media/x.mp4")
    assert ready.usable is True
    # 不得带任何 generation admission 词汇
    for forbidden in ("ready_for_generation", "admit", "can_generate", "generation_allowed"):
        assert not hasattr(ready, forbidden), (
            f"F10_LEAK: ExecutionReadyResolution 暴露了 {forbidden},看起来像 admission")


def test_f10_obtained_source_is_not_named_as_a_selection():
    """字段名本身不得再宣称自己是选择结论。"""
    fields = set(ExecutionReadyResolution.__dataclass_fields__)
    assert "selected_source" not in fields, (
        "F10 回归:selected_source 会让人把 acquirer 的第一次命中当成选择结论")
    assert "obtained_source" in fields
    instance = ExecutionReadyResolution(
        requirement_id="r", decision_state="ACCEPTED", provider_id="p",
        obtained_source="s")
    assert instance.obtained_source == "s"


def test_f10_usable_does_not_imply_admit_generation():
    """拿到 usable=True 也仍然进不了生成:admit_generation 需要 ShotResolution。"""
    from hevi.creative.autonomous.selection import (
        GenerationNotAdmittedError,
        admit_generation,
    )

    ready = ExecutionReadyResolution(
        requirement_id="VIDEO/SCENE", decision_state="ACCEPTED",
        provider_id="p", obtained_source="media/x.mp4")
    assert ready.usable is True
    with pytest.raises(GenerationNotAdmittedError):
        # 没有 ShotResolution → 即使 resolver 说 usable 也无法 admission
        admit_generation(None, [])


# ── 3. 不在生产路径 ──
def test_f10_production_modules_do_not_import_the_resolver():
    offenders: dict[str, int] = {}
    for tree_name in PRODUCTION_TREES:
        tree_root = REPO / tree_name
        if not tree_root.is_dir():
            continue
        for path in sorted(tree_root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if not any(name in text for name in FROZEN_NAMES):
                continue
            parsed = ast.parse(text)
            for node in ast.walk(parsed):
                hit = None
                if isinstance(node, ast.ImportFrom):
                    hit = next((n for n in FROZEN_NAMES
                                if any(a.name == n or a.name.endswith(f".{n}")
                                       for a in node.names)), None)
                elif isinstance(node, ast.Import):
                    hit = next((n for n in FROZEN_NAMES
                                if any(a.name.endswith(f".{n}") or a.name == n
                                       for a in node.names)), None)
                if hit:
                    offenders[f"{path.relative_to(REPO)}:{node.lineno}"] = node.lineno
    assert not offenders, (
        f"RESOLVER_ON_PRODUCTION_PATH: 生产模块不得 import {FROZEN_NAMES}: {offenders}")


def test_f10_p0_generation_gate_does_not_mention_the_resolver():
    """p0 的 generation 门只认 ShotResolution + admit_generation。"""
    src = (REPO / "hevi" / "production" / "p0_pipeline.py").read_text(encoding="utf-8")
    for name in FROZEN_NAMES:
        assert name not in src, f"F10_LEAK: p0_pipeline 不得提到 {name}"
    assert "admit_generation(resolution, preparation.candidates)" in src


# ── 冻结声明本身 ──
def test_f10_role_declaration_is_machine_readable():
    assert RESOLVER_ROLE.produces_candidates is False
    assert RESOLVER_ROLE.is_generation_admission is False
    assert RESOLVER_ROLE.on_production_path is False
    assert "provider" in RESOLVER_ROLE.role
    # 排除项必须点名真正的 owner,否则守卫只是形式
    joined = " ".join(RESOLVER_ROLE.ruled_out)
    assert "select_candidate" in joined
    assert "admit_generation" in joined


def test_f10_assert_guard_detects_a_regression():
    """守卫必须真的能失败 —— 否则它只是装饰。"""
    assert_resolver_is_not_production_authority()
    for attribute in ("produces_candidates", "is_generation_admission", "on_production_path"):
        original = getattr(RESOLVER_ROLE, attribute)
        broken = type(RESOLVER_ROLE)(
            **{**{f.name: getattr(RESOLVER_ROLE, f.name)
                  for f in RESOLVER_ROLE.__dataclass_fields__.values()},
               attribute: True})
        try:
            resolver_module.RESOLVER_ROLE = broken
            with pytest.raises(AssertionError, match="RESOLVER_OVERREACH|RESOLVER_ON_PRODUCTION"):
                assert_resolver_is_not_production_authority()
        finally:
            resolver_module.RESOLVER_ROLE = type(
                RESOLVER_ROLE)(**{**{f.name: getattr(RESOLVER_ROLE, f.name)
                                    for f in RESOLVER_ROLE.__dataclass_fields__.values()},
                                 attribute: original})


def test_f10_s2_acquisition_reaches_provider_without_the_resolver():
    """P2-A 的 acquisition 链不经过 AssetResolver —— 这是「不在生产路径」的实证。"""
    src = (REPO / "hevi" / "creative" / "autonomous" / "acquire_stock.py").read_text(
        encoding="utf-8")
    assert "AssetResolver" not in src
    assert "ExecutionReadyResolution" not in src
    # provider 选择直接走 provider_policy(权威),不经 resolver 转接
    assert "evaluate_provider_policy" in (REPO / "hevi" / "production" / "p0_pipeline.py").read_text(
        encoding="utf-8")