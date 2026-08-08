"""hevi.director.scene_world — Director World 场景一致性(3GS 轻量版)。

对标 DramaClaw Director World / 3GS(场景变体):锁定空间结构、角色走位、
机位,让同一场景跨镜头保持一致——hevi 侧以**场景状态(scene_state)**实现:
同一场景的所有镜头共享空间布局/机位/光照约束(生成时注入 prompt 前缀),
并在镜头清单产出后做确定性一致性 gate。

纯机制(不依赖 LLM/生成服务),装配层注入 shot_list 生成。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hevi.director.pipeline_schemas import ShotListItem


@dataclass
class SceneState:
    """场景状态:跨镜头锁定的空间/机位/光照/走位约束。"""

    scene_name: str
    layout: str = ""  # 空间布局,如"客厅:沙发居左,落地窗居右,茶几居中"
    lighting: str = ""  # 光照,如"冷调夜景,窗外月光"
    camera_defaults: str = ""  # 默认机位/摄法,如"平视中景为主,少用仰角"
    blocking_template: str = ""  # 走位模板,如"主角近窗,对手戏时对称站位"

    def to_lock_prompt(self) -> str:
        """场景锁定前缀:注入镜头视觉 prompt,保证同场景跨镜头一致。"""
        parts = [f"[场景锁定:{self.scene_name}"]
        if self.layout:
            parts.append(f"空间:{self.layout}")
        if self.lighting:
            parts.append(f"光照:{self.lighting}")
        if self.camera_defaults:
            parts.append(f"机位:{self.camera_defaults}")
        if self.blocking_template:
            parts.append(f"走位:{self.blocking_template}")
        return " | ".join(parts) + "]"


class SceneWorld:
    """场景世界:注册场景状态 + 锁定 prompt + 一致性 gate。"""

    def __init__(self) -> None:
        self._scenes: dict[str, SceneState] = {}

    def register(self, state: SceneState) -> SceneState:
        self._scenes[state.scene_name] = state
        return state

    def get(self, scene_name: str) -> SceneState | None:
        return self._scenes.get(scene_name)

    def lock_prompt_for(self, scene_name: str) -> str:
        state = self._scenes.get(scene_name)
        return state.to_lock_prompt() if state else ""


# ── 一致性 gate:确定性检查,不调 LLM ──────────────────────────────
def check_scene_consistency(
    shots: list[ShotListItem],
    scene_world: SceneWorld | None = None,
) -> dict[str, Any]:
    """按 scene_name 分组,检查同场景镜头间的空间一致性:

    1. 镜头覆盖:同场景 ≥2 镜时每镜须有机位(camera)与视觉 prompt
       (visual_prompt 为空 = 无法判定空间,记 warning)
    2. 场景锁定:若 SceneWorld 注册了该场景,镜头 visual_prompt 须含
       场景锁定前缀(缺失 = 该镜未受场景约束)
    3. 走位冲突:同一角色在同一镜内的 blocking 位置互相矛盾 → conflict

    返回: {scene_name: {shot_count, camera_coverage, lock_missing,
                        conflicts: [str]}}
    """
    by_scene: dict[str, list[ShotListItem]] = {}
    for shot in shots:
        by_scene.setdefault(shot.scene_name or "(未定)", []).append(shot)

    report: dict[str, Any] = {}
    for scene_name, scene_shots in by_scene.items():
        lock_prefix = ""
        if scene_world is not None:
            lock_prefix = scene_world.lock_prompt_for(scene_name)
        conflicts: list[str] = []
        lock_missing = 0
        camera_coverage = 0
        for shot in scene_shots:
            if shot.camera:
                camera_coverage += 1
            if lock_prefix and lock_prefix.split("]")[0] not in (
                shot.visual_prompt or ""
            ):
                lock_missing += 1
            # 同镜内同一角色位置冲突
            seen: dict[str, str] = {}
            for b in shot.blocking:
                if not b.position:
                    continue
                if b.character_name in seen and seen[b.character_name] != b.position:
                    conflicts.append(
                        f"{shot.shot_id} 角色 {b.character_name} 走位矛盾 "
                        f"({seen[b.character_name]} vs {b.position})")
                seen[b.character_name] = b.position
        report[scene_name] = {
            "shot_count": len(scene_shots),
            "camera_coverage": camera_coverage,
            "lock_missing": lock_missing,
            "conflicts": conflicts,
        }
    return report


def consistency_passed(report: dict[str, Any]) -> bool:
    """gate 判定:所有场景无走位冲突(lock_missing 记 warning 不阻断)。"""
    if not report:
        return True
    return all(not v["conflicts"] for v in report.values())
