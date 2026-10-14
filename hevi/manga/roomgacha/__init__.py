"""M2 房间背景抽卡 (roomgacha) — package exports."""

from .spec import RoomSpec, SCENE_KINDS, generate_primitives
from .render import render_room

__all__ = [
    "RoomSpec",
    "SCENE_KINDS",
    "generate_primitives",
    "render_room",
]
