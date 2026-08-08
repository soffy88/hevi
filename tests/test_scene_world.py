"""Director World 场景一致性(3GS 轻量版)测试。

对标 DramaClaw Director World/3GS:同场景跨镜头锁定空间/机位/光照/走位,
产出后确定性一致性 gate。纯逻辑,不依赖 LLM。
"""

from __future__ import annotations

from hevi.director.pipeline_schemas import ShotBlocking, ShotListItem
from hevi.director.scene_world import (
    SceneState,
    SceneWorld,
    check_scene_consistency,
    consistency_passed,
)


def _shot(shot_id: str, scene_name: str, *, camera: str = "", prompt: str = "",
          blocking: list[ShotBlocking] | None = None) -> ShotListItem:
    return ShotListItem(
        shot_id=shot_id, scene_no=1, camera=camera, visual_prompt=prompt,
        scene_name=scene_name, blocking=blocking or [])


def test_scene_lock_prompt():
    st = SceneState(
        scene_name="客厅",
        layout="沙发居左,落地窗居右",
        lighting="冷调夜景",
        camera_defaults="平视中景",
        blocking_template="主角近窗",
    )
    lock = st.to_lock_prompt()
    assert "场景锁定:客厅" in lock
    assert "沙发居左" in lock and "冷调夜景" in lock


def test_scene_world_lock_prompt_for_registered():
    w = SceneWorld()
    w.register(SceneState(scene_name="客厅", layout="沙发居左"))
    assert "沙发居左" in w.lock_prompt_for("客厅")
    assert w.lock_prompt_for("未注册") == ""


def test_consistency_no_conflicts():
    shots = [
        _shot("A1", "客厅", camera="平视", prompt="人物在沙发旁"),
        _shot("A2", "客厅", camera="近景", prompt="人物走向窗边"),
    ]
    report = check_scene_consistency(shots)
    assert report["客厅"]["shot_count"] == 2
    assert report["客厅"]["conflicts"] == []
    assert consistency_passed(report) is True


def test_consistency_blocking_conflict():
    """同镜内同一角色两个矛盾位置 → conflict。"""
    shots = [
        _shot("B1", "客厅", camera="平视", prompt="x",
              blocking=[ShotBlocking(character_name="甲", position="左侧"),
                        ShotBlocking(character_name="甲", position="右侧")]),
    ]
    report = check_scene_consistency(shots)
    assert len(report["客厅"]["conflicts"]) == 1
    assert consistency_passed(report) is False


def test_consistency_lock_missing_when_world_registered():
    """SceneWorld 注册场景后,未带锁定的镜头记 lock_missing。"""
    w = SceneWorld()
    w.register(SceneState(scene_name="客厅", layout="沙发居左"))
    shots = [
        _shot("C1", "客厅", camera="平视", prompt="自由发挥的画面"),  # 无锁定前缀
        _shot("C2", "客厅", camera="近景",
              prompt="[场景锁定:客厅 | 空间:沙发居左] 画面"),
    ]
    report = check_scene_consistency(shots, scene_world=w)
    assert report["客厅"]["lock_missing"] == 1
    # lock_missing 记 warning 不阻断 gate
    assert consistency_passed(report) is True


def test_screenplay_mode_tails():
    """剧本三模式 prompt 尾注齐全(与 generate_screenplay_draft 的 mode 联动)。"""
    from hevi.director.screenplay import _SCREENPLAY_MODE_TAILS
    assert set(_SCREENPLAY_MODE_TAILS) == {"adaptive", "literal", "staged"}
    assert "贴原文" in _SCREENPLAY_MODE_TAILS["literal"]
    assert "舞台化" in _SCREENPLAY_MODE_TAILS["staged"]
