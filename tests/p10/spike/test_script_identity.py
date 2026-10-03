"""G0.2-A spike tests: ScriptUnit identity across revisions (T1-T4 + reverse)."""

from hevi.director.pipeline_schemas import ScreenplayDialogueLine
from hevi.director.script_identity import (
    ScriptUnit,
    assign_unit_ids,
    inherit_unit_ids,
    resolve_unit,
)


def _units(*texts: str, scene: str = "scene1") -> list[ScriptUnit]:
    return [ScriptUnit("", scene, i, t) for i, t in enumerate(texts)]


def test_t1_create_assigns_stable_ids():
    out = assign_unit_ids(_units("A", "B", "C"))
    ids = [u.unit_id for u in out]
    assert ids == ["scene1.line001", "scene1.line002", "scene1.line003"]
    # 确定性:重复补 ID 结果一致
    assert [u.unit_id for u in assign_unit_ids(out)] == ids


def test_t2_insert_keeps_existing_ids():
    old = assign_unit_ids(_units("A", "B", "C"))
    new = inherit_unit_ids(old, [("scene1", "A", ""), ("scene1", "X", ""), ("scene1", "B", ""), ("scene1", "C", "")])
    by_text = {u.text: u for u in new}
    assert by_text["B"].unit_id == old[1].unit_id  # 禁止 B -> id+1
    assert by_text["C"].unit_id == old[2].unit_id
    assert by_text["X"].revision == 1 and by_text["X"].unit_id not in {u.unit_id for u in old}


def test_t1_reword_inherits_id_with_revision_bump():
    old = assign_unit_ids(_units("The black hole bends light"))
    new = inherit_unit_ids(old, [("scene1", "The black hole bends spacetime", "")])
    assert new[0].unit_id == old[0].unit_id
    assert new[0].revision == old[0].revision + 1


def test_t3_reorder_keeps_ids():
    old = assign_unit_ids(_units("A", "B", "C"))
    new = inherit_unit_ids(old, [("scene1", "C", ""), ("scene1", "A", ""), ("scene1", "B", "")])
    assert [u.text for u in new] == ["C", "A", "B"]
    assert {u.unit_id for u in new} == {u.unit_id for u in old}
    assert [u.order for u in new] == [0, 1, 2]


def test_rule3_deleted_id_never_reused():
    old = assign_unit_ids(_units("A", "B", "C"))
    gone = old[1].unit_id
    new = inherit_unit_ids(old, [("scene1", "A", ""), ("scene1", "C", ""), ("scene1", "D", "")])
    assert gone not in {u.unit_id for u in new}
    assert resolve_unit(new, gone) is None  # orphan 可检测


def test_t4_cross_reference_model_carries_unit_id():
    line = ScreenplayDialogueLine(character_name="道白", text="A", unit_id="scene1.line001")
    assert line.unit_id == "scene1.line001"
    assert ScreenplayDialogueLine(character_name="x", text="y").unit_id == ""  # 老数据兼容
    assert line.model_dump()["unit_id"] == "scene1.line001"  # 序列化往返
