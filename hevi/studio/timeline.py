"""ChatCut 式时间线 —— 编辑对象是项目,不是再跑一条管线。"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, cast

from hevi.studio.kit import nle_recut

_STORE: dict[str, Timeline] = {}


def _timeline_root() -> Path:
    return Path(os.getenv("HEVI_TIMELINE_DIR", "data/timelines")).expanduser()


def _timeline_path(timeline_id: str) -> Path:
    return _timeline_root() / f"{timeline_id}.json"


def _load_from_disk(timeline_id: str) -> Timeline | None:
    path = _timeline_path(timeline_id)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        timeline = Timeline.from_dict(payload)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    _STORE[timeline.timeline_id] = timeline
    return timeline


@dataclass
class TimelineClip:
    clip_id: str
    track: str  # video | audio | captions
    start_s: float
    duration_s: float
    label: str
    action: str = "keep"  # keep | drop | mute
    source: str = ""
    text: str = ""
    source_in_s: float = 0.0
    speed: float = 1.0
    reverse: bool = False
    transition: str = "cut"
    effect: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Timeline:
    timeline_id: str
    title: str
    clips: list[TimelineClip] = field(default_factory=list)
    bgm: str = ""
    fps: int = 24
    source_film: str = ""

    @property
    def duration_s(self) -> float:
        if not self.clips:
            return 0.0
        return max(c.start_s + c.duration_s for c in self.clips)

    @property
    def tracks(self) -> dict[str, list[TimelineClip]]:
        return {
            name: [c for c in self.clips if c.track == name]
            for name in ("video", "audio", "captions")
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "timeline_id": self.timeline_id,
            "title": self.title,
            "duration_s": round(self.duration_s, 2),
            "bgm": self.bgm,
            "fps": self.fps,
            "source_film": self.source_film,
            "clips": [c.to_dict() for c in self.clips],
            "tracks": {name: [c.to_dict() for c in items] for name, items in self.tracks.items()},
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Timeline:
        clips: list[TimelineClip] = []
        for raw in payload.get("clips") or []:
            if not isinstance(raw, dict):
                continue
            clips.append(
                TimelineClip(
                    clip_id=str(raw.get("clip_id") or uuid.uuid4()),
                    track=str(raw.get("track") or "video"),
                    start_s=float(raw.get("start_s") or 0.0),
                    duration_s=max(0.0, float(raw.get("duration_s") or 0.0)),
                    label=str(raw.get("label") or ""),
                    action=str(raw.get("action") or "keep"),
                    source=str(raw.get("source") or ""),
                    text=str(raw.get("text") or ""),
                    source_in_s=float(raw.get("source_in_s") or 0.0),
                    speed=float(raw.get("speed") or 1.0),
                    reverse=bool(raw.get("reverse")),
                    transition=str(raw.get("transition") or "cut"),
                    effect=str(raw.get("effect") or "none"),
                )
            )
        return cls(
            timeline_id=str(payload.get("timeline_id") or uuid.uuid4()),
            title=str(payload.get("title") or "untitled"),
            clips=clips,
            bgm=str(payload.get("bgm") or ""),
            fps=int(payload.get("fps") or 24),
            source_film=str(payload.get("source_film") or ""),
        )


def reset_timelines() -> None:
    _STORE.clear()


def get_timeline(timeline_id: str) -> Timeline | None:
    return _STORE.get(timeline_id) or _load_from_disk(timeline_id)


def list_timelines() -> list[Timeline]:
    root = _timeline_root()
    if root.is_dir():
        for path in root.glob("*.json"):
            if path.stem not in _STORE:
                _load_from_disk(path.stem)
    return list(_STORE.values())


def save_timeline(tl: Timeline) -> Timeline:
    _STORE[tl.timeline_id] = tl
    root = _timeline_root()
    root.mkdir(parents=True, exist_ok=True)
    path = _timeline_path(tl.timeline_id)
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(tl.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return tl


def timeline_from_edit_plan(plan: dict[str, Any], *, title: str = "untitled") -> Timeline:
    tl = Timeline(timeline_id=str(uuid.uuid4()), title=title)
    for i, cut in enumerate(plan.get("cuts") or []):
        if not isinstance(cut, dict):
            continue
        start = float(cut.get("start_s") or 0)
        dur = float(cut.get("duration_s") or 2.5)
        text = str(cut.get("text") or f"cut {i}")
        src = str(cut.get("visual") or cut.get("source") or "")
        action = str(cut.get("action") or "keep")
        tl.clips.append(
            TimelineClip(
                clip_id=f"v{i}",
                track="video",
                start_s=start,
                duration_s=dur,
                label=text[:24],
                action=action,
                source=src,
                text=text,
                source_in_s=float(cut.get("source_in_s") or 0.0),
                speed=max(0.25, min(4.0, float(cut.get("speed") or 1.0))),
                reverse=bool(cut.get("reverse")),
                transition=str(cut.get("transition") or "cut"),
                effect=str(cut.get("effect") or "none"),
            )
        )
        tl.clips.append(
            TimelineClip(
                clip_id=f"a{i}",
                track="audio",
                start_s=start,
                duration_s=dur,
                label="VO",
                action=action,
                text=text,
            )
        )
        tl.clips.append(
            TimelineClip(
                clip_id=f"c{i}",
                track="captions",
                start_s=start,
                duration_s=dur,
                label=text[:18],
                action="keep",
                text=text,
            )
        )
    return save_timeline(tl)


def patch_clip(
    timeline_id: str,
    clip_id: str,
    *,
    action: str | None = None,
    label: str | None = None,
    duration_s: float | None = None,
    text: str | None = None,
    speed: float | None = None,
    reverse: bool | None = None,
    transition: str | None = None,
    effect: str | None = None,
) -> Timeline | None:
    tl = get_timeline(timeline_id)
    if tl is None:
        return None
    for clip in tl.clips:
        if clip.clip_id != clip_id:
            continue
        if action in {"keep", "drop", "mute"}:
            clip.action = action
        if label is not None:
            clip.label = label
        if duration_s is not None:
            clip.duration_s = max(0.4, float(duration_s))
        if text is not None:
            clip.text = text
        if speed is not None:
            clip.speed = max(0.25, min(4.0, float(speed)))
        if reverse is not None:
            clip.reverse = bool(reverse)
        if transition in {"cut", "dissolve", "wipe", "smash"}:
            clip.transition = transition
        if effect in {"none", "warm", "cool", "mono", "vignette", "sharpen"}:
            clip.effect = effect
        return save_timeline(tl)
    return None


def set_bgm(timeline_id: str, bgm: str) -> Timeline | None:
    tl = get_timeline(timeline_id)
    if tl is None:
        return None
    tl.bgm = bgm
    return save_timeline(tl)


def split_at(timeline_id: str, at_s: float) -> Timeline | None:
    """ChatCut 式:在游标切开所有轨上压到的 clip。"""
    tl = get_timeline(timeline_id)
    if tl is None:
        return None
    mark = max(0.2, float(at_s))
    spawned: list[TimelineClip] = []
    for clip in tl.clips:
        end = clip.start_s + clip.duration_s
        if not (clip.start_s + 0.2 < mark < end - 0.2):
            continue
        right = TimelineClip(
            clip_id=f"{clip.clip_id}s{uuid.uuid4().hex[:4]}",
            track=clip.track,
            start_s=mark,
            duration_s=round(end - mark, 3),
            label=clip.label,
            action=clip.action,
            source=clip.source,
            text=clip.text,
            source_in_s=round(clip.source_in_s + (mark - clip.start_s) * clip.speed, 3),
            speed=clip.speed,
            reverse=clip.reverse,
            transition=clip.transition,
            effect=clip.effect,
        )
        clip.duration_s = round(mark - clip.start_s, 3)
        spawned.append(right)
    tl.clips.extend(spawned)
    return save_timeline(tl)


def ripple(timeline_id: str) -> Timeline | None:
    """丢掉的镜不再占时间,后面的 clip 左移收缝。"""
    tl = get_timeline(timeline_id)
    if tl is None:
        return None
    for track in ("video", "audio", "captions"):
        clips = sorted(
            (c for c in tl.clips if c.track == track),
            key=lambda c: c.start_s,
        )
        cursor = 0.0
        for clip in clips:
            if clip.action == "drop":
                continue
            clip.start_s = round(cursor, 3)
            cursor += clip.duration_s
    return save_timeline(tl)


def timeline_from_film(
    film: str | Path,
    *,
    duration_s: float | None = None,
    title: str = "imported",
) -> Timeline:
    path = Path(film)
    dur = duration_s
    if dur is None:
        try:
            from oprim import probe_duration

            probe = cast(Any, probe_duration)
            dur = float(probe(path)) if path.exists() else 10.0
        except Exception:
            dur = 10.0
    tl = Timeline(
        timeline_id=str(uuid.uuid4()),
        title=title,
        source_film=str(path),
    )
    tl.clips = [
        TimelineClip("v0", "video", 0.0, float(dur), path.stem, source=str(path)),
        TimelineClip("a0", "audio", 0.0, float(dur), "VO", source=str(path)),
        TimelineClip("c0", "captions", 0.0, float(dur), path.stem),
    ]
    return save_timeline(tl)


def export_timeline(timeline_id: str, dest: Path) -> dict[str, Any]:
    tl = get_timeline(timeline_id)
    if tl is None:
        return {"status": "failed", "reason": "unknown timeline"}
    clips = [
        {
            "track": c.track,
            "action": c.action,
            "source": c.source or tl.source_film,
            "source_in_s": c.source_in_s,
            "duration_s": c.duration_s,
            "speed": c.speed,
            "reverse": c.reverse,
            "transition": c.transition,
            "effect": c.effect,
        }
        for c in tl.clips
        if c.track == "video"
    ]
    result = nle_recut(
        {
            "clips": clips,
            "output_path": str(dest),
            "bgm": tl.bgm,
            "film": tl.source_film,
        }
    )
    result["timeline_id"] = timeline_id
    result["kept"] = len([c for c in tl.clips if c.track == "video" and c.action != "drop"])
    return result
