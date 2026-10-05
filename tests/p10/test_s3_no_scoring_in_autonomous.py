"""S2/S3 硬门禁:任何 scoring/ranking 实现出现在 hevi/creative/autonomous/ 即 FAIL。

裁决(2026-10-03):
    S3 scoring canonical owner = provider_policy / 既有 shot_readiness.select_candidate
    绝不能放进 autonomous/resolver.py。
因此 autonomous 包内**不得**出现:
  - 打分函数(calculate_*/compute_*/score_*/_score/fitness)
  - 排序函数(rank_*/sort_candidates/top_k/argmax/choose_best/pick_best)
  - 权重表(weight/coefficient/threshold 形式的评分常量)
  - 引用既有 scorer 的实现(把评分搬进来也算违规)

允许的:消费 authority 的结论(如 read confidence / use ProviderDecision.selected_provider)。
"""

from __future__ import annotations

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[2] / "hevi" / "creative" / "autonomous"

SCORING_PATTERNS = (
    "calculate_score", "calculate_", "compute_score", "compute_fitness",
    "score_", "_score", "fitness", "weighted_score", "relevance",
)
RANKING_PATTERNS = (
    "rank", "sort_candidates", "top_k", "argmax", "argmin",
    "choose_best", "pick_best", "best_", "order_by_score",
)
WEIGHT_TOKENS = ("weight", "coefficient", "score_threshold", "soft_score", "relevance_weight")

# 允许出现的「消费既有结论」的名字(读取 authority 结果,不算自己实现)
ALLOWED_CONSUMERS = {
    "read_confidence", "selected_provider", "candidate_scores", "is_semantic_match",
}


def _functions_and_classes(tree: ast.AST) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            out.append(("class", node.name))
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            out.append(("func", node.name))
    return out


def test_no_scoring_or_ranking_implementation_in_autonomous_pkg():
    offenders: dict[str, list[str]] = {}
    for module in sorted(PKG.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        hits = []
        for kind, name in _functions_and_classes(tree):
            if name in ALLOWED_CONSUMERS:
                continue
            if any(token in name for token in SCORING_PATTERNS) or any(token in name for token in RANKING_PATTERNS):
                hits.append(f"{kind}:{name}")
        if hits:
            offenders[module.name] = sorted(hits)
    assert not offenders, f"SCORING_IN_AUTONOMOUS_PKG: {offenders}"


def test_no_weight_tables_in_autonomous_pkg():
    """评分权重表也不允许:一旦有权重,评分就回来了。"""
    offenders: dict[str, list[str]] = {}
    for module in sorted(PKG.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        hits: list[str] = []
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target.id]
            for name in targets:
                if any(token in name.lower() for token in WEIGHT_TOKENS):
                    hits.append(name)
        if hits:
            offenders[module.name] = sorted(set(hits))
    assert not offenders, f"WEIGHT_TABLE_IN_AUTONOMOUS_PKG: {offenders}"


def test_no_asset_score_dataclass_reintroduced():
    """第 5 套评分模型的名字也不允许回来。"""
    banned = {"AssetScore", "AssetFitness", "CandidateScore", "ScoredCandidate",
              "RankedCandidate", "SemanticScore"}
    found: dict[str, list[str]] = {}
    for module in sorted(PKG.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        hits = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name in banned]
        if hits:
            found[module.name] = hits
    assert not found, f"SCORE_MODEL_REINTRODUCED: {found}"


def test_resolver_only_consumes_authority_conclusions():
    """resolver 必须只读 authority 结论:出现排序调用即失败。"""
    text = (PKG / "resolver.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    forbidden_calls = {"max", "min", "sorted", "sort"}
    assert not (called & forbidden_calls), f"RESOLVER_SORTS: {called & forbidden_calls}"


def test_autonomous_does_not_import_existing_scorers():
    """不得把既有 scorer 的实现搬进来(只可消费其结论)。"""
    banned_imports = ("p1_pipeline", "providers.scoring", "production.p1_types")
    for module in sorted(PKG.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not any(b in node.module for b in banned_imports), (
                    f"AUTONOMOUS_IMPORTS_SCORER:{module.name} -> {node.module}")