"""A3 production: unit_id wired into screenplay generation + revision inheritance."""

from unittest.mock import AsyncMock

from hevi.director.pipeline_schemas import Concept
from hevi.director.screenplay import _assign_scene_unit_ids, generate_screenplay_draft
from hevi.director.script_identity import ScriptUnit, inherit_unit_ids


def _llm(payload: str) -> AsyncMock:
    return AsyncMock(return_value={"content": payload})


def _units_from_screenplay(sp) -> list[ScriptUnit]:
    out = []
    for scene in sp.scenes:
        for line in scene.dialogue:
            out.append(ScriptUnit(line.unit_id, f"scene{scene.scene_no}", len(out), line.text))
    return out


TWO_SCENES = (
    '{"scenes": ['
    '{"scene_no": 1, "narration": "n1", "dialogue": ['
    '{"character_name": "A", "text": "line one"},'
    '{"character_name": "B", "text": "line two"}]},'
    '{"scene_no": 2, "narration": "n2", "dialogue": ['
    '{"character_name": "A", "text": "line three"}]}]}'
)


async def test_a3_generated_dialogue_gets_unit_ids():
    sp = await generate_screenplay_draft(concept=Concept(theme="t"), material_text="素材",
                                         llm=_llm(TWO_SCENES))
    ids = [line.unit_id for scene in sp.scenes for line in scene.dialogue]
    assert ids == ["scene1.line001", "scene1.line002", "scene2.line001"]
    assert len(set(ids)) == 3


def _scene():
    from hevi.director.pipeline_schemas import ScreenplayDialogueLine, ScreenplayScene

    return ScreenplayScene(scene_no=1, dialogue=[
        ScreenplayDialogueLine(character_name="A", text="x", unit_id="scene1.line007"),
        ScreenplayDialogueLine(character_name="A", text="y"),
    ])


def test_a3_helper_preserves_existing_ids():
    scene = _scene()
    _assign_scene_unit_ids([scene])
    # existing line007 kept; the un-numbered line takes its own ordinal, no collision
    assert [line.unit_id for line in scene.dialogue] == ["scene1.line007", "scene1.line002"]


async def test_a3_ids_survive_revision_insert():
    sp = await generate_screenplay_draft(concept=Concept(), material_text="素材", llm=_llm(TWO_SCENES))
    old = _units_from_screenplay(sp)
    # new revision: an inserted line inside scene1 shifts everything after it
    new_texts = [("scene1", "line one", ""), ("scene1", "inserted", ""),
                 ("scene1", "line two", ""), ("scene2", "line three", "")]
    new = inherit_unit_ids(old, new_texts)
    by_text = {u.text: u.unit_id for u in new}
    assert by_text["line one"] == "scene1.line001"
    assert by_text["line two"] == "scene1.line002"
    assert by_text["line three"] == "scene2.line001"
    assert by_text["inserted"] not in {u.unit_id for u in old}


async def test_a3_scene_cap_keeps_ids():
    from hevi.core.config import settings

    original = settings.director_max_scenes
    try:
        settings.director_max_scenes = 1
        sp = await generate_screenplay_draft(concept=Concept(), material_text="素材",
                                             llm=_llm(TWO_SCENES))
        assert len(sp.scenes) == 1
        assert [line.unit_id for line in sp.scenes[0].dialogue] == ["scene1.line001", "scene1.line002"]
    finally:
        settings.director_max_scenes = original