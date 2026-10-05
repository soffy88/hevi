"""S3 接线验收:canonical selection 进入生产路径(resolve)。

验证顺序不可颠倒:先选、再判能否生成。
"""

from __future__ import annotations

import pytest

from hevi.creative.autonomous import ShotResolution, resolve
from hevi.creative.autonomous.selection import CANDIDATE_SELECTION, assert_single_authority
from hevi.production.shot_readiness import (
    REVIEW_CONFIDENCE_FLOOR,
    AssetCandidate,
    AssetCandidateState,
    ShotPreparation,
)


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
    resolution = resolve(_prep(chosen))
    assert isinstance(resolution, ShotResolution)
    assert resolution.selected_requirement_ids == ("VIDEO/SCENE",)
    assert resolution.unresolved_requirement_ids == ()
    assert chosen.state is AssetCandidateState.SELECTED
    assert CANDIDATE_SELECTION.implementation.endswith("select_candidate")


def test_resolve_reports_unresolved_when_no_candidate():
    resolution = resolve(_prep())
    assert resolution.unresolved_requirement_ids == ()
    assert resolution.ready_for_generation is False


def test_resolve_marks_requirement_unresolved_when_candidate_not_eligible():
    """有候选但不合规(floor 以下 / 无来源 / 未验证)→ requirement 未解决,不静默通过。"""
    low = _cand("c1", confidence=REVIEW_CONFIDENCE_FLOOR - 0.1)
    assert resolve(_prep(low)).unresolved_requirement_ids == ("VIDEO/SCENE",)
    unscored = _cand("c2", scored_by="")
    assert resolve(_prep(unscored)).unresolved_requirement_ids == ("VIDEO/SCENE",)
    unverified = _cand("c3", verified=False)
    assert resolve(_prep(unverified)).unresolved_requirement_ids == ("VIDEO/SCENE",)


def test_resolve_ready_requires_all_requirements_resolved():
    ok = _cand("c1", req="VIDEO/SCENE")
    bad = _cand("c2", req="VIDEO/CHARACTER", confidence=0.1)
    resolution = resolve(_prep(ok, bad))
    assert resolution.selected_requirement_ids == ("VIDEO/SCENE",)
    assert resolution.unresolved_requirement_ids == ("VIDEO/CHARACTER",)
    assert resolution.ready_for_generation is False


def test_resolve_surfaces_human_review_flag():
    """既有 needs_human_review 只看 required_asset_refs 里的 requirement;

    候选的 requirement_id 未登记在该列表时,它按既有语义返回 False。
    这里锁定该真实语义,避免我们悄悄改写既有判定。
    """
    low = _cand("c1", confidence=0.2)
    assert resolve(_prep(low)).human_review_required is False  # 不在 required 列表
    bound = _cand("c2", req="ev.png", confidence=0.2)
    assert resolve(_prep(bound, required=("ev.png",))).human_review_required is True


# ── unbound local refs 必须暴露,不得静默 ──
def test_resolve_surfaces_unbound_asset_refs():
    """required 里的 ref 没有对应候选 → 显式列出,不静默忽略。"""
    resolution = resolve(_prep(_cand("c1"), required=("ev.png", "orphan.png")))
    assert "orphan.png" in resolution.unbound_asset_refs


def test_resolve_never_compares_local_ref_against_canonical_id():
    """回归:local ref 恰好长得像 canonical id 时,不得因此被视为已绑定。

    这是与 S2/S3 同类的静默失败:两边都是 str,比较能跑。
    """
    prep = _prep(required=("VIDEO/SCENE",))
    resolution = resolve(prep)
    assert resolution.unbound_asset_refs == ("VIDEO/SCENE",)


# ── provenance ──
def test_resolve_records_lineage_for_audit():
    chosen = _cand("c1")
    resolve(_prep(chosen))
    assert any(line.startswith("selected:") for line in chosen.lineage)


def test_resolve_is_deterministic():
    prep = _prep(_cand("c1"), _cand("c2", confidence=0.95))
    first = resolve(prep)
    second = resolve(prep)
    assert first.selected_requirement_ids == second.selected_requirement_ids


@pytest.mark.parametrize("confidence", [0.0, 0.5, 0.74, 0.75, 0.99])
def test_resolve_respects_floor_boundary(confidence):
    candidate = _cand("c1", confidence=confidence)
    eligible = resolve(_prep(candidate)).ready_for_generation
    assert eligible is (confidence >= REVIEW_CONFIDENCE_FLOOR)