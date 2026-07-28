"""DirectorWorksRepository 行序列化单测（P0 持久化,2026-07-23）——纯函数,不碰 DB。"""

from __future__ import annotations

from hevi.director.works_repository import _VOLUME_KEYS, _rec_to_row


def test_rec_to_row_maps_all_five_volumes_and_scalars() -> None:
    rec = {
        "user_id": "u1",
        "status": "scene_script_locked",
        "locked_through": 4,
        "visual_style": "inkwash",
        "material_text": "王六郎……",
        "video_task_id": "task-abc",
        "concept": {"theme": "报恩"},
        "screenplay": {"scenes": []},
        "design_list": {"characters": []},
        "world_bible": {"visual": {}},
        "scene_script": {"scripts": [{"scene_ref": 1}]},
    }
    row = _rec_to_row("w1", rec)
    assert row["work_id"] == "w1"
    assert row["user_id"] == "u1"
    assert row["status"] == "scene_script_locked"
    assert row["locked_through"] == 4
    assert row["visual_style"] == "inkwash"
    assert row["video_task_id"] == "task-abc"
    # 五卷逐一落列,原样 dict
    for k in _VOLUME_KEYS:
        assert row[k] == rec[k]
    assert row["scene_script"]["scripts"][0]["scene_ref"] == 1
    assert "updated_at" in row


def test_rec_to_row_defaults_for_partial_work() -> None:
    # 只到 concept 的半成品:未生成的卷存 None,标量给缺省
    rec = {"user_id": "u2", "concept": {"theme": "x"}}
    row = _rec_to_row("w2", rec)
    assert row["status"] == ""
    assert row["locked_through"] == -1
    assert row["visual_style"] == "realistic"
    assert row["material_text"] == ""
    assert row["video_task_id"] is None
    assert row["concept"] == {"theme": "x"}
    assert row["screenplay"] is None
    assert row["scene_script"] is None
