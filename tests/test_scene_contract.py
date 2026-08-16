"""3GS G1 前置测试: 镜头空间契约(越轴 / One-Move / 机位字段完备)。"""

from __future__ import annotations

from hevi.director.pipeline_schemas import ShotBlocking, ShotListItem
from hevi.director.scene_contract import (
    CameraContinuityReport,
    camera_angle_azimuth,
    check_axis_crossing,
    check_camera_continuity,
    check_camera_field_completeness,
    check_one_move_rule,
    screen_direction,
)


def _shot(
    shot_id: str,
    scene_no: int = 1,
    camera_angle: str = "正面",
    azimuth_deg: float | None = None,
    facing: str = "",
    action_beats: list[str] | None = None,
    characters: list[str] | None = None,
) -> ShotListItem:
    return ShotListItem(
        shot_id=shot_id,
        scene_no=scene_no,
        camera_angle=camera_angle,
        azimuth_deg=azimuth_deg,
        blocking=[ShotBlocking(character_name="A", facing=facing)] if facing else [],
        action_beats=action_beats or [],
        character_names=characters or [],
    )


# ---- 方位角 / 银幕方向推导 ----

def test_camera_angle_azimuth():
    assert camera_angle_azimuth("侧45°", None) == 45.0
    assert camera_angle_azimuth("右侧", None) == 90.0
    assert camera_angle_azimuth("", 180.0) == 180.0  # 显式 azimuth 优先
    assert camera_angle_azimuth("随便写", None) is None


def test_screen_direction():
    assert screen_direction("左侧", None) == "left"
    assert screen_direction("右侧", None) == "right"
    assert screen_direction("正面", None) == "front"
    assert screen_direction("背后", None) == "back"
    assert screen_direction("", 45.0) == "right"  # 方位角符号
    assert screen_direction("", -45.0) == "left"
    assert screen_direction("", 0.0) == "front"
    assert screen_direction("正面", None, facing="面向角色B左侧") == "left"  # facing 优先


# ---- 越轴检查 ----

def test_no_axis_crossing_same_direction():
    shots = [_shot("s1", camera_angle="左侧"), _shot("s2", camera_angle="左侧")]
    assert check_axis_crossing(shots) == []


def test_axis_crossing_detected():
    shots = [_shot("s1", camera_angle="左侧"), _shot("s2", camera_angle="右侧")]
    issues = check_axis_crossing(shots)
    assert len(issues) == 1
    assert "越轴" in issues[0]


def test_front_back_not_crossing():
    # 正面→背面是机位选择,不判越轴
    shots = [_shot("s1", camera_angle="正面"), _shot("s2", camera_angle="背后")]
    assert check_axis_crossing(shots) == []


def test_cross_scene_not_flagged():
    shots = [
        _shot("s1", scene_no=1, camera_angle="左侧"),
        _shot("s2", scene_no=2, camera_angle="右侧"),
    ]
    assert check_axis_crossing(shots) == []


def test_unknown_direction_skipped():
    shots = [_shot("s1", camera_angle=""), _shot("s2", camera_angle="右侧")]
    assert check_axis_crossing(shots) == []


# ---- One-Move Rule ----

def test_one_move_rule_ok():
    # 3 拍 = 一条完整动作弧(trigger/peak/aftermath),不违规
    shots = [_shot("s1", action_beats=["起", "承", "落"])]
    assert check_one_move_rule(shots) == []


def test_one_move_rule_multi_action():
    shots = [_shot("s1", action_beats=["a", "b", "c", "d"])]
    issues = check_one_move_rule(shots)
    assert len(issues) == 1
    assert "一镜一动作" in issues[0]


# ---- 机位字段完备 ----

def test_character_shot_requires_camera_angle():
    shots = [_shot("s1", camera_angle="", characters=["A"])]
    issues = check_camera_field_completeness(shots)
    assert len(issues) == 1
    assert "缺机位角度" in issues[0]
    # 旁白/空镜不要求
    assert check_camera_field_completeness([_shot("s2", camera_angle="")]) == []


# ---- 聚合 ----

def test_full_continuity_report():
    shots = [
        _shot("s1", camera_angle="左侧", characters=["A"], action_beats=["a", "b", "c"]),
        _shot("s2", camera_angle="右侧", characters=["A"]),
        _shot("s3", camera_angle="正面", characters=["A"]),
    ]
    report = check_camera_continuity(shots)
    assert isinstance(report, CameraContinuityReport)
    assert not report.passed  # s1→s2 越轴
    assert any("越轴" in i for i in report.issues)
    assert report.per_shot_direction["s1"] == "left"
    assert report.per_shot_direction["s2"] == "right"
    assert report.per_shot_direction["s3"] == "front"


def test_clean_continuity_passes():
    shots = [
        _shot("s1", camera_angle="正面", characters=["A"]),
        _shot("s2", camera_angle="正面", characters=["A"]),
    ]
    assert check_camera_continuity(shots).passed
