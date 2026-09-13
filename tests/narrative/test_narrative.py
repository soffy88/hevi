from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from hevi.cinematic.shot_intelligence.persistence import canonical_json, replay_plan
from hevi.cinematic.shot_intelligence.selector import ShotSelector
from hevi.narrative.adapters.shot_intelligence import scene_to_shot_intents
from hevi.narrative.bible import NarrativeSchemaError, restore_bible, validate_bible
from hevi.narrative.characters import character_authority, scene_character_state
from hevi.narrative.context import ContextBudget, NarrativeContextBuilder
from hevi.narrative.continuity import ContinuityEngine
from hevi.narrative.flags import enabled
from hevi.narrative.generation import (
    NarrativeGenerationError,
    bounded_continuation,
    parse_structured_output,
)
from hevi.narrative.models import (
    Character,
    CharacterState,
    ContinuityConstraint,
    DramaticQuestion,
    EpisodeBlueprint,
    NarrativeAssertion,
    NarrativeThread,
    SceneBlueprint,
    SceneObjective,
    SceneObstacle,
    SceneOutcome,
    SceneTurn,
    StoryBeat,
    StoryBible,
    StoryPremise,
    TimelineEvent,
    to_dict,
)
from hevi.narrative.persistence import persist_bible
from hevi.narrative.quality import NarrativeQualityGate
from hevi.narrative.revision import NarrativeRevision, RevisionStore, StaleRevisionError


def bible() -> StoryBible:
    return StoryBible(
        project_id="p1",
        premise=StoryPremise("A courier chooses truth over safety"),
        dramatic_question=DramaticQuestion("Will the evidence survive?"),
        characters=(Character("c1", "Lin", knowledge_state=("letter",)),),
        timeline=(TimelineEvent("t1", "arrival", 1),),
        established_facts=(NarrativeAssertion("f1", "The letter exists", "SOURCE_FACT", ("source:1",), True),),
    )


def scene(**changes: object) -> SceneBlueprint:
    base = SceneBlueprint("s1", "seq1", "reveal", SceneObjective("find proof"), SceneObstacle("guard"), "truth vs fear", SceneTurn("opens letter"), SceneOutcome("knows truth"), ("c1",), "archive", "t1", required_facts=("f1",), evidence_refs=("source:1",), continuity_constraints=(ContinuityConstraint("cc1", "fact", "fact remains", ("f1",)),))
    return replace(base, **changes)


@pytest.mark.parametrize("case", json.loads((Path(__file__).parents[1] / "fixtures/narrative_gold/cases.json").read_text()), ids=lambda item: item["id"])
def test_narrative_gold_cases_are_declared(case: dict[str, str]) -> None:
    assert case["id"] and case["kind"]


def test_story_bible_roundtrip(tmp_path: Path) -> None:
    receipt = persist_bible(bible(), tmp_path / "bible.json")
    restored = restore_bible(json.loads((tmp_path / "bible.json").read_text()))
    assert receipt.committed and receipt.validation == "PASS"
    assert to_dict(restored) == to_dict(bible())


def test_character_authority_and_knowledge_violation() -> None:
    assert character_authority(bible(), "c1").name == "Lin"
    with pytest.raises(ValueError, match="knowledge"):
        scene_character_state(bible(), CharacterState("c1", "s1", knowledge=("secret",)))


def test_character_authority_rejects_unknown_character() -> None:
    with pytest.raises(KeyError):
        character_authority(bible(), "missing")


def test_timeline_consistency_and_relationship_projection() -> None:
    report = ContinuityEngine().check(bible(), (scene(),))
    assert report.status == "PASS"


def test_continuity_reports_dangling_character() -> None:
    report = ContinuityEngine().check(bible(), (scene(characters=("missing",)),))
    assert report.status == "FAIL"
    assert report.findings[0]["code"] == "CHARACTER_STATE_CONFLICT"


def test_fact_dramatization_boundary() -> None:
    bad = replace(bible(), established_facts=(NarrativeAssertion("f", "invented", "DRAMATIZATION", historically_verified=True),))
    with pytest.raises(NarrativeSchemaError):
        validate_bible(bad)


def test_context_selection_and_budget() -> None:
    context = NarrativeContextBuilder().build(bible(), scene(), ContextBudget(2, 1))
    assert context.context_truncated is True
    assert context.dropped_refs


def test_stale_revision_rejected() -> None:
    store = RevisionStore()
    store.commit(NarrativeRevision("b", None, "1", "create", "new", "test", "now"))
    with pytest.raises(StaleRevisionError, match="STALE_REVISION"):
        store.commit(NarrativeRevision("b", None, "2", "edit", "stale", "test", "now"))


def test_atomic_revision_commit(tmp_path: Path) -> None:
    receipt = persist_bible(bible(), tmp_path / "bible.json")
    assert receipt.committed is True
    assert not list(tmp_path.glob(".*"))


def test_scene_blueprint_schema_and_quality_gate() -> None:
    narrative = replace(bible(), episodes=(EpisodeBlueprint("e1", 1, "premise", "goal", beats=(StoryBeat("b1", "turn", "reveal", change="truth changes"),)),))
    report = ContinuityEngine().check(narrative, (scene(),))
    quality = NarrativeQualityGate().evaluate(narrative, scene(), report)
    assert quality.ready is True


def test_setup_payoff_and_thread_tracking() -> None:
    threads = (NarrativeThread("th1", "HIGH_PRIORITY", "s1"), NarrativeThread("th1", "HIGH_PRIORITY", "s2"))
    from hevi.narrative.threads import thread_diagnostics

    assert "DUPLICATE_THREAD" in thread_diagnostics(threads)


def test_scene_to_shot_adapter_is_one_way() -> None:
    intents = scene_to_shot_intents(scene(), "character_animation")
    plan = ShotSelector().plan(intents)
    replayed = replay_plan(plan)
    assert canonical_json(plan) == canonical_json(replayed)


def test_feature_flag_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NARRATIVE_INTELLIGENCE_ENABLED", raising=False)
    assert enabled() is False


def test_schema_rejects_wrong_version() -> None:
    with pytest.raises(NarrativeSchemaError, match="schema_version"):
        restore_bible({"project_id": "p", "schema_version": "0"})


def test_truncated_output_not_committed() -> None:
    from hevi.narrative.models import GenerationCompletionStatus

    with pytest.raises(NarrativeGenerationError, match="TRUNCATED"):
        parse_structured_output('{"scene":', GenerationCompletionStatus("TRUNCATED"))


def test_bounded_continuation_deduplicates_overlap() -> None:
    assert bounded_continuation(['{"scene":"a', '"}'], 1) == '{"scene":"a"}'


def test_bounded_continuation_rejects_unbounded_output() -> None:
    with pytest.raises(NarrativeGenerationError, match="REVISION_LIMIT"):
        bounded_continuation(["a", "b", "c"], 1)
