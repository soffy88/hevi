from __future__ import annotations

import json
from pathlib import Path

import pytest

from hevi.narrative.bible import restore_bible
from hevi.narrative.contract import NARRATIVE_CONTRACT_VERSION, contract_snapshot
from hevi.narrative.errors import ERROR_CODES, NarrativeFailure, fail_closed
from hevi.narrative.models import (
    Character,
    NarrativeAssertion,
    SceneBlueprint,
    StoryBible,
    StoryPremise,
    to_dict,
)
from hevi.narrative.persistence import persist_bible
from hevi.narrative.revision import NarrativeRevision, RevisionStore, StaleRevisionError


def _minimal() -> StoryBible:
    return StoryBible(
        project_id="compat",
        premise=StoryPremise("original premise"),
        characters=(Character("c1", "A"),),
        established_facts=(NarrativeAssertion("f1", "fact", "SOURCE_FACT", ("src:1",), True),),
    )


def test_narrative_v1_contract_snapshot() -> None:
    snapshot = contract_snapshot()
    assert NARRATIVE_CONTRACT_VERSION == 1
    assert snapshot["contract_version"] == 1
    assert "SceneBlueprint" in snapshot["schema_versions"]
    assert snapshot["ShotAdapter"]["renderer_dependency"] is False


def test_story_bible_backward_compatibility() -> None:
    payload = json.loads(json.dumps(to_dict(_minimal())))
    assert restore_bible(payload).project_id == "compat"


def test_scene_blueprint_backward_compatibility() -> None:
    fields = set(SceneBlueprint.__dataclass_fields__)
    assert {"scene_id", "sequence_id", "purpose", "objective", "continuity_constraints"} <= fields


def test_revision_receipt_backward_compatibility(tmp_path: Path) -> None:
    receipt = persist_bible(_minimal(), tmp_path / "bible.json")
    assert {"asset_id", "previous_revision", "new_revision", "committed", "validation"} <= set(receipt.__dataclass_fields__)


def test_provenance_backward_compatibility() -> None:
    fields = set(contract_snapshot()["NarrativeProvenance"])
    assert {"project_revision", "story_bible_revision", "source_refs", "shot_plan_id"} <= fields


def test_fail_closed_taxonomy_is_explicit() -> None:
    assert len(ERROR_CODES) == 10
    for code in ERROR_CODES:
        with pytest.raises(NarrativeFailure, match=code):
            fail_closed(code)


def test_stale_revision_is_fail_closed() -> None:
    store = RevisionStore()
    store.commit(NarrativeRevision("a", None, "1", "create", "initial", "test", "now"))
    with pytest.raises(StaleRevisionError):
        store.commit(NarrativeRevision("a", None, "2", "edit", "stale", "test", "now"))
