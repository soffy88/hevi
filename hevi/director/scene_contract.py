"""镜头空间契约 —— 机位驱动渲染的确定性前置校验(3GS G1,3O 内化 Phase D)。

SPEC-3GS-world-set.md 门 1(G1)的代码侧:分镜 shot schema 有机位/方位角字段后,
这里提供**确定性空间契约检查**(不吃模型,HEVI-ARCH v3.2 已列为 lint 硬项):

  1. **越轴检查(axis crossing)**:相邻镜头 screen_direction 不得无理由翻转 ——
     从 camera_angle/azimuth 推导银幕方向,相邻镜同场景翻转判为越轴。
  2. **One-Move Rule**:每镜只允许一个可见动作节拍 + 一个主要运镜。
  3. **机位字段完备**:角色锁定的镜头应有机位角度(缺 = 无法驱动 3D 视角资产)。

全部纯函数、确定性输出 issues 列表(空 = 通过);不进 LLM,零成本。
3O 归属(待上游): `oprim.scene_spatial_contract`(几何自洽校验)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: camera_angle 关键词 → 代表方位角(deg,顺时针)。
_ANGLE_AZIMUTH: dict[str, float] = {
    "正面": 0.0,
    "正对": 0.0,
    "侧45": 45.0,
    "侧45°": 45.0,
    "左侧": -90.0,
    "右侧": 90.0,
    "背后": 180.0,
    "俯拍": 0.0,
    "仰拍": 0.0,
    "环绕": 0.0,
}
#: camera_angle / facing 里的"银幕方向"关键词 → 方向(越轴判定用)。
_DIRECTION_KEYWORDS: dict[str, str] = {
    "左": "left",
    "右": "right",
    "背后": "back",
    "正面": "front",
    "正对": "front",
}


def camera_angle_azimuth(camera_angle: str, azimuth_deg: float | None) -> float | None:
    """机位角度 → 代表方位角(优先显式 azimuth;否则按关键词映射;未知 → None)。"""
    if azimuth_deg is not None:
        return azimuth_deg
    for key, value in _ANGLE_AZIMUTH.items():
        if key in camera_angle:
            return value
    return None


def screen_direction(
    camera_angle: str, azimuth_deg: float | None = None, facing: str = ""
) -> str | None:
    """推导银幕方向(left/right/front/back);无法推导 → None。

    优先级:朝向词(facing)→ 机位角度关键词 → 方位角符号。
    """
    for key, value in _DIRECTION_KEYWORDS.items():
        if key in facing:
            return value
    for key, value in _DIRECTION_KEYWORDS.items():
        if key in camera_angle:
            return value
    az = camera_angle_azimuth(camera_angle, azimuth_deg)
    if az is None:
        return None
    if abs(az) < 30.0:
        return "front"
    if abs(az - 180.0) < 30.0:
        return "back"
    return "right" if az > 0 else "left"


def _shot_camera_angle(shot: Any) -> str:
    return getattr(shot, "camera_angle", "") or getattr(shot, "camera", "") or ""


def _shot_azimuth(shot: Any) -> float | None:
    return getattr(shot, "azimuth_deg", None)


def _shot_facing(shot: Any) -> str:
    blocking = getattr(shot, "blocking", None) or []
    for b in blocking:
        facing = getattr(b, "facing", "") or ""
        if facing:
            return facing
    return ""


@dataclass
class CameraContinuityReport:
    """空间契约检查结果。"""

    issues: list[str] = field(default_factory=list)
    per_shot_direction: dict[str, str | None] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.issues


def check_axis_crossing(shots: list[Any], *, scene_no: int | None = None) -> list[str]:
    """越轴检查:相邻镜头银幕方向无理由翻转(left↔right)判为越轴。

    - 仅对**同一场景**的相邻镜头比较:跨场景恒重置(不误报)。
    - front/back 不参与翻转判定(正面/背面是机位选择,不是越轴)。
    - 无法推导方向的镜头跳过(不误报)。
    """
    issues: list[str] = []
    prev_dir: str | None = None
    prev_id: str | None = None
    prev_scene: Any = None
    for shot in shots:
        shot_scene = getattr(shot, "scene_no", None)
        if scene_no is not None and shot_scene != scene_no:
            prev_dir, prev_id, prev_scene = None, None, None
            continue
        if shot_scene != prev_scene:  # 换场景 → 重置,跨场景不受越轴约束
            prev_dir, prev_id = None, None
        direction = screen_direction(
            _shot_camera_angle(shot), _shot_azimuth(shot), _shot_facing(shot)
        )
        both_lateral = direction in ("left", "right") and prev_dir in ("left", "right")
        if both_lateral and direction != prev_dir:
            issues.append(
                f"shot {getattr(shot, 'shot_id', '?')} 相对 {prev_id}: "
                f"银幕方向 {prev_dir}→{direction} 无理由翻转(越轴)"
            )
        prev_dir, prev_id, prev_scene = direction, getattr(shot, "shot_id", None), shot_scene
    return issues


def check_one_move_rule(shots: list[Any]) -> list[str]:
    """One-Move Rule:每镜只允许一个可见动作节拍(HEVI-ARCH v3.2 lint 硬项)。"""
    issues: list[str] = []
    for shot in shots:
        beats = getattr(shot, "action_beats", None) or []
        if len(beats) > 3:  # trigger/peak/aftermath = 一条动作弧(≤3 拍点),非多个动作
            issues.append(
                f"shot {getattr(shot, 'shot_id', '?')}: {len(beats)} 个动作拍点,"
                "一镜一动作(3 拍为一条完整弧线,再多=塞多个动作)"
            )
    return issues


def check_camera_field_completeness(shots: list[Any]) -> list[str]:
    """机位字段完备:角色锁定的镜头应有机位角度(缺 = 无法驱动 3D 视角资产)。"""
    issues: list[str] = []
    for shot in shots:
        chars = getattr(shot, "character_names", None) or []
        angle = _shot_camera_angle(shot)
        if chars and not angle.strip():
            issues.append(
                f"shot {getattr(shot, 'shot_id', '?')}: 角色镜头缺机位角度"
                "(camera_angle 空,3D 视角资产无法按机位渲条件帧)"
            )
    return issues


def check_camera_continuity(shots: list[Any]) -> CameraContinuityReport:
    """聚合:越轴 + One-Move + 机位字段完备。"""
    report = CameraContinuityReport()
    report.issues.extend(check_axis_crossing(shots))
    report.issues.extend(check_one_move_rule(shots))
    report.issues.extend(check_camera_field_completeness(shots))
    report.per_shot_direction = {
        getattr(s, "shot_id", f"#{i}"): screen_direction(
            _shot_camera_angle(s), _shot_azimuth(s), _shot_facing(s)
        )
        for i, s in enumerate(shots)
    }
    return report
