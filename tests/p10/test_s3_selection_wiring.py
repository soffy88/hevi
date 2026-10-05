"""S3 接线验收:canonical selection 进入生产路径(resolve)。

验证顺序不可颠倒:先选、再判能否生成。
"""

from __future__ import annotations

import pytest

from hevi.creative.autonomous import ShotResolution, resolve
from hevi.creative.autonomous.identity import RequirementBinding, RequirementBindingSet
from hevi.creative.autonomous.selection import CANDIDATE_SELECTION, assert_single_authority
from hevi.production.p7.asset_contract import AssetSemanticRole, MediaType
from hevi.production.p7.asset_requirement import AssetRequirement
from hevi.production.shot_readiness import (
    REVIEW_CONFIDENCE_FLOOR,
    AssetCandidate,
    AssetCandidateState,
    ShotPreparation,
)

#: P1 起 `resolve()` 必须显式声明 domain + scorer registry + identity bindings,
#: 生产无法再靠「候选已经打好分」绕过 canonical scorer。
TEST_DOMAIN = "test_domain"
TEST_SCORER_ID = "test.pass_through"


class PassThroughScorer:
    """保留候选既有 confidence 的恒等 scorer(仅用于 selection seam 测试)。

    它照样声明适用域,遵守 S3 契约;不重新计算分数,让本文件继续专注
    `select_candidate` 的门槛行为。
    """

    applicable_domains = frozenset({TEST_DOMAIN})

    def __call__(self, candidate: AssetCandidate) -> float:
        return candidate.confidence


def _requirement(req_id: str) -> AssetRequirement:
    """canonical id → AssetRequirement。

    刻意容忍非 canonical 字符串(如 "ev.png"):本文件要证明的是
    **local ref 与 canonical id 不属于同一 namespace**,所以绑定对象
    必须是 canonical identity,而不是把 "ev.png" 反解成 requirement。
    """
    try:
        media, _, role = req_id.partition("/")
        return AssetRequirement(media_type=MediaType(media),
                                semantic_role=AssetSemanticRole(role))
    except ValueError:
        # 非 canonical id(实为 local ref):绑到默认 canonical requirement。
        # 这样 "ev.png" 作为 local_ref 仍可被显式绑定,而 candidate 侧的
        # requirement_id="ev.png" 不会被误当成已绑定。
        return AssetRequirement(media_type=MediaType.VIDEO,
                                semantic_role=AssetSemanticRole.SCENE)


def _bindings(*candidates: AssetCandidate,
              required: tuple[str, ...] = ()) -> RequirementBindingSet:
    known = list(candidates) + [
        AssetCandidate(candidate_id=f"required:{ref}",
                       requirement_id="VIDEO/SCENE", asset_ref=ref)
        for ref in required
    ]
    return RequirementBindingSet(tuple(
        RequirementBinding(local_ref=c.asset_ref, requirement=_requirement(c.requirement_id))
        for c in known
    ))


def _resolve(*candidates: AssetCandidate,
             required: tuple[str, ...] = ()) -> ShotResolution:
    prep = _prep(*candidates, required=required)
    return resolve(prep, domain=TEST_DOMAIN,
                   scorer_registry={TEST_SCORER_ID: PassThroughScorer()},
                   bindings=_bindings(*candidates, required=required))


def _prep(*candidates: AssetCandidate, required: tuple[str, ...] = ()) -> ShotPreparation:
    return ShotPreparation(shot_id="S1", candidates=list(candidates),
                           required_asset_refs=list(required))


def _cand(cid: str, *, req: str = "VIDEO/SCENE", confidence: float = 0.9,
          verified: bool = True, scored_by: str = "s", asset_ref: str = "") -> AssetCandidate:
    return AssetCandidate(candidate_id=cid, requirement_id=req,
                          asset_ref=asset_ref or f"media://{cid}",
                          confidence=confidence, verified=verified, scored_by=scored_by)


# ── 接线:走 canonical authority ──
def test_resolve_selects_through_canonical_authority():
    assert_single_authority()
    chosen = _cand("c1")
    resolution = _resolve(chosen)
    assert isinstance(resolution, ShotResolution)
    assert resolution.selected_requirement_ids == ("VIDEO/SCENE",)
    assert resolution.unresolved_requirement_ids == ()
    assert chosen.state is AssetCandidateState.SELECTED
    assert CANDIDATE_SELECTION.implementation.endswith("select_candidate")


def test_resolve_reports_unresolved_when_no_candidate():
    resolution = _resolve()
    assert resolution.unresolved_requirement_ids == ()
    assert resolution.ready_for_generation is False


def test_resolve_marks_requirement_unresolved_when_candidate_not_eligible():
    """有候选但不合规(floor 以下 / 未验证)→ requirement 未解决,不静默通过。"""
    low = _cand("c1", confidence=REVIEW_CONFIDENCE_FLOOR - 0.1)
    assert _resolve(low).unresolved_requirement_ids == ("VIDEO/SCENE",)
    unverified = _cand("c3", verified=False)
    assert _resolve(unverified).unresolved_requirement_ids == ("VIDEO/SCENE",)


def test_resolve_stamps_provenance_instead_of_trusting_the_caller():
    """P1 变更:来源不再由调用方预先声明,而是 `resolve()` 亲自盖章。

    S3 旧契约是「候选没有 `scored_by` 就不许自动选」,前提是调用方自己打分。
    P1 起 `resolve()` 必跑 canonical scorer,provenance 成为**产出**而非**输入**,
    所以「未打分候选被拒」不再是可达状态 —— 取而代之的保证是:
    经 `resolve()` 的候选必然带来源,且该来源是声明适用域的 canonical scorer。
    """
    unscored = _cand("c2", scored_by="", confidence=0.9)
    resolution = _resolve(unscored)
    assert unscored.scored_by == TEST_SCORER_ID
    assert resolution.selected_requirement_ids == ("VIDEO/SCENE",)
    assert any(line.startswith(f"scored:{TEST_SCORER_ID}") for line in unscored.lineage)


def test_select_candidate_still_rejects_provenance_free_candidate():
    """门槛本身未放松:绕过 `resolve()` 直接喂无来源候选,selector 仍拒绝。"""
    from hevi.production.shot_readiness import select_candidate

    free = _cand("c2", scored_by="", confidence=0.9)
    assert select_candidate(_prep(free), "VIDEO/SCENE") is None


def test_resolve_ready_requires_all_requirements_resolved():
    ok = _cand("c1", req="VIDEO/SCENE")
    bad = _cand("c2", req="VIDEO/CHARACTER", confidence=0.1)
    resolution = _resolve(ok, bad)
    assert resolution.selected_requirement_ids == ("VIDEO/SCENE",)
    assert resolution.unresolved_requirement_ids == ("VIDEO/CHARACTER",)
    assert resolution.ready_for_generation is False


def test_resolve_surfaces_human_review_flag():
    """既有 needs_human_review 只看 required_asset_refs 里的 requirement;

    候选的 requirement_id 未登记在该列表时,它按既有语义返回 False。
    这里锁定该真实语义,避免我们悄悄改写既有判定。
    """
    low = _cand("c1", confidence=0.2)
    assert _resolve(low).human_review_required is False  # 不在 required 列表
    bound = _cand("c2", req="ev.png", confidence=0.2)
    assert _resolve(bound, required=("ev.png",)).human_review_required is True


# ── unbound local refs 必须暴露,不得静默 ──
def test_resolve_surfaces_unbound_asset_refs():
    """required 里的 ref 没有对应候选 → 显式列出,不静默忽略。"""
    resolution = _resolve(_cand("c1"), required=("ev.png", "orphan.png"))
    assert "orphan.png" in resolution.unbound_asset_refs


def test_resolve_never_compares_local_ref_against_canonical_id():
    """回归:local ref 恰好长得像 canonical id 时,不得因此被视为已绑定。

    这是与 S2/S3 同类的静默失败:两边都是 str,比较能跑。
    """
    resolution = _resolve(required=("VIDEO/SCENE",))
    assert resolution.unbound_asset_refs == ("VIDEO/SCENE",)


# ── provenance ──
def test_resolve_records_lineage_for_audit():
    chosen = _cand("c1")
    _resolve(chosen)
    assert any(line.startswith("selected:") for line in chosen.lineage)


def test_resolve_is_deterministic():
    first = _resolve(_cand("c1"), _cand("c2", confidence=0.95))
    second = _resolve(_cand("c1"), _cand("c2", confidence=0.95))
    assert first.selected_requirement_ids == second.selected_requirement_ids


@pytest.mark.parametrize("confidence", [0.0, 0.5, 0.74, 0.75, 0.99])
def test_resolve_respects_floor_boundary(confidence):
    candidate = _cand("c1", confidence=confidence)
    eligible = _resolve(candidate).ready_for_generation
    assert eligible is (confidence >= REVIEW_CONFIDENCE_FLOOR)