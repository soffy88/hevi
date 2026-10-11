"""Clean-room CMU motion-capture loader for the SVG character renderer.

The Hevi character-animation line needs real human motion driving an SVG
skeleton.  This module fetches BVH trials from the **CMU Graphics Lab Motion
Capture Database** (free for all uses, research and commercial) through the
``una-dinosauria/cmu-mocap`` mirror, parses them with our own forward-kinematics
code, and projects each frame to a flat 2-D joint set the renderer consumes.

Nothing here is derived from OpenMontage; the BVH format is the published
standard and the joint names are CMU's own.

Public API
----------
``load_clip(name)``      -> cached 2-D clip dict (downloads + converts once)
``available()``          -> the bundled trial table
``convert(name)``        -> parse → project → normalise, returns the clip dict
"""

from __future__ import annotations

import json
import math
import os
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

CMU_RAW = "https://raw.githubusercontent.com/una-dinosauria/cmu-mocap/master/data"
GHFAST = "https://ghfast.top/"

#: clip name -> (subject folder, trial, projection plane, spoken label)
TRIALS: dict[str, tuple[str, str, str, str]] = {
    "walk": ("002", "02_01", "zy", "它走起来了"),
    "run": ("009", "09_01", "zy", "它跑了起来"),
    "march": ("015", "15_01", "zy", "它原地踏步"),
    "shuffle": ("077", "77_29", "zy", "它悄悄挪动"),
    "sit": ("013", "13_01", "zy", "它坐了下来"),
    "jump": ("013", "13_11", "xy", "它跳了一下"),
    "kick": ("010", "10_01", "xy", "它踢了一脚"),
    "wave": ("141", "141_16", "xy", "它挥手打招呼"),
    "dance_spin": ("005", "05_02", "xy", "它转了个圈"),
    "dance_glide": ("005", "05_10", "xy", "它跳起舞来"),
    "twist": ("141", "141_12", "xy", "它扭动身体"),
}

#: joints we keep, mapped to the CMU names we resolve below
_KEEP = (
    "hips",
    "chest",
    "neck",
    "head",
    "shR",
    "elR",
    "haR",
    "shL",
    "elL",
    "haL",
    "hipR",
    "knR",
    "ftR",
    "hipL",
    "knL",
    "ftL",
)

#: candidate CMU joint names per kept joint (first match wins; ``Spine``/``Neck``
#: appear twice in CMU skeletons so the *upper* occurrence is chosen by rest height)
_ALIASES: dict[str, tuple[str, ...]] = {
    "hips": ("Hips",),
    "chest": ("Spine1", "Spine", "Chest"),
    "neck": ("Neck1", "Neck"),
    "head": ("Head",),
    "shR": ("RightArm", "RightShoulder"),
    "elR": ("RightForeArm",),
    "haR": ("RightHand",),
    "shL": ("LeftArm", "LeftShoulder"),
    "elL": ("LeftForeArm",),
    "haL": ("LeftHand",),
    "hipR": ("RightUpLeg",),
    "knR": ("RightLeg",),
    "ftR": ("RightFoot",),
    "hipL": ("LeftUpLeg",),
    "knL": ("LeftLeg",),
    "ftL": ("LeftFoot",),
}

_DUPLICATE_NAMES = {"Spine", "Neck", "Spine1", "Neck1"}


@dataclass
class _Node:
    name: str
    offset: np.ndarray
    channels: list[str]
    parent: int


def cache_dir() -> Path:
    root = os.environ.get("HEVI_CMU_CACHE") or str(Path.home() / ".cache" / "hevi-cmu-mocap")
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


def clip_cache_dir() -> Path:
    root = Path(__file__).resolve().parents[2] / "assets" / "mocap-clips" / "clips"
    root.mkdir(parents=True, exist_ok=True)
    return root


def available() -> dict[str, dict[str, str]]:
    return {
        name: {"subject": subj, "trial": trial, "plane": plane, "label": label, "source": f"CMU {trial}"}
        for name, (subj, trial, plane, label) in TRIALS.items()
    }


def _download_bvh(subject: str, trial: str) -> Path:
    dest = cache_dir() / f"{trial}.bvh"
    if dest.is_file() and dest.stat().st_size > 1024:
        return dest
    url = f"{CMU_RAW}/{subject}/{trial}.bvh"
    last_error: str | None = None
    for candidate in (GHFAST + url, url):
        proc = subprocess.run(
            ["curl", "-sL", "--fail", "--max-time", "120", candidate, "-o", str(dest)],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and dest.is_file() and dest.stat().st_size > 1024:
            return dest
        last_error = proc.stderr[-300:]
    raise RuntimeError(f"could not download CMU trial {trial}: {last_error}")


# --------------------------------------------------------------------- parser
def _parse_bvh(path: Path) -> tuple[list[_Node], int, list[list[float]], float]:
    text = path.read_text(encoding="utf-8", errors="replace")
    hierarchy, _, motion = text.partition("MOTION")
    tokens = hierarchy.replace("{", " { ").replace("}", " } ").split()
    nodes: list[_Node] = []
    stack: list[int] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in ("ROOT", "JOINT"):
            name = tokens[i + 1]
            parent = stack[-1] if stack else -1
            # skip to the OFFSET / CHANNELS inside this block
            offset = np.zeros(3)
            channels: list[str] = []
            j = i + 2
            while j < len(tokens) and tokens[j] not in ("JOINT", "ROOT", "End", "}"):
                if tokens[j] == "OFFSET":
                    offset = np.array([float(tokens[j + 1]), float(tokens[j + 2]), float(tokens[j + 3])])
                    j += 4
                elif tokens[j] == "CHANNELS":
                    count = int(tokens[j + 1])
                    channels = tokens[j + 2 : j + 2 + count]
                    j += 2 + count
                else:
                    j += 1
            nodes.append(_Node(name=name, offset=offset, channels=channels, parent=parent))
            stack.append(len(nodes) - 1)
            i = j
            continue
        if token == "End":
            # End Site { OFFSET x y z } — skip the whole block
            j = i
            while j < len(tokens) and tokens[j] != "}":
                j += 1
            i = j + 1
            continue
        if token == "}":
            if stack:
                stack.pop()
            i += 1
            continue
        i += 1

    lines = [ln for ln in motion.splitlines() if ln.strip()]
    frame_count = 0
    frame_time = 1.0 / 30.0
    for ln in lines:
        if ln.upper().startswith("FRAMES:"):
            frame_count = int(ln.split(":")[1])
        if ln.upper().startswith("FRAME TIME:"):
            frame_time = float(ln.split(":", 1)[1])
            break
    data_lines = lines[-frame_count:] if frame_count else []
    frames = [[float(x) for x in ln.split()] for ln in data_lines]
    return nodes, frame_count, frames, frame_time


def _rot(axis: str, deg: float) -> np.ndarray:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    if axis == "X":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])
    if axis == "Y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def _forward_kinematics(nodes: list[_Node], frame: list[float]) -> np.ndarray:
    """World positions of every joint for one frame (root translation included)."""
    positions = np.zeros((len(nodes), 3))
    world_rot = [np.eye(3) for _ in nodes]
    cursor = 0
    for idx, node in enumerate(nodes):
        translation = node.offset.copy()
        rotation = np.eye(3)
        for channel in node.channels:
            value = frame[cursor]
            cursor += 1
            kind, axis = channel[0], channel[1]
            if kind == "X" and axis == "p":
                translation = translation + np.array([value, 0, 0])
            elif kind == "Y" and axis == "p":
                translation = translation + np.array([0, value, 0])
            elif kind == "Z" and axis == "p":
                translation = translation + np.array([0, 0, value])
            elif kind == "X" and axis == "r":
                rotation = _rot("X", value) @ rotation
            elif kind == "Y" and axis == "r":
                rotation = _rot("Y", value) @ rotation
            elif kind == "Z" and axis == "r":
                rotation = _rot("Z", value) @ rotation
        parent_pos = positions[node.parent] if node.parent >= 0 else np.zeros(3)
        parent_rot = world_rot[node.parent] if node.parent >= 0 else np.eye(3)
        positions[idx] = parent_pos + parent_rot @ translation
        world_rot[idx] = parent_rot @ rotation
    return positions


def _rest_positions(nodes: list[_Node]) -> np.ndarray:
    return _forward_kinematics(nodes, [0.0] * sum(len(n.channels) for n in nodes))


def _resolve_joints(nodes: list[_Node]) -> dict[str, int]:
    rest = _rest_positions(nodes)
    resolved: dict[str, int] = {}
    for key, aliases in _ALIASES.items():
        candidates = [i for i, n in enumerate(nodes) if n.name in aliases]
        if not candidates:
            raise RuntimeError(f"CMU skeleton has no joint for {key} ({aliases})")
        if len(candidates) > 1:
            # CMU repeats Spine/Neck; keep the upper one (largest rest Y)
            candidates.sort(key=lambda i: float(rest[i][1]))
        resolved[key] = candidates[-1]
    return resolved


def convert(name: str) -> dict[str, Any]:
    """Parse a trial, run FK, project to 2-D and normalise the figure."""
    if name not in TRIALS:
        raise KeyError(f"unknown mocap clip {name!r}; have {sorted(TRIALS)}")
    subject, trial, plane, label = TRIALS[name]
    bvh = _download_bvh(subject, trial)
    nodes, _frame_count, frames, frame_time = _parse_bvh(bvh)
    if not frames:
        raise RuntimeError(f"{trial}: no motion frames parsed")
    joints = _resolve_joints(nodes)

    # CMU is 120 fps; resample every trial to a flat 30 fps timeline.
    src_fps = 1.0 / frame_time if frame_time > 0 else 120.0
    out_fps = 30.0
    duration = (len(frames) - 1) / src_fps
    out_count = max(round(duration * out_fps) + 1, 2)
    sample_times = [i / out_fps for i in range(out_count)]

    # forward kinematics at 30 fps (linear interpolation between source frames)
    tracks: dict[str, list[list[float]]] = {k: [] for k in _KEEP}
    for t in sample_times:
        pos = t * src_fps
        lo = min(int(pos), len(frames) - 1)
        hi = min(lo + 1, len(frames) - 1)
        frac = pos - lo
        frame = [frames[lo][i] * (1 - frac) + frames[hi][i] * frac for i in range(len(frames[lo]))]
        positions = _forward_kinematics(nodes, frame)
        for key, idx in joints.items():
            p = positions[idx]
            if plane == "zy":
                tracks[key].append([float(p[2]), float(p[1])])
            else:
                tracks[key].append([float(p[0]), float(p[1])])

    # normalise: figure height = 1, ground at y=0, horizontal locked to the hips
    ground = min(min(v[1] for v in tracks["ftR"]), min(v[1] for v in tracks["ftL"]))
    top = max(max(v[1] for v in tracks["head"]), max(v[1] for v in tracks["chest"]))
    height = max(top - ground, 1e-6)

    out_frames: list[dict[str, list[float]]] = []
    for i in range(out_count):
        cx = tracks["hips"][i][0]
        row: dict[str, list[float]] = {}
        for key in _KEEP:
            x, y = tracks[key][i]
            row[key] = [round((x - cx) / height, 4), round((y - ground) / height, 4)]
        out_frames.append(row)

    return {
        "name": name,
        "source": f"CMU {trial}",
        "plane": plane,
        "fps": out_fps,
        "frameCount": len(out_frames),
        "label": label,
        "height": 1.0,
        "frames": out_frames,
    }


def load_clip(name: str) -> dict[str, Any]:
    """Return a cached 2-D clip, converting from BVH on first use."""
    dest = clip_cache_dir() / f"{name}.json"
    if dest.is_file():
        try:
            return json.loads(dest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    clip = convert(name)
    dest.write_text(json.dumps(clip, ensure_ascii=False), encoding="utf-8")
    return clip


def build_all(names: Iterable[str] | None = None) -> dict[str, Path]:
    written: dict[str, Path] = {}
    for name in names or TRIALS:
        clip = convert(name)
        dest = clip_cache_dir() / f"{name}.json"
        dest.write_text(json.dumps(clip, ensure_ascii=False), encoding="utf-8")
        written[name] = dest
    return written


if __name__ == "__main__":  # pragma: no cover - manual conversion helper
    import sys

    names = sys.argv[1:] or list(TRIALS)
    for n, path in build_all(names).items():
        print(f"{n:12s} -> {path}")
