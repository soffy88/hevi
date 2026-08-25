"""语义动效计划 —— 内化 agent-video-pipeline motion-system。

每个语义节点一个 hero motion;build→breathe→resolve;时间绑韵律轨。
静止是资源,不是空档。deterministic / seek-safe。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any

from hevi.production.craft_profile import CraftProfile
from hevi.production.prosody import ProsodyTrack

SEMANTIC_ROLES: tuple[str, ...] = (
    "hook",
    "definition",
    "process",
    "comparison",
    "metric",
    "warning",
    "demo",
    "hierarchy",
    "example",
    "conclusion",
    "cta",
    "statement",
)

HERO_BY_ROLE: dict[str, str] = {
    "hook": "keyword_lock",
    "definition": "term_then_expand",
    "process": "path_draw",
    "comparison": "split_mirror",
    "metric": "value_morph",
    "warning": "border_tighten",
    "demo": "device_window",
    "hierarchy": "hub_grow",
    "example": "card_stagger",
    "conclusion": "converge_claim",
    "cta": "card_arrow_once",
    "statement": "fade_slide",
}

_ROLE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("hook", ("为什么", "竟然", "没人", "悬念", "突然")),
    ("definition", ("所谓", "是指", "定义", "本质", "公式")),
    ("process", ("首先", "然后", "接着", "步骤", "流程")),
    ("comparison", ("对比", "一边", "另一", "vs", "而不是")),
    ("metric", ("%", "倍", "万", "数据", "增长")),
    ("warning", ("危险", "禁止", "风险", "注意", "不要")),
    ("demo", ("代码", "点击", "界面", "演示")),
    ("conclusion", ("因此", "所以", "结论", "总之")),
    ("cta", ("关注", "点赞", "订阅", "点击")),
)


@dataclass
class MotionBeat:
    id: str
    semantic_anchor: str
    cue_s: float
    primitive: str
    priority: str = "hero"
    seek_safe: bool = True


@dataclass
class MotionScene:
    id: str
    start_s: float
    end_s: float
    semantic_role: str
    hero_motion: str
    supporting_motions: list[str]
    layout_variant: str
    beats: list[MotionBeat]
    transition_in: str
    selection_reason: str = ""


@dataclass
class MotionPlan:
    scenes: list[MotionScene]
    profile_sha256: str
    seed: str
    clock: str = "prosody"
    preset: str = "basic-stable"
    degradations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": 1,
            "status": "draft",
            "profile_sha256": self.profile_sha256,
            "seed": self.seed,
            "clock": self.clock,
            "preset": self.preset,
            "degradations": list(self.degradations),
            "scenes": [
                {
                    **{key: value for key, value in asdict(scene).items() if key != "beats"},
                    "beats": [asdict(beat) for beat in scene.beats],
                }
                for scene in self.scenes
            ],
        }
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        payload["sha256"] = hashlib.sha256(blob.encode("utf-8")).hexdigest()
        return payload


def infer_semantic_role(text: str, *, index: int = 0, total: int = 1) -> str:
    body = text or ""
    if index == 0:
        return "hook"
    if total > 1 and index == total - 1:
        return "conclusion"
    for role, hints in _ROLE_HINTS:
        if any(hint in body for hint in hints):
            return role
    return "statement"


def _layout_for(role: str, preset: str) -> str:
    if preset == "cinematic":
        return "cinematic-wide"
    return {
        "hook": "asymmetric-title",
        "definition": "term-media",
        "process": "center-path",
        "comparison": "protected-split",
        "metric": "big-number",
        "warning": "alert-rail",
        "conclusion": "converge",
        "cta": "cta-away-avatar",
    }.get(role, "statement-card")


def plan_semantic_motion(
    texts: list[str],
    track: ProsodyTrack,
    profile: CraftProfile,
    *,
    seed: str = "hevi",
) -> MotionPlan:
    """旁白 + 韵律 + Profile → 声明式动效计划。每场恰好一个 hero。"""
    scenes: list[MotionScene] = []
    families = profile.transition_families or ["crossfade"]
    last_hero = ""
    for index, text in enumerate(texts):
        role = infer_semantic_role(text, index=index, total=len(texts))
        hero = HERO_BY_ROLE[role]
        if hero == last_hero and role == "statement":
            hero = "card_stagger"
        last_hero = hero
        related = [beat for beat in track.beats if beat.cue_index == index]
        start = related[0].start_s if related else 0.0
        end = related[-1].end_s if related else start + 4.0
        support: list[str] = []
        if profile.motion_preset in {"premium-balanced", "cinematic"}:
            support = ["focus_underline"]
        if profile.motion_preset == "basic-stable" and hero not in {
            "fade_slide",
            "term_then_expand",
            "card_stagger",
            "converge_claim",
        }:
            # 批量默认档压到低成本 primitive
            hero = "fade_slide"
        motion_beats = [
            MotionBeat(
                id=f"{index + 1}-{beat.sentence_id}",
                semantic_anchor=beat.emphasis[0] if beat.emphasis else beat.text[:12],
                cue_s=beat.start_s,
                primitive=hero if offset == 0 else "fade_in",
                priority="hero" if offset == 0 else "support",
            )
            for offset, beat in enumerate(related or [None])
            if beat is not None
        ]
        if not motion_beats:
            motion_beats = [
                MotionBeat(
                    id=f"{index + 1}-solo",
                    semantic_anchor=text[:12],
                    cue_s=start,
                    primitive=hero,
                )
            ]
        scenes.append(
            MotionScene(
                id=f"scene-{index + 1:02d}",
                start_s=start,
                end_s=end,
                semantic_role=role,
                hero_motion=hero,
                supporting_motions=support[:1],
                layout_variant=_layout_for(role, profile.motion_preset),
                beats=motion_beats,
                transition_in=families[index % len(families)],
                selection_reason=f"role={role}",
            )
        )
    return MotionPlan(
        scenes=scenes,
        profile_sha256=profile.sha256(),
        seed=seed,
        preset=profile.motion_preset,
    )
