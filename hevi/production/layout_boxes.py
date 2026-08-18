"""布局盒 + 遮挡闸 —— 内化 agent-video-pipeline layout-box-schema。

画布和 protected zones 只来自冻结 Profile。动画元素验 swept bbox,
protected 同时相交且没有 composite id → 失败。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hevi.production.craft_profile import CraftProfile
from hevi.production.semantic_motion import MotionPlan


@dataclass
class LayoutElement:
    id: str
    role: str
    x: float
    y: float
    width: float
    height: float
    protected: bool
    start_s: float
    end_s: float
    z_index: int
    composite_id: str | None = None

    def box(self) -> tuple[float, float, float, float]:
        return (self.x, self.y, self.x + self.width, self.y + self.height)


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _px(profile: CraftProfile, box: dict[str, float]) -> tuple[int, int, int, int]:
    return (
        int(profile.width * float(box["x"])),
        int(profile.height * float(box["y"])),
        int(profile.width * float(box["w"])),
        int(profile.height * float(box["h"])),
    )


def init_layout_boxes(profile: CraftProfile, plan: MotionPlan) -> dict[str, Any]:
    scenes: list[dict[str, Any]] = []
    for scene in plan.scenes:
        title = _px(profile, profile.title_box)
        caption = _px(profile, profile.caption_box)
        art = _px(profile, profile.illustration_box)
        elements = [
            LayoutElement("title", "title", *title, True, scene.start_s, scene.end_s, 30),
            LayoutElement("content", "content", *art, True, scene.start_s, scene.end_s, 20),
            LayoutElement("caption", "caption", *caption, True, scene.start_s, scene.end_s, 40),
        ]
        if profile.avatar_enabled:
            avatar = _px(profile, profile.avatar_box)
            elements.append(
                LayoutElement("avatar", "avatar", *avatar, True, scene.start_s, scene.end_s, 35)
            )
        scenes.append(
            {
                "id": scene.id,
                "start_s": scene.start_s,
                "end_s": scene.end_s,
                "layout_variant": scene.layout_variant,
                "elements": [
                    {
                        "id": item.id,
                        "role": item.role,
                        "shape": "rect",
                        "x": item.x,
                        "y": item.y,
                        "width": item.width,
                        "height": item.height,
                        "swept_bbox": {
                            "x": item.x,
                            "y": item.y,
                            "width": item.width,
                            "height": item.height,
                        },
                        "start_s": item.start_s,
                        "end_s": item.end_s,
                        "protected": item.protected,
                        "z_index": item.z_index,
                        "intentional_composite_id": item.composite_id,
                    }
                    for item in elements
                ],
            }
        )
    return {
        "schema_version": 1,
        "status": "draft",
        "canvas": {"width": profile.width, "height": profile.height},
        "profile_sha256": profile.sha256(),
        "motion_plan_sha": plan.to_dict().get("sha256"),
        "scenes": scenes,
    }


def check_occlusion(layout: dict[str, Any]) -> list[str]:
    """protected 同时相交且无合法 composite id → 错误。"""
    errors: list[str] = []
    for scene in layout.get("scenes") or []:
        items = [
            item
            for item in (scene.get("elements") or [])
            if item.get("protected") and item.get("role") != "background"
        ]
        for index, left in enumerate(items):
            left_box = (
                float(left["x"]),
                float(left["y"]),
                float(left["x"]) + float(left["width"]),
                float(left["y"]) + float(left["height"]),
            )
            left_span = (float(left.get("start_s") or 0), float(left.get("end_s") or 0))
            for right in items[index + 1 :]:
                if left.get("intentional_composite_id") and (
                    left.get("intentional_composite_id") == right.get("intentional_composite_id")
                ):
                    continue
                right_box = (
                    float(right["x"]),
                    float(right["y"]),
                    float(right["x"]) + float(right["width"]),
                    float(right["y"]) + float(right["height"]),
                )
                right_span = (float(right.get("start_s") or 0), float(right.get("end_s") or 0))
                time_hit = left_span[0] < right_span[1] and right_span[0] < left_span[1]
                if time_hit and _overlap(left_box, right_box):
                    errors.append(
                        f"{scene.get('id')}: {left.get('id')} 与 {right.get('id')} 保护区相交"
                    )
    return errors
