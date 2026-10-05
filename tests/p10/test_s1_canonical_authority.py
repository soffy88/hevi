"""S1 架构守卫 —— 机械执行 2026-10-03 canonical 裁决。

这些测试的价值在于:违反裁决 = 测试变红,而不是靠人记住。
"""

import ast
from pathlib import Path

import pytest

from hevi.creative.autonomous import canonical, manifest, resolver

PKG = Path(canonical.__file__).parent

# 裁决列出的「不得新增第 6/7 套」词汇
FORBIDDEN_DEFINITIONS = (
    "AssetRequirement", "AssetDecision", "AssetScore", "AssetDecisionKind",
    "VisualIntent", "Storyboard", "AutonomousStoryboard",
    "AutonomousRunner", "ProductionOrchestrator", "VideoOrchestrator", "PipelineExecutor",
    "RepairPolicy", "RepairIncident", "RepairPlan", "QCRepairPlan", "AutonomousRepairPlan",
    "AssetRepairPlan", "DirectorRepairPlan",
    "QualityEvaluation", "QCVerdict",
    "ShotPlan", "DirectorIntent",
)


def _defined_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) or isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            names.add(node.name)
    return names


def test_s1_defines_no_sixth_or_seventh_vocabulary():
    """本包只做 adapter / aggregator / projection,不得定义 canonical-owned 类型。"""
    offenders: dict[str, list[str]] = {}
    for module in sorted(PKG.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        defined = _defined_names(tree)
        hits = sorted(defined & set(FORBIDDEN_DEFINITIONS))
        if hits:
            offenders[module.name] = hits
    assert not offenders, f"CANONICALIZATION_VIOLATION: {offenders}"


def test_s1_imports_canonical_owners_not_local_copies():
    """VisualIntent / AssetRequirement 必须来自 canonical owner,不是本地副本。"""
    tree = ast.parse((PKG / "canonical.py").read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "hevi.production.p0_pipeline" in imported
    assert "hevi.production.p7.asset_requirement" in imported
    assert "hevi.production.p7.asset_decision" in imported
    # 裁决:第二个 VisualIntent(p6 visual_compiler)降为 compiler-local,不得经此出口
    assert not any("visual_compiler" in module for module in imported)


def test_s1_resolver_has_no_selection_authority():
    """Resolver 不得拥有打分/排序/选 provider/覆盖决策的能力。"""
    for name in resolver.FORBIDDEN_METHODS:
        assert not hasattr(resolver.AssetResolver, name)
    # 构造时就拦:想挂打分/排序函数都挂不上
    with pytest.raises((AttributeError, TypeError)):
        resolver.AssetResolver(rank_candidates=lambda *a, **k: None)  # type: ignore[call-arg]


def test_s1_verdict_is_aggregator_not_evaluator():
    """ProductionVerdictAuthority 只聚合既有结论,不实现评估。"""
    source = ast.parse((PKG / "verdict.py").read_text(encoding="utf-8"))
    called = {n.func.attr for n in ast.walk(source)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    # 不得调用任何真实 evaluator(它们是 6 个既有实现之一)
    for evaluator in ("run_final_review", "run_delivery_gate", "shot_scorecard",
                      "analyze_video", "verdict_shot", "run_production_checks"):
        assert evaluator not in called, f"verdict must not run evaluators: {evaluator}"
    assert "ValidationResult" in (PKG / "verdict.py").read_text(encoding="utf-8")


def test_s1_manifest_is_projection_not_state_machine():
    """manifest 不推进状态:只从 mission 读,写入即 out_dir。"""
    text = (PKG / "manifest.py").read_text(encoding="utf-8")
    assert "def set_status" not in text
    assert "def advance" not in text
    # 状态来自 mission 投影
    assert 'getattr(mission, "status"' in text


def test_s1_manifest_blocks_secrets():
    with pytest.raises(ValueError, match="SECRET_IN_MANIFEST"):
        manifest.assert_no_secrets({"voice": {"api_key": "sk-live-x"}})
    manifest.assert_no_secrets({"voice": {"auth_ref": "env:VOICE_KEY"}})  # 引用可以


def test_known_vocabulary_splits_are_registered_not_hidden():
    """分裂必须被登记,而不是假装已统一。"""
    concepts = {s.concept for s in canonical.KNOWN_SPLITS}
    assert {"ProviderPolicy/ProviderDecision", "RunState", "RepairAction/RepairPlan",
            "Subtitle writer"} <= concepts
    for split in canonical.KNOWN_SPLITS:
        assert split.canonical and split.owners and split.seam


def test_require_canonical_guard_rejects_new_vocabulary():
    for name in ("VisualIntent", "AssetRequirement", "RepairPolicy"):
        with pytest.raises(ValueError, match="CANONICALIZATION_VIOLATION"):
            canonical.require_canonical(name)
    assert canonical.require_canonical("ExecutionReadyResolution") == "ExecutionReadyResolution"


def test_director_entry_is_existing_semantic_spine_only():
    """不得新增第四个 Director 入口:只声明既有五级主干。"""
    assert canonical.DIRECTOR_ENTRY == "director_pipeline:semantic_spine"
    assert canonical.DIRECTOR_STAGES == ("concept", "screenplay", "design_list",
                                         "scene_stage", "shot_list")
    # 包内不得出现其它 director 入口函数名
    text = "\n".join(p.read_text(encoding="utf-8") for p in PKG.glob("*.py"))
    for banned in ("plan_from_text", "director_create_episode", "parse_work"):
        assert f"import {banned}" not in text