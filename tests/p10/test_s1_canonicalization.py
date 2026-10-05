"""S1 行为验收:resolver adapter / verdict aggregator / manifest / one-line dry-run。"""

import json

import pytest

from hevi.creative.autonomous import (
    AssetResolver,
    DryRunResult,
    ProductionVerdictAuthority,
    VerdictInput,
    VerdictOutcome,
    assert_no_secrets,
    dry_run,
    to_manifest,
)
from hevi.creative.autonomous.canonical import (
    AssetDecisionAuthority,
    AssetRequirement,
    AssetSemanticRole,
    MediaType,
    to_asset_requirement,
    to_visual_intent,
)
from hevi.production.p7.evidence import AssetEvidence, AssetStatus
from hevi.validation.artifact import CheckOperator, ValidationCheck, ValidationResult

SPEC_PROMPT = ("做一个45秒的视频，解释为什么AI视频质量取决于导演而不只是模型，"
               "科技感、快节奏、适合短视频。")


def _req(role: AssetSemanticRole = AssetSemanticRole.SCENE) -> AssetRequirement:
    return AssetRequirement(media_type=MediaType.VIDEO, semantic_role=role,
                            constraints=(("query", "futuristic control room"),))


def _valid_artifact() -> ValidationResult:
    return ValidationResult(
        validator="test", checks=(ValidationCheck(name="exists", observed=True,
                                                  operator=CheckOperator.NON_EMPTY),))


def _blocked_artifact() -> ValidationResult:
    return ValidationResult(
        validator="test", checks=(ValidationCheck(name="exists", observed=None,
                                                  expected=True,
                                                  operator=CheckOperator.EQ),))


# ── resolver adapter ──
async def test_resolver_without_provider_decision_is_blocked_not_defaulted():
    """provider authority 未被咨询 → p7 BLOCKED,resolver 不兜底、不选 provider。"""
    out = await AssetResolver().resolve(_req(), provider_decision=None)
    assert out.blocked and "NO_PROVIDER_DECISION" in out.reason
    assert out.usable is False and out.provider_id == ""


async def test_resolver_cannot_override_p7_block():
    """即便 provider decision 存在,缺 evidence + selected_source 时 p7 仍阻塞。"""
    from hevi.provider_policy.policy import ProviderDecision

    decision = ProviderDecision(selected_provider="local_ffmpeg", eligible=["local_ffmpeg"],
                               considered=["local_ffmpeg"])
    out = await AssetResolver().resolve(_req(), provider_decision=decision)
    assert out.blocked  # NO_ASSET_EVIDENCE / NO_ASSET_OBTAINED
    assert out.provider_id == "local_ffmpeg"


async def test_resolver_executes_and_returns_execution_ready():
    """有 acquirer 时:执行 → 回填 evidence → p7 ACCEPTED。"""
    from hevi.provider_policy.policy import ProviderDecision

    evidence = AssetEvidence(asset_id="asset-1", source="local", status=AssetStatus.AVAILABLE,
                             license="CC0", validation="probe_ok")

    class Acquirer:
        async def acquire(self, requirement, provider_id, context):
            return "media_assets/control_room.mp4", evidence

    decision = ProviderDecision(selected_provider="local_assets", eligible=["local_assets"],
                               considered=["local_assets"])
    out = await AssetResolver(acquirer=Acquirer()).resolve(_req(), provider_decision=decision)
    assert out.usable and out.decision_state == "ACCEPTED"
    # F10:字段名从 selected_source 改为 obtained_source —— 它记录「取得」,
    # 不是「选中」。旧名会让人把它当成素材取舍结论。
    assert out.obtained_source == "media_assets/control_room.mp4"
    assert out.evidence_ids  # evidence 已回填


# ── verdict aggregator ──
def test_verdict_requires_all_inputs_and_valid_artifact():
    authority = ProductionVerdictAuthority()
    verdict = authority.evaluate(
        inputs=(VerdictInput(source="verdict/final_review", passed=True),
                VerdictInput(source="verdict/delivery_gate", passed=True)),
        artifact_validation=_valid_artifact())
    assert verdict.outcome is VerdictOutcome.PASS and verdict.is_final


def test_verdict_blocks_when_no_evidence():
    """无既有结论 = BLOCKED(证据不足),不是 PASS。"""
    verdict = ProductionVerdictAuthority().evaluate(inputs=(), artifact_validation=_valid_artifact())
    assert verdict.outcome is VerdictOutcome.BLOCKED and not verdict.is_final


def test_verdict_blocks_when_artifact_missing_or_invalid():
    authority = ProductionVerdictAuthority()
    good = (VerdictInput(source="verdict/final_review", passed=True),)
    assert authority.evaluate(inputs=good, artifact_validation=None).outcome is VerdictOutcome.BLOCKED
    failed = authority.evaluate(inputs=good, artifact_validation=_blocked_artifact())
    assert failed.outcome is VerdictOutcome.FAIL
    assert failed.failing_sources() == ()


def test_verdict_fails_if_any_existing_gate_failed():
    verdict = ProductionVerdictAuthority().evaluate(
        inputs=(VerdictInput(source="verdict/final_review", passed=True),
                VerdictInput(source="verdict/delivery_gate", passed=False, detail="loudness")),
        artifact_validation=_valid_artifact())
    assert verdict.outcome is VerdictOutcome.FAIL
    assert verdict.failing_sources() == ("verdict/delivery_gate",)


def test_verdict_rejects_untraceable_input():
    with pytest.raises(ValueError, match="VERDICT_UNTRACEABLE"):
        ProductionVerdictAuthority().evaluate(inputs=(VerdictInput(source="", passed=True),),
                                             artifact_validation=_valid_artifact())


# ── manifest(唯一绿地)──
def test_manifest_is_deterministic_projection():
    result = DryRunResult(production_id="p1", request="x", summary={"a": 1})
    first, second = to_manifest(result), to_manifest(result)
    assert first.content_hash() == second.content_hash()
    payload = first.to_dict()
    assert payload["schema_version"] == "autonomous-production-manifest/1"
    assert {"production_id", "request", "director_plan", "stages", "status"} <= set(payload)


def test_manifest_refuses_secrets_but_allows_refs():
    with pytest.raises(ValueError, match="SECRET_IN_MANIFEST"):
        assert_no_secrets({"render": {"token": "abc"}})
    assert_no_secrets({"render": {"auth_ref": "env:RENDER_KEY"}})


def test_manifest_roundtrips_json(tmp_path):
    manifest = to_manifest(DryRunResult(production_id="p1", request="x", summary={"k": "v"}))
    path = manifest.write(tmp_path / "production_manifest.json")
    assert json.loads(path.read_text(encoding="utf-8"))["production_id"] == "p1"


# ── adapters ──
def test_to_visual_intent_uses_canonical_contract():
    from hevi.creative.autonomous.canonical import (
        Concept,
        DesignList,
        Screenplay,
        ShotList,
        ShotListItem,
    )

    item = ShotListItem(shot_id="S1", scene_no=1, shot_size="wide", camera="push_in",
                        character_names=["ann"], scene_name="lab", recipe="coverage")
    intent = to_visual_intent(item, timeline_lock_id="tl:1", start_s=0.0, end_s=4.0)
    assert intent.intent_id == "vi:S1" and intent.timeline_lock_id == "tl:1"
    assert intent.required_entities == ("ann",) and "lab" in intent.required_concepts
    assert intent.motion_purpose == "push_in"  # 直接映射,无新字段
    assert Concept() is not None and DesignList() is not None
    assert Screenplay() is not None and ShotList() is not None


def test_to_asset_requirement_uses_p7_contract():
    from hevi.creative.autonomous.canonical import ShotListItem

    item = ShotListItem(shot_id="S1", scene_no=1, duration_s=3.0,
                        visual_prompt="futuristic control room")
    req = to_asset_requirement(item, semantic_role=AssetSemanticRole.SCENE)
    assert isinstance(req, AssetRequirement)
    assert req.requirement_id and req.quality_floor == 7
    assert "duration" in req.constraint_map() and "query" in req.constraint_map()
    # 只用 p7 KNOWN_CONSTRAINTS:错键(如把 shot_size 塞进 period)会污染 provider 检索
    assert not req.unknown_constraints()
    assert "period" not in req.constraint_map()


def test_asset_decision_authority_is_stateless_and_reused():
    """resolver 用的是 p7 authority,不是自建决策。"""
    assert AssetDecisionAuthority.authority_id == "p7_0_asset_decision"
    resolution = AssetDecisionAuthority().decide(_req(), provider_decision=None)
    assert resolution.decision.state.value == "BLOCKED"


# ── one-line dry-run ──
async def test_one_line_dry_run_produces_full_plan(tmp_path):
    result = await dry_run(SPEC_PROMPT, out_dir=tmp_path)
    assert result.summary["director_entry"] == "director_pipeline:semantic_spine"
    assert result.summary["scenes"] >= 1
    assert result.summary["shots"] >= 1
    assert result.asset_requirements
    assert len(result.stage_plan) >= 6
    assert result.summary["paid_provider_called"] is False
    assert result.summary["gpu_required"] is False
    for name in ("plan", "script", "asset_plan", "stage_plan"):
        assert (tmp_path / f"{name}.json").is_file()


async def test_dry_run_records_vocabulary_splits():
    """分裂必须随 dry-run 一起暴露,不能藏起来。"""
    result = await dry_run(SPEC_PROMPT)
    concepts = {s["concept"] for s in result.vocabulary_splits}
    assert "ProviderPolicy/ProviderDecision" in concepts
    assert all(s["seam"] for s in result.vocabulary_splits)


async def test_dry_run_manifest_is_produced():
    manifest = to_manifest(await dry_run(SPEC_PROMPT))
    assert manifest.status == "PLANNED"
    assert manifest.provenance["dry_run"] is True
    assert manifest.content_hash()