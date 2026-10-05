"""S3 硬测试 1-4(裁决要求):

1. requirement identity —— p7 requirement_id 全链路不变
2. namespace mismatch —— shot_readiness local ref ≠ p7 id 必须显式映射,禁止静默真假
3. selection single-authority —— autonomous 内无 score/rank/select 实现
4. decision provenance —— AssetDecision 可追溯 requirement/candidate/scorer/score inputs/rejection
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hevi.creative.autonomous import (
    CANDIDATE_SELECTION,
    PROVIDER_SELECTION,
    AssetRequirement,
    AssetSemanticRole,
    MediaType,
    RequirementBinding,
    RequirementBindingSet,
    RequirementIdentityError,
    assert_single_authority,
)
from hevi.creative.autonomous.selection import NON_AUTHORITATIVE, SelectionPath, select
from hevi.production.p7.asset_decision import AssetDecision, AssetDecisionState
from hevi.production.p7.asset_intelligence import AssetDecisionAuthority
from hevi.production.shot_readiness import (
    AssetCandidate,
    AssetCandidateState,
    ShotPreparation,
)

PKG = Path(__file__).resolve().parents[2] / "hevi" / "creative" / "autonomous"


def _req(role: AssetSemanticRole = AssetSemanticRole.SCENE) -> AssetRequirement:
    return AssetRequirement(media_type=MediaType.VIDEO, semantic_role=role)


# ══ 1. requirement identity 全链路不变 ══

def test_1_requirement_id_is_stable_across_the_chain():
    """p7 requirement_id 从 requirement 到 candidate 到 decision 全程不变。"""
    requirement = _req()
    canonical_id = requirement.requirement_id
    assert canonical_id == "VIDEO/SCENE"

    candidate = AssetCandidate(candidate_id="c1", requirement_id=canonical_id,
                               asset_ref="a.mp4", scored_by="s")
    assert candidate.requirement_id == canonical_id

    class _Decision:
        selected_provider = "local"

        def model_dump(self, **_: object) -> dict[str, object]:
            return {}

    decision = AssetDecision(requirement_id=canonical_id,
                             state=AssetDecisionState.ACCEPTED, selected_source="a.mp4",
                             provider_decision=_Decision(), confidence=0.9)  # type: ignore[arg-type]
    assert decision.requirement_id == canonical_id


def test_1_two_requirements_of_same_shape_share_id_only_by_construction():
    """id 由 media_type/role 派生 —— 相同形状确实同 id,这不是 bug 而是既有契约。"""
    assert _req().requirement_id == _req().requirement_id
    assert _req(AssetSemanticRole.CHARACTER).requirement_id != _req().requirement_id


# ══ 2. namespace mismatch 必须显式 ══

def test_2_local_ref_and_canonical_id_are_different_namespaces():
    """这是那个静默失败的根源:两边都是 str,直接比较能跑但语义不同。"""
    requirement = _req()
    binding = RequirementBinding(local_ref="ev.png", requirement=requirement)
    assert binding.local_ref != binding.requirement_id
    # local ref 不能当 canonical id 用
    assert binding.covers("ev.png") is False
    assert binding.covers(requirement.requirement_id) is True


def test_2_unbound_local_ref_is_surfaced_not_ignored():
    bindings = RequirementBindingSet((RequirementBinding("ev.png", _req()),))
    assert bindings.unbound_local_refs(("ev.png", "missing.png")) == ("missing.png",)
    assert bindings.for_local_ref("missing.png") is None
    assert bindings.for_requirement("VIDEO/CHARACTER") is None


def test_2_binding_requires_both_sides():
    with pytest.raises(RequirementIdentityError):
        RequirementBinding(local_ref="", requirement=_req()).validate()


def test_2_no_implicit_fallback_in_covers():
    """candidate 侧只接受 canonical id;传 local ref 不得「宽松匹配」。"""
    binding = RequirementBinding("ev.png", _req())
    for wrong in ("ev.png", "", "VIDEO", "video/scene", "VIDEO/SCENE "):
        assert binding.covers(wrong) is False


# ══ 3. selection single-authority ══

def test_3_exactly_one_candidate_authority_in_production():
    assert_single_authority()
    live = [a for a in (CANDIDATE_SELECTION, *NON_AUTHORITATIVE)
            if a.selects == "candidate" and a.in_production_use]
    assert len(live) == 1
    assert live[0].implementation.endswith("shot_readiness.select_candidate")


def test_3_provider_selection_is_a_different_object_not_a_second_selector():
    assert PROVIDER_SELECTION.selects == "provider"
    assert CANDIDATE_SELECTION.selects == "candidate"
    assert SelectionPath.PROVIDER is not SelectionPath.CANDIDATE


def test_3_unused_local_path_is_registered_as_non_authoritative():
    """p1 的 max-overall 必须在册为非权威,否则将来会被误当 canonical。"""
    unused = [a for a in NON_AUTHORITATIVE if a.path is SelectionPath.UNUSED_LOCAL]
    assert unused and all(a.in_production_use is False for a in unused)


def test_3_autonomous_package_contains_no_selection_implementation():
    """AST:不得定义 select/rank/score 类实现(薄转发除外)。"""
    offenders: dict[str, list[str]] = {}
    for module in sorted(PKG.glob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            name = node.name
            if name in {"select", "select_candidate"} and module.name == "selection.py":
                continue  # 明确的薄转发
            if any(token in name for token in ("select", "rank", "score", "best", "top_k")):
                offenders.setdefault(module.name, []).append(name)
    assert not offenders, f"SELECTION_IN_AUTONOMOUS:{offenders}"


def test_3_select_forwards_to_canonical():
    chosen = AssetCandidate(candidate_id="c1", requirement_id="VIDEO/SCENE",
                            asset_ref="a.mp4", confidence=0.95, verified=True,
                            scored_by="s")
    prep = ShotPreparation(shot_id="S1", candidates=[chosen])
    assert select(prep, "VIDEO/SCENE") is chosen


# ══ 4. decision provenance ══

def test_4_decision_traces_all_five_elements():
    """requirement_id / candidate_id / selector authority / score inputs / rejection reason。"""
    from hevi.provider_policy.policy import ProviderDecision

    provider_decision = ProviderDecision(selected_provider="local_assets",
                                         eligible=["local_assets"],
                                         considered=["local_assets", "stock_x"],
                                         candidate_scores={"local_assets": {"score": 0.9}})
    from hevi.production.p7.asset_contract import AssetStatus
    from hevi.production.p7.evidence import AssetEvidence

    authority = AssetDecisionAuthority()
    accepted = authority.decide(_req(), provider_decision=provider_decision,
                                selected_source="a.mp4", confidence=0.9,
                                evidence=(AssetEvidence(asset_id="c1", source="local",
                                                        status=AssetStatus.AVAILABLE,
                                                        license="CC0"),),
                                policy_id="s3")
    assert accepted.decision.state is AssetDecisionState.ACCEPTED
    decision = accepted.decision
    payload = decision.to_dict()
    for key in ("requirement_id", "state", "selected_source", "confidence", "reason",
                 "policy_id"):
        assert key in payload, key
    assert payload["requirement_id"] == "VIDEO/SCENE"
    assert decision.provider_decision is provider_decision  # provider 权威结论原样携带
    assert decision.provider_decision.candidate_scores  # score inputs 可追溯
    assert decision.fingerprint()  # 稳定指纹


def test_4_rejection_reason_is_recorded_not_silent():
    authority = AssetDecisionAuthority()
    blocked = authority.decide(_req(), provider_decision=None, policy_id="s3")
    assert blocked.decision.state is AssetDecisionState.BLOCKED
    assert "NO_PROVIDER_DECISION" in blocked.decision.reason
    assert blocked.decision.to_dict()["reason"]


def test_4_candidate_lineage_records_scorer_and_selection():
    from hevi.production.shot_readiness import score_candidates

    def scorer(candidate: AssetCandidate) -> float:
        return 0.92

    scorer.applicable_domains = frozenset({"any"})  # type: ignore[attr-defined]
    candidate = AssetCandidate(candidate_id="c1", requirement_id="VIDEO/SCENE",
                               asset_ref="a.mp4", verified=True)
    score_candidates([candidate], domain="any", registry={"s": scorer})
    select(ShotPreparation(shot_id="S1", candidates=[candidate]), "VIDEO/SCENE")
    assert any(line.startswith("scored:") for line in candidate.lineage)
    assert any(line.startswith("selected:") for line in candidate.lineage)
    assert candidate.state is AssetCandidateState.SELECTED


def test_4_binding_bridges_local_ref_to_decision_provenance():
    """local ref → canonical id → decision,一条链可追。"""
    binding = RequirementBinding("ev.png", _req())
    bindings = RequirementBindingSet((binding,))
    resolved = bindings.for_local_ref("ev.png")
    assert resolved is binding
    assert resolved.requirement_id == "VIDEO/SCENE"
    # 反方向:canonical id → binding → local ref
    assert bindings.for_requirement("VIDEO/SCENE").local_ref == "ev.png"