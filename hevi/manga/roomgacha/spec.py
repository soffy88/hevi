"""M2 房间背景抽卡 (roomgacha) — spec + generator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..common import PRNG

SCENE_KINDS = ("classroom", "own_room", "living_room")


@dataclass
class RoomSpec:
    kind: str = "classroom"
    seed: str = "room"
    messiness: float = 0.3          # 凌乱度 0..1
    life: float = 0.5               # 生活感 0..1
    light_azimuth: float = 45.0     # degrees; light direction
    light_elevation: float = 45.0   # degrees
    long_edge: int = 2400          # export PNG long edge (2400 or 3600)
    solid_color: bool = False      # 可选固有色 (else toon tone shading)
    wall_color: tuple[float, float, float] = (0.92, 0.90, 0.86)
    floor_color: tuple[float, float, float] = (0.80, 0.74, 0.64)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "seed": self.seed,
            "messiness": self.messiness,
            "life": self.life,
            "light_azimuth": self.light_azimuth,
            "light_elevation": self.light_elevation,
            "long_edge": self.long_edge,
            "solid_color": self.solid_color,
            "wall_color": list(self.wall_color),
            "floor_color": list(self.floor_color),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RoomSpec":
        return cls(
            kind=d.get("kind", "classroom"),
            seed=d.get("seed", "room"),
            messiness=float(d.get("messiness", 0.3)),
            life=float(d.get("life", 0.5)),
            light_azimuth=float(d.get("light_azimuth", 45.0)),
            light_elevation=float(d.get("light_elevation", 45.0)),
            long_edge=int(d.get("long_edge", 2400)),
            solid_color=bool(d.get("solid_color", False)),
            wall_color=tuple(d.get("wall_color", (0.92, 0.90, 0.86))),  # type: ignore
            floor_color=tuple(d.get("floor_color", (0.80, 0.74, 0.64))),  # type: ignore
        )


def _part(kind: str, pos, size=None, radius=None, height=None, rotY=0.0,
          color=(0.6, 0.6, 0.6), role="") -> dict[str, Any]:
    p: dict[str, Any] = {
        "kind": kind,
        "pos": [round(float(v), 4) for v in pos],
        "rotY": round(float(rotY), 4),
        "color": [round(float(v), 4) for v in color],
        "role": role,
    }
    if kind == "box":
        p["size"] = [round(float(v), 4) for v in size]
    else:
        p["radius"] = round(float(radius), 4)
        p["height"] = round(float(height), 4)
    return p


def build_desk(rng: PRNG, x: float, z: float, color=(0.55, 0.38, 0.24),
               messiness: float = 0.3, life: float = 0.5) -> list[dict]:
    parts = []
    parts.append(_part("box", [x, 0.74, z], [1.2, 0.06, 0.6], color=color, role="desk_top"))
    for dx, dz in [(-0.55, -0.25), (0.55, -0.25), (-0.55, 0.25), (0.55, 0.25)]:
        parts.append(_part("box", [x + dx, 0.37, z + dz], [0.06, 0.74, 0.06],
                           color=(color[0] * 0.8, color[1] * 0.8, color[2] * 0.8), role="desk_leg"))
    if rng.next() < messiness:
        parts.append(_part("box", [x + rng.range(-0.3, 0.3), 0.80, z], [0.2, 0.04, 0.14],
                           color=(0.8, 0.3, 0.3), role="item"))
    if rng.next() < life:
        parts.append(_part("cyl", [x - 0.3, 0.78, z + 0.1], radius=0.05, height=0.08,
                           color=(0.2, 0.5, 0.8), role="mug"))
    return parts


def build_chair(rng: PRNG, x: float, z: float, color=(0.4, 0.4, 0.45)) -> list[dict]:
    parts = []
    parts.append(_part("box", [x, 0.46, z], [0.42, 0.06, 0.42], color=color, role="chair_seat"))
    parts.append(_part("box", [x, 0.66, z - 0.2], [0.42, 0.4, 0.06], color=color, role="chair_back"))
    for dx, dz in [(-0.16, -0.16), (0.16, -0.16), (-0.16, 0.16), (0.16, 0.16)]:
        parts.append(_part("box", [x + dx, 0.21, z + dz], [0.05, 0.42, 0.05],
                           color=(color[0] * 0.8, color[1] * 0.8, color[2] * 0.8), role="chair_leg"))
    return parts


def build_bed(rng: PRNG, x: float, z: float, color=(0.8, 0.85, 0.9)) -> list[dict]:
    parts = []
    parts.append(_part("box", [x, 0.25, z], [2.0, 0.3, 1.4], color=(0.6, 0.5, 0.4), role="bed_frame"))
    parts.append(_part("box", [x, 0.5, z + 0.1], [1.8, 0.18, 1.2], color=color, role="mattress"))
    parts.append(_part("box", [x - 0.7, 0.62, z + 0.1], [0.5, 0.2, 1.2], color=(0.95, 0.95, 0.95), role="pillow"))
    parts.append(_part("box", [x + 0.2, 0.6, z + 0.1], [1.0, 0.12, 1.2], color=(0.7, 0.8, 0.9), role="blanket"))
    return parts


def build_cabinet(rng: PRNG, x: float, z: float, w=0.9, h=1.8, d=0.5,
                  color=(0.5, 0.35, 0.25)) -> list[dict]:
    parts = [_part("box", [x, h / 2, z], [w, h, d], color=color, role="cabinet_body")]
    parts.append(_part("box", [x - w / 4, h * 0.55, z + d / 2 + 0.02], [0.04, 0.18, 0.04],
                       color=(0.2, 0.2, 0.2), role="handle"))
    parts.append(_part("box", [x + w / 4, h * 0.55, z + d / 2 + 0.02], [0.04, 0.18, 0.04],
                       color=(0.2, 0.2, 0.2), role="handle"))
    return parts


def build_bookshelf(rng: PRNG, x: float, z: float, color=(0.45, 0.3, 0.2)) -> list[dict]:
    parts = []
    W, H, D = 1.0, 1.8, 0.3
    parts.append(_part("box", [x, H / 2, z], [W, H, D], color=color, role="shelf_body"))
    book_colors = [(0.8, 0.3, 0.3), (0.3, 0.6, 0.4), (0.3, 0.4, 0.8), (0.9, 0.8, 0.3)]
    for sh in range(1, 4):
        y = H * sh / 4
        bx = x - W / 2 + 0.1
        while bx < x + W / 2 - 0.1:
            bw = rng.range(0.05, 0.1)
            if bx + bw > x + W / 2 - 0.1:
                break
            bc = book_colors[rng.int(0, len(book_colors) - 1)]
            parts.append(_part("box", [bx + bw / 2, y + 0.12, z], [bw, 0.24, D * 0.8],
                               color=bc, role="book"))
            bx += bw + 0.01
    return parts


def build_sofa(rng: PRNG, x: float, z: float, color=(0.7, 0.55, 0.5)) -> list[dict]:
    parts = []
    parts.append(_part("box", [x, 0.3, z], [2.0, 0.3, 0.9], color=color, role="sofa_base"))
    parts.append(_part("box", [x, 0.55, z - 0.38], [2.0, 0.5, 0.15], color=color, role="sofa_back"))
    parts.append(_part("box", [x - 0.9, 0.45, z], [0.15, 0.4, 0.9], color=color, role="sofa_arm"))
    parts.append(_part("box", [x + 0.9, 0.45, z], [0.15, 0.4, 0.9], color=color, role="sofa_arm"))
    parts.append(_part("box", [x, 0.5, z], [1.6, 0.12, 0.7], color=(color[0] * 1.1, color[1] * 1.1, color[2] * 1.1), role="cushion"))
    return parts


def build_podium(rng: PRNG, x: float, z: float, color=(0.6, 0.45, 0.3)) -> list[dict]:
    return [
        _part("box", [x, 0.6, z], [1.0, 1.2, 0.7], color=color, role="podium_body"),
        _part("box", [x, 1.27, z - 0.1], [0.7, 0.12, 0.4], color=(color[0]*1.1, color[1]*1.1, color[2]*1.1), role="podium_top"),
    ]


def build_desk_array(rng: PRNG, x0: float, z0: float, cols: int, rows: int,
                     spacing_x: float, spacing_z: float, messiness: float,
                     life: float) -> list[dict]:
    parts: list[dict] = []
    for r in range(rows):
        for c in range(cols):
            x = x0 + c * spacing_x
            z = z0 + r * spacing_z
            parts += build_desk(rng, x, z, color=(0.55, 0.38, 0.24), messiness=messiness, life=life)
            parts += build_chair(rng, x, z + 0.45, color=(0.4, 0.4, 0.45))
    return parts


def build_floor_grid(spec: RoomSpec, rng: PRNG) -> tuple[list[dict], dict]:
    size = 12.0
    cells = 12
    tile = size / cells
    tiles: list[dict] = []
    for i in range(cells):
        for j in range(cells):
            cx = -size / 2 + (i + 0.5) * tile
            cz = -size / 2 + (j + 0.5) * tile
            aisle = (i == cells // 2 or j == cells // 2)
            height = 0.0
            if spec.kind == "classroom" and j < 2:
                height = 0.15
            tag = "aisle" if aisle else "region"
            col = spec.floor_color
            if tag == "aisle":
                col = (min(1, spec.floor_color[0] * 0.9),) * 3
            tiles.append({
                "pos": [round(cx, 3), round(height, 3), round(cz, 3)],
                "size": [round(tile, 3), 0.1, round(tile, 3)],
                "tag": tag, "height": height,
                "color": [round(c, 4) for c in col],
            })
    meta = {"size": size, "cells": cells, "tile": tile}
    return tiles, meta


def generate_primitives(spec: RoomSpec) -> dict[str, Any]:
    rng = PRNG(spec.seed)
    floor, meta = build_floor_grid(spec, rng)
    furniture: list[dict] = []
    kind = spec.kind
    if kind == "classroom":
        furniture += build_podium(rng, 0, -4.5)
        furniture += build_desk_array(rng, -4.0, -1.5, 4, 3, 2.0, 1.6,
                                      spec.messiness, spec.life)
        furniture.append(_part("box", [0, 1.6, -5.8], [4.0, 1.2, 0.1],
                               color=(0.15, 0.2, 0.18), role="blackboard"))
    elif kind == "own_room":
        furniture += build_bed(rng, -3.5, -3.0)
        furniture += build_desk(rng, 3.0, -3.5, messiness=spec.messiness, life=spec.life)
        furniture += build_cabinet(rng, 4.0, 2.0, w=1.2, h=2.0, d=0.6)
        furniture += build_bookshelf(rng, -4.2, 2.5)
        if rng.next() < spec.life:
            furniture.append(_part("cyl", [0, 0.2, 1.5], radius=0.25, height=0.4, color=(0.3, 0.5, 0.7), role="rug"))
    elif kind == "living_room":
        furniture += build_sofa(rng, 0, 3.0)
        furniture += build_cabinet(rng, -4.0, -3.5, w=2.0, h=0.6, d=0.5)
        furniture.append(_part("box", [0, 0.25, -1.0], [1.4, 0.4, 0.8], color=(0.5, 0.4, 0.3), role="coffee_table"))
        furniture += build_bookshelf(rng, 4.2, 1.0)
        if rng.next() < spec.life:
            furniture.append(_part("cyl", [0, 0.02, 0], radius=1.2, height=0.04, color=(0.5, 0.45, 0.4), role="rug"))
    else:
        raise ValueError(f"unknown room kind {kind!r}")

    if spec.messiness > 0.4:
        n = int(spec.messiness * 8)
        for _ in range(n):
            x = rng.range(-4, 4)
            z = rng.range(-4, 4)
            furniture.append(_part("box", [x, 0.06, z], [0.15, 0.05, 0.1],
                                   color=(rng.range(0.4, 0.9),) * 3, role="clutter"))

    return {
        "spec": spec.to_dict(),
        "meta": meta,
        "floor": floor,
        "furniture": furniture,
        "walls": _walls(spec),
    }


def _walls(spec: RoomSpec) -> dict:
    size = 12.0
    half = size / 2
    return {
        "size": size,
        "half": half,
        "height": 3.2,
        "windows": [
            {"wall": "back", "x": -3.0, "y": 1.8, "w": 1.6, "h": 1.2},
            {"wall": "back", "x": 3.0, "y": 1.8, "w": 1.6, "h": 1.2},
            {"wall": "left", "z": 0.0, "y": 1.8, "w": 1.6, "h": 1.2},
        ],
        "door": {"wall": "right", "z": 0.0, "y": 1.1, "w": 1.0, "h": 2.2},
    }
