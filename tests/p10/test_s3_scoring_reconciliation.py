"""S3:两套评分并存 + 按适用域自动选择(canonical 层,不碰 autonomous/)。

验证的核心安全性质:**不适用的 scorer = 不可用,不是低分。**
题材不匹配的硬编码打分器若对所有候选打低分,「低分里挑最高」就是静默误选。
"""


from hevi.creative.autonomous import resolver as autonomous_resolver
from hevi.production.p1_pipeline import (
    ASSET_FITNESS_APPLICABLE_DOMAINS,
    asset_fitness_applies,
)
from hevi.production.p1_types import AssetFitness
from hevi.production.shot_readiness import (
    NO_APPLICABLE_SCORER,
    REVIEW_CONFIDENCE_FLOOR,
    AssetCandidate,
    AssetCandidateState,
    ShotPreparation,
    applicable_scorers,
    score_candidates,
    select_candidate,
)


def _cand(cid: str, *, confidence: float = 0.0, verified: bool = True,
          scored_by: str = "", req: str = "req-1") -> AssetCandidate:
    return AssetCandidate(candidate_id=cid, requirement_id=req, asset_ref=f"a://{cid}",
                          confidence=confidence, verified=verified, scored_by=scored_by)


def _prep(*candidates: AssetCandidate) -> ShotPreparation:
    return ShotPreparation(shot_id="S1", candidates=list(candidates))


# ── 适用域声明 ──
def test_scorer_without_declared_domain_is_never_applicable():
    """未声明适用域 = 不默认适用(fail-closed)。"""
    def bare(candidate):
        return 0.99

    assert applicable_scorers("black_hole", {"bare": bare}) == ()


def test_declared_domain_selects_deterministically():
    def a(candidate):
        return 0.9

    a.applicable_domains = frozenset({"black_hole", "space"})  # type: ignore[attr-defined]
    def b(candidate):
        return 0.8

    b.applicable_domains = frozenset({"space"})  # type: ignore[attr-defined]
    hits = applicable_scorers("space", {"b": b, "a": a})
    assert [sid for sid, _ in hits] == ["a", "b"]  # 字典序,不是「谁分高用谁」


def test_black_hole_fitness_declares_its_domain():
    assert asset_fitness_applies("black_hole") is True
    assert asset_fitness_applies("kitchen_knife") is False
    assert frozenset({"black_hole"}) == ASSET_FITNESS_APPLICABLE_DOMAINS


# ── 不适用 ≠ 低分 ──
def test_no_applicable_scorer_does_not_score_at_all():
    cands = [_cand("c1"), _cand("c2")]
    reason, out = score_candidates(cands, domain="kitchen_knife",
                                   registry={"bh": lambda c: 0.2})
    assert reason == NO_APPLICABLE_SCORER
    # 关键:分数保持 0(未被污染),来源仍为空
    assert all(c.confidence == 0.0 and c.scored_by == "" for c in out)


def test_applicable_scorer_records_provenance():
    def scorer(candidate):
        return 0.95

    scorer.applicable_domains = frozenset({"any"})  # type: ignore[attr-defined]
    sid, out = score_candidates([_cand("c1")], domain="any", registry={"s": scorer})
    assert sid == "s"
    assert out[0].confidence == 0.95 and out[0].scored_by == "s"
    assert any(line.startswith("scored:s") for line in out[0].lineage)


def test_inapplicable_scorer_would_have_been_a_silent_misrank():
    """回归:若把不适用当低分,两个候选会以 0.2/0.1 选出 0.2 —— 静默误选。"""
    cands = [_cand("c1", confidence=0.2, scored_by="bh"), _cand("c2", confidence=0.1, scored_by="bh")]
    reason, out = score_candidates(cands, domain="kitchen_knife",
                                   registry={"bh": lambda c: 0.2})
    assert reason == NO_APPLICABLE_SCORER
    assert select_candidate(_prep(*out), "req-1") is None  # 不选


# ── select_candidate 要求 canonical 来源 ──
def test_select_requires_scored_by_provenance():
    unscored = _cand("c1", confidence=0.95, scored_by="")
    assert select_candidate(_prep(unscored), "req-1") is None
    scored = _cand("c1", confidence=0.95, scored_by="s")
    assert select_candidate(_prep(scored), "req-1") is scored


def test_select_still_refuses_below_floor_and_unverified():
    low = _cand("c1", confidence=REVIEW_CONFIDENCE_FLOOR - 0.01, scored_by="s")
    assert select_candidate(_prep(low), "req-1") is None
    unverified = _cand("c1", confidence=0.95, verified=False, scored_by="s")
    assert select_candidate(_prep(unverified), "req-1") is None


def test_select_records_lineage_and_rejects_others():
    chosen = _cand("c1", confidence=0.9, scored_by="s")
    other = _cand("c2", confidence=0.8, scored_by="s")
    got = select_candidate(_prep(chosen, other), "req-1")
    assert got is chosen
    assert chosen.state is AssetCandidateState.SELECTED
    assert any(line.startswith("selected:") for line in chosen.lineage)
    assert other.state is AssetCandidateState.REJECTED


def test_scoring_skips_already_rejected_candidates():
    rejected = _cand("c1", scored_by="")
    rejected.state = AssetCandidateState.REJECTED

    def scorer(candidate):
        return 0.99

    scorer.applicable_domains = frozenset({"any"})  # type: ignore[attr-defined]
    score_candidates([rejected], domain="any", registry={"s": scorer})
    assert rejected.confidence == 0.0


# ── AssetCandidate 向后兼容 ──
def test_asset_candidate_defaults_unchanged():
    c = AssetCandidate(candidate_id="c", requirement_id="r", asset_ref="a")
    assert c.confidence == 0.0 and c.scored_by == "" and c.state is AssetCandidateState.CANDIDATE
    assert "scored_by" in c.to_dict()


def test_asset_fitness_weight_formula_still_the_canonical_one():
    """7 维权重不被改动(这是 p1_types 的既有 canonical 公式)。"""
    f = AssetFitness(asset_id="a", beat_id="b", entity_score=1.0, action_score=1.0,
                     state_score=1.0, temporal_score=1.0, shot_role_score=1.0,
                     motion_score=1.0, provenance_score=1.0)
    assert f.overall == 1.0
    one_dim = AssetFitness(asset_id="a", beat_id="b", entity_score=1.0, action_score=0.0,
                           state_score=0.0, temporal_score=0.0, shot_role_score=0.0,
                           motion_score=0.0, provenance_score=0.0)
    assert one_dim.overall == 0.25  # 仅 entity 维命中 = 其权重 .25
    two_dims = AssetFitness(asset_id="a", beat_id="b", entity_score=1.0, action_score=1.0,
                            state_score=0.0, temporal_score=0.0, shot_role_score=0.0,
                            motion_score=0.0, provenance_score=0.0)
    assert two_dims.overall == 0.5  # entity .25 + action .25


# ── autonomous 仍然不含 scoring ──
def test_autonomous_still_has_no_scoring_authority():
    for name in autonomous_resolver.FORBIDDEN_METHODS:
        assert not hasattr(autonomous_resolver.AssetResolver, name)
    assert not hasattr(autonomous_resolver, "score_candidates")