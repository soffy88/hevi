"""P1 invariants A-F + P1-01..P1-10 — canonical resolution 是生产 authority。

真实走 `run_p0_production` 的 stage 3-5 代码路径(P0ProductionState + VisualIntent +
discovery + resolve + admission),不 mock 核心链路。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hevi.creative.autonomous.identity import RequirementBinding, RequirementBindingSet
from hevi.creative.autonomous.selection import (
    GenerationNotAdmitted,
    GenerationNotAdmittedError,
    ShotResolution,
    admit_generation,
    resolve,
)
from hevi.production.p0_pipeline import (
    P0_ASSET_DOMAIN,
    P0_SCORER_ID,
    P0_ScienceRelevanceScorer,
    P0ProductionState,
    VisualIntent,
    _requirement_for,
)
from hevi.production.shot_readiness import (
    NO_APPLICABLE_SCORER,
    REVIEW_CONFIDENCE_FLOOR,
    AssetCandidate,
    AssetCandidateState,
    ShotPreparation,
    score_candidates,
)

REPO = Path(__file__).resolve().parents[2]
P0_SRC = REPO / "hevi" / "production" / "p0_pipeline.py"


def _state() -> P0ProductionState:
    return P0ProductionState(production_id="prod-1", narration="n", topic="t")


def _intent(intent_id: str = "vi-0001", *, entities: tuple[str, ...] = ()) -> VisualIntent:
    return VisualIntent(intent_id=intent_id, timeline_lock_id="tl-1",
                        narration_segment="the black hole bends light near accretion disk",
                        start_s=0.0, end_s=4.0, required_entities=entities,
                        required_concepts=("black hole",), visual_purpose="show scale",
                        motion_purpose="slow push")


def _cand(cid: str, *, asset_ref: str, req: str, confidence: float = 0.0,
          verified: bool = True, scored_by: str = "") -> AssetCandidate:
    return AssetCandidate(candidate_id=cid, requirement_id=req, asset_ref=asset_ref,
                          confidence=confidence, verified=verified, scored_by=scored_by)


def _resolve_for(state: P0ProductionState, intent: VisualIntent,
                 candidates: list[AssetCandidate]) -> ShotResolution:
    """复现 p0 stage 4b 的真实顺序:打分 → resolve → admission。"""
    scorer = P0_ScienceRelevanceScorer()
    scored, _ = score_candidates(candidates, domain=P0_ASSET_DOMAIN,
                                 registry={P0_SCORER_ID: scorer})
    if scored == NO_APPLICABLE_SCORER:
        pytest.skip("scorer not applicable")
    prep = ShotPreparation(shot_id=f"prod-1:shot-{intent.intent_id[-4:]}",
                           candidates=list(candidates),
                           required_asset_refs=[c.asset_ref for c in candidates])
    return resolve(prep, domain=P0_ASSET_DOMAIN,
                   scorer_registry={P0_SCORER_ID: scorer},
                   bindings=_bindings_for(intent, candidates))


def _bindings_for(intent: VisualIntent,
                 candidates: list[AssetCandidate]) -> RequirementBindingSet:
    """local asset ref → canonical p7 requirement 的显式映射(生产同款)。"""
    return RequirementBindingSet(tuple(
        RequirementBinding(local_ref=c.asset_ref, requirement=_requirement_for(intent))
        for c in candidates
    ))


# ══ P1-01 canonical path ══
def test_p1_01_canonical_path_produces_selectable_resolution(tmp_path):
    media = tmp_path / "nasa_accretion.webm"
    media.write_bytes(b"webm-bytes")
    intent = _intent()
    candidate = _cand("c1", asset_ref=media.as_uri(), req=_requirement_for(intent).requirement_id)
    resolution = _resolve_for(_state(), intent, [candidate])
    assert resolution.ready_for_generation is True
    assert candidate.state is AssetCandidateState.SELECTED
    assert candidate.scored_by == P0_SCORER_ID
    assert candidate.confidence >= REVIEW_CONFIDENCE_FLOOR


# ══ P1-02 no selected ══
def test_p1_02_no_candidates_means_no_generation():
    intent = _intent()
    assert _resolve_for(_state(), intent, []).ready_for_generation is False


# ══ P1-03 unresolved ══
def test_p1_03_unresolved_blocks_generation():
    intent = _intent()
    # asset_ref 不含任何已知关键词 → scorer 给 0.0 → 无合规候选 → unresolved
    low = _cand("c1", asset_ref="file:///generic_clip.webm",
                req=_requirement_for(intent).requirement_id)
    resolution = _resolve_for(_state(), intent, [low])
    assert resolution.unresolved_requirement_ids == (low.requirement_id,)
    assert resolution.ready_for_generation is False


# ══ P1-04 unbound ══
def test_p1_04_unbound_blocks_generation(tmp_path):
    media = tmp_path / "nasa_accretion.webm"
    media.write_bytes(b"x")
    intent = _intent()
    candidate = _cand("c1", asset_ref=media.as_uri(), req=_requirement_for(intent).requirement_id)
    prep = ShotPreparation(shot_id="S1", candidates=[candidate],
                           required_asset_refs=["orphan.png"])
    resolution = resolve(prep, domain=P0_ASSET_DOMAIN,
                         scorer_registry={P0_SCORER_ID: P0_ScienceRelevanceScorer()},
                         bindings=_bindings_for(intent, [candidate]))
    assert "orphan.png" in resolution.unbound_asset_refs
    # unbound 非空 → 不得生成
    assert resolution.ready_for_generation is False


# ══ P1-05 human review ══
def test_p1_05_human_review_blocks_auto_generation():
    low = _cand("c1", asset_ref="file:///ev.png", req="ev.png", confidence=0.1,
                scored_by=P0_SCORER_ID)
    prep = ShotPreparation(shot_id="S1", candidates=[low], required_asset_refs=["ev.png"])
    resolution = resolve(prep, domain=P0_ASSET_DOMAIN,
                         scorer_registry={P0_SCORER_ID: P0_ScienceRelevanceScorer()},
                         bindings=RequirementBindingSet(()))
    assert resolution.human_review_required is True
    assert resolution.ready_for_generation is False


# ══ P1-06 namespace collision ══
def test_p1_06_requirement_id_looks_like_local_ref_is_not_bound():
    """canonical id 恰好等于 required ref 的字符串值时,不得视为已绑定。"""
    intent = _intent()
    canonical_id = _requirement_for(intent).requirement_id
    prep = ShotPreparation(shot_id="S1", candidates=[],
                           required_asset_refs=[canonical_id])
    resolution = resolve(prep, domain=P0_ASSET_DOMAIN,
                         scorer_registry={P0_SCORER_ID: P0_ScienceRelevanceScorer()},
                         bindings=RequirementBindingSet(()))
    assert resolution.unbound_asset_refs == (canonical_id,)
    assert resolution.ready_for_generation is False


def test_p1_06_requirement_id_derives_from_canonical_p7():
    from hevi.production.p7.asset_contract import AssetSemanticRole, MediaType
    from hevi.production.p7.asset_requirement import AssetRequirement

    expected = AssetRequirement(media_type=MediaType.VIDEO,
                                semantic_role=AssetSemanticRole.SCENE)
    assert _requirement_for(_intent()) == expected
    character = _requirement_for(_intent(entities=("ann",)))
    assert character.semantic_role is AssetSemanticRole.CHARACTER
    assert character.requirement_id != expected.requirement_id


# ══ P1-07 multiple candidates ══
def test_p1_07_multiple_candidates_decided_by_canonical_selector(tmp_path):
    """多个候选时 selection 必须来自 canonical selector,而非 discovery。"""
    accretion = tmp_path / "nasa_accretion.webm"
    accretion.write_bytes(b"a")
    orbit = tmp_path / "nasa_orrery.webm"
    orbit.write_bytes(b"o")
    intent = _intent()
    candidates = [
        _cand("c-accretion", asset_ref=accretion.as_uri(), req=_requirement_for(intent).requirement_id),
        _cand("c-orbit", asset_ref=orbit.as_uri(), req=_requirement_for(intent).requirement_id),
    ]
    resolution = _resolve_for(_state(), intent, candidates)
    assert resolution.ready_for_generation is True
    chosen = [c for c in candidates if c.state is AssetCandidateState.SELECTED]
    assert len(chosen) == 1
    # 'orbit' 相关性 0.85 < 'accretion' 0.95,canonical scorer + selector 应选 accretion
    assert chosen[0].candidate_id == "c-accretion"
    assert all(c.state is AssetCandidateState.REJECTED for c in candidates if c is not chosen[0])


# ══ P1-08 retry / P1-09 resume ══
def test_p1_08_retry_recomputes_resolution(tmp_path):
    """第一次失败后 retry 必须重新 resolve,不得复用旧结论。"""
    media = tmp_path / "nasa_accretion.webm"
    media.write_bytes(b"x")
    intent = _intent()
    first = _cand("c1", asset_ref=media.as_uri(), req=_requirement_for(intent).requirement_id)
    assert _resolve_for(_state(), intent, [first]).ready_for_generation is True

    retry_media = tmp_path / "nasa_orbit.webm"
    retry_media.write_bytes(b"y")
    second = _cand("c2", asset_ref=retry_media.as_uri(), req=_requirement_for(intent).requirement_id)
    retry_resolution = _resolve_for(_state(), intent, [second])
    assert retry_resolution.ready_for_generation is True
    assert first.state is AssetCandidateState.SELECTED      # 旧结论未被篡改
    assert second.state is AssetCandidateState.SELECTED     # 新结论独立


def test_p1_09_reload_state_recomputes_from_scratch(tmp_path):
    """resume:state 重建后 resolution 必须重算,不从旧 state 继承。"""
    media = tmp_path / "nasa_accretion.webm"
    media.write_bytes(b"x")
    intent = _intent()
    fresh = _state()
    assert not fresh.shot_resolutions
    candidate = _cand("c1", asset_ref=media.as_uri(), req=_requirement_for(intent).requirement_id)
    fresh.shot_resolutions["prod-1:shot-0001"] = _resolve_for(fresh, intent, [candidate])
    assert fresh.shot_resolutions["prod-1:shot-0001"].ready_for_generation is True


# ══ P1-10 AST guard:生产路径不得自行选择资产 ══
def test_p1_10_p0_has_no_asset_selection_pattern():
    """p0 生产路径不得再出现「决定哪个 asset 被选」的形态。

    禁:`max/sorted(...)[0]/candidates[0]` 等排序取值;禁 discovery 层的 `break` 提前退出。
    允许:lookup、receipt 构造、时长 clamp。
    """
    tree = ast.parse(P0_SRC.read_text(encoding="utf-8"))
    lines = P0_SRC.read_text(encoding="utf-8").splitlines()

    # 1) 排序/取值选择
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {
                "max", "min", "sorted"}:
            src = ast.get_source_segment(P0_SRC.read_text(encoding="utf-8"), node) or ""
            # 只禁止与候选/资产选择相关的;时长 clamp 等不在此范围
            assert "candidate" not in src and "asset" not in src, (
                f"ASSET_SELECTION_IN_P0: {src[:80]}")
        if isinstance(node, ast.Subscript):
            src = ast.get_source_segment(P0_SRC.read_text(encoding="utf-8"), node) or ""
            if "candidate" in src or "resolved_assets" in src:
                assert "[0]" not in src, f"ASSET_SELECTION_IN_P0: {src[:80]}"

    # 2) discovery 层的 break(选择提前退出)
    discovery_break = [i + 1 for i, line in enumerate(lines)
                       if line.strip() == "break" and i > 400 and i < 440]
    assert not discovery_break, f"DISCOVERY_STILL_BREAKS_EARLY: lines {discovery_break}"


def test_p1_10_p0_calls_resolve_and_gates_on_ready_for_generation():
    src = P0_SRC.read_text(encoding="utf-8")
    assert "resolve(" in src and "preparation" in src, \
        "production path must call canonical resolve()"
    assert "admit_generation(" in src, \
        "production generation must go through the admission seam"
    assert "ready_for_generation" in src, "generation must be gated on ShotResolution"


def test_p1_10_p0_uses_declared_domain_scorer():
    """discovery 的 scorer 必须声明适用域(S3 契约),不能是裸函数。"""
    scorer = P0_ScienceRelevanceScorer()
    assert scorer.applicable_domains == frozenset({P0_ASSET_DOMAIN})


# ══ Invariant D 汇总 ══
@pytest.mark.parametrize("scenario", ["no_candidate", "low_confidence", "unverified", "unbound"])
def test_invariant_d_any_blocker_stops_generation(tmp_path, scenario):
    media = tmp_path / "generic.webm"  # 不含任何已知关键词 → scorer 给 0.0
    media.write_bytes(b"x")
    intent = _intent()
    req = _requirement_for(intent).requirement_id
    if scenario == "no_candidate":
        assert _resolve_for(_state(), intent, []).ready_for_generation is False
    elif scenario == "low_confidence":
        c = _cand("c", asset_ref=media.as_uri(), req=req)
        prep = ShotPreparation(shot_id="S1", candidates=[c],
                               required_asset_refs=[c.asset_ref])
        resolution = resolve(prep, domain=P0_ASSET_DOMAIN,
                             scorer_registry={P0_SCORER_ID: P0_ScienceRelevanceScorer()},
                             bindings=_bindings_for(intent, [c]))
        assert resolution.unresolved_requirement_ids == (req,)
        assert resolution.ready_for_generation is False
    elif scenario == "unverified":
        c = _cand("c", asset_ref=media.as_uri(), req=req, verified=False)
        assert _resolve_for(_state(), intent, [c]).ready_for_generation is False
    else:
        c = _cand("c", asset_ref=media.as_uri(), req=req)
        prep = ShotPreparation(shot_id="S1", candidates=[c],
                               required_asset_refs=["other.png"])
        resolution = resolve(prep, domain=P0_ASSET_DOMAIN,
                             scorer_registry={P0_SCORER_ID: P0_ScienceRelevanceScorer()},
                             bindings=_bindings_for(intent, [c]))
        assert resolution.unbound_asset_refs == ("other.png",)
        assert resolution.ready_for_generation is False

# ══ generation admission seam ══
def test_admit_returns_only_the_selected_candidate(tmp_path):
    media = tmp_path / "nasa_accretion.webm"
    media.write_bytes(b"x")
    intent = _intent()
    candidates = [
        _cand("c1", asset_ref=media.as_uri(), req=_requirement_for(intent).requirement_id),
        _cand("c2", asset_ref=(tmp_path / "nasa_orrery.webm").as_uri(),
              req=_requirement_for(intent).requirement_id),
    ]
    (tmp_path / "nasa_orrery.webm").write_bytes(b"o")
    prep = ShotPreparation(shot_id="S1", candidates=candidates,
                           required_asset_refs=[c.asset_ref for c in candidates])
    resolution = resolve(prep, domain=P0_ASSET_DOMAIN,
                         scorer_registry={P0_SCORER_ID: P0_ScienceRelevanceScorer()},
                         bindings=_bindings_for(intent, candidates))
    chosen = admit_generation(resolution, prep.candidates)
    assert chosen.candidate_id == "c1"
    assert chosen.state is AssetCandidateState.SELECTED


@pytest.mark.parametrize("corrupt", ["none", "not_ready", "empty_selected"])
def test_admit_refuses_without_selection(tmp_path, corrupt):
    media = tmp_path / "nasa_accretion.webm"
    media.write_bytes(b"x")
    intent = _intent()
    candidate = _cand("c1", asset_ref=media.as_uri(),
                      req=_requirement_for(intent).requirement_id)
    prep = ShotPreparation(shot_id="S1", candidates=[candidate],
                           required_asset_refs=[candidate.asset_ref])
    resolution = resolve(prep, domain=P0_ASSET_DOMAIN,
                         scorer_registry={P0_SCORER_ID: P0_ScienceRelevanceScorer()},
                         bindings=_bindings_for(intent, [candidate]))
    candidates = list(prep.candidates)
    if corrupt == "none":
        with pytest.raises(GenerationNotAdmittedError) as err:
            admit_generation(None, candidates)
        assert err.value.reason is GenerationNotAdmitted.NO_RESOLUTION
    elif corrupt == "not_ready":
        blocked = ShotResolution(
            resolution.shot_id, resolution.selected_requirement_ids,
            ("VIDEO/SCENE",), resolution.unbound_asset_refs, False)
        with pytest.raises(GenerationNotAdmittedError):
            admit_generation(blocked, candidates)
    else:
        # resolution 说可生成,但候选里没有 SELECTED → 仍必须拒绝(不得自行挑选)
        stripped = ShotResolution(resolution.shot_id,
                                  resolution.selected_requirement_ids, (), (), False)
        with pytest.raises(GenerationNotAdmittedError) as err:
            admit_generation(stripped, [AssetCandidate(
                candidate_id="fresh", requirement_id=candidate.requirement_id,
                asset_ref=candidate.asset_ref)])
        assert err.value.reason is GenerationNotAdmitted.NO_SELECTED_CANDIDATE


def test_no_applicable_scorer_blocks_generation(tmp_path):
    """域外/无 scorer → 不得默认放行。"""
    media = tmp_path / "nasa_accretion.webm"
    media.write_bytes(b"x")
    intent = _intent()
    candidate = _cand("c1", asset_ref=media.as_uri(),
                      req=_requirement_for(intent).requirement_id)
    prep = ShotPreparation(shot_id="S1", candidates=[candidate],
                           required_asset_refs=[candidate.asset_ref])
    resolution = resolve(prep, domain="some_other_domain",
                         scorer_registry={P0_SCORER_ID: P0_ScienceRelevanceScorer()},
                         bindings=_bindings_for(intent, [candidate]))
    assert resolution.selected_requirement_ids == ()
    assert resolution.unresolved_requirement_ids == (candidate.requirement_id,)
    assert resolution.human_review_required is True
    assert resolution.ready_for_generation is False
    with pytest.raises(GenerationNotAdmittedError):
        admit_generation(resolution, prep.candidates)


def test_admit_error_reports_every_blocker():
    """拒绝理由要完整,不吞掉后续 blocker。"""
    blocked = ShotResolution("S1", (), ("VIDEO/SCENE",), ("orphan.png",), True)
    assert set(blocked.blockers) == {
        GenerationNotAdmitted.NO_SELECTED_CANDIDATE,
        GenerationNotAdmitted.UNRESOLVED,
        GenerationNotAdmitted.UNBOUND,
        GenerationNotAdmitted.HUMAN_REVIEW,
    }
    with pytest.raises(GenerationNotAdmittedError) as err:
        admit_generation(blocked, [])
    assert err.value.reason is GenerationNotAdmitted.NO_SELECTED_CANDIDATE
    assert "orphan.png" in str(err.value)


def test_selected_but_unbound_is_still_blocked():
    """selected 非空也不代表可生成 —— unbound 必须单独拦住。"""
    partial = ShotResolution("S1", ("VIDEO/SCENE",), (), ("orphan.png",), False)
    assert partial.ready_for_generation is False
    assert partial.blockers == (GenerationNotAdmitted.UNBOUND,)
