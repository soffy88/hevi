from hevi.quality import (
    FailureCode,
    GatePolicy,
    QualityEvaluation,
    QualityEvidence,
    RepairBudget,
    RepairController,
    apply_repair_decision,
)


def _failed(code: FailureCode, scope: str = "shot:S01") -> QualityEvidence:
    return QualityEvidence(code=code, scope=scope, passed=False)


# Identity / audio / scene drift are the P2 injection set from the architecture RFC.
_REPAIR_CORPUS: list[tuple[FailureCode, str]] = [
    (FailureCode.IDENTITY_MISMATCH, "replace_reference"),
    (FailureCode.WARDROBE_MISMATCH, "recompile_prompt"),
    (FailureCode.SCENE_CONTINUITY, "recompile_prompt"),
    (FailureCode.SCREEN_DIRECTION, "recompile_prompt"),
    (FailureCode.EYELINE_VIOLATION, "recompile_prompt"),
    (FailureCode.ANATOMY_ARTIFACT, "retry_new_seed"),
    (FailureCode.CAMERA_CONTRACT, "recompile_prompt"),
    (FailureCode.ACTION_MISSING, "retry_new_seed"),
    (FailureCode.DIALOGUE_MISSING, "recompile_prompt"),
    (FailureCode.AUDIO_QUALITY, "recompile_prompt"),
    (FailureCode.TIMING_PACING, "recompile_prompt"),
    (FailureCode.STYLE_DRIFT, "recompile_prompt"),
    (FailureCode.PROVIDER_FAILURE, "switch_provider"),
    (FailureCode.QUOTA_OR_BALANCE, "switch_provider"),
    (FailureCode.DELIVERY_INTEGRITY, "retry_new_seed"),
    (FailureCode.SAFETY_POLICY, "human_review"),
    (FailureCode.QUALITY_CHECKER_FAILURE, "human_review"),
]


def test_repair_corpus_covers_taxonomy() -> None:
    covered = {code for code, _ in _REPAIR_CORPUS}
    assert len(covered) / len(FailureCode) >= 0.90


def test_repair_corpus_maps_to_scoped_actions_and_patches() -> None:
    policy = GatePolicy(
        profile="cinema",
        required_failures=set(FailureCode),
        advisory_failures=set(),
        allow_checker_failure=False,
    )
    hits = 0
    for code, expected_kind in _REPAIR_CORPUS:
        controller = RepairController(RepairBudget(max_attempts=1, max_cost_usd=10.0))
        evaluation = QualityEvaluation.from_evidence([_failed(code)], policy)
        controller.observe(evaluation)
        decision = controller.decide(evaluation)
        auto_kinds = {
            "regenerate_same_provider",
            "retry_new_seed",
            "recompile_prompt",
            "replace_reference",
            "switch_provider",
        }
        if expected_kind in auto_kinds:
            assert decision.should_repair, code
            assert decision.actions[0].kind == expected_kind
            patch = apply_repair_decision(
                decision,
                current_provider="ltx2_cloud",
                fallback_candidates=["ltx2_cloud", "veo3"],
                current_seed=3,
            )
            assert patch.consumed
            assert 1 in patch.shot_indexes
            if expected_kind == "replace_reference":
                assert patch.replace_references
            if expected_kind == "recompile_prompt":
                assert patch.recompile_prompt
            if expected_kind == "retry_new_seed":
                assert patch.seed == 4
            if expected_kind == "switch_provider":
                assert patch.provider_id == "veo3"
            hits += 1
        else:
            assert not decision.should_repair, code
            assert decision.stop_reason == "manual_repair_required"
            hits += 1
    assert hits / len(_REPAIR_CORPUS) >= 0.90


def test_identity_audio_and_scene_injection_set_is_executable() -> None:
    policy = GatePolicy.for_profile("cinema")
    cases = [
        FailureCode.IDENTITY_MISMATCH,
        FailureCode.DIALOGUE_MISSING,
        FailureCode.SCENE_CONTINUITY,
    ]
    for code in cases:
        controller = RepairController(RepairBudget(max_attempts=2, max_cost_usd=5.0))
        failed = QualityEvaluation.from_evidence([_failed(code, "shot:12")], policy)
        controller.observe(failed)
        decision = controller.decide(failed)
        assert decision.should_repair
        patch = apply_repair_decision(
            decision,
            current_provider="wan_cloud",
            fallback_candidates=["wan_cloud", "ltx2_cloud"],
            current_seed=0,
        )
        assert patch.consumed
        assert patch.shot_indexes == [12]
        assert patch.config_updates()["repair_patch"]
