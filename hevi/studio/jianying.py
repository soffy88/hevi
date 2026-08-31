"""剪映专业版草稿导出 —— 对照 jianying-editor-skill / shotcraft JianYing export。

写出 draft 目录(draft_content.json + draft_meta_info.json + materials 清单)。
不操作剪映 UI、不自动导出 MP4。国际版 CapCut 不保证可导入;国内草稿格式随
版本变,调用方应把这当成可编辑交接包,而不是 5.9 自动导出。
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _us(seconds: float) -> int:
    return max(0, round(float(seconds) * 1_000_000))


@dataclass
class JianyingClip:
    path: str
    start_s: float
    duration_s: float
    track: str = "video"  # video | audio | text
    text: str = ""
    volume: float = 1.0

    def to_segment(self, material_id: str, timeline_start_us: int) -> dict[str, Any]:
        dur = _us(self.duration_s)
        return {
            "id": material_id,
            "material_id": material_id,
            "target_timerange": {"start": timeline_start_us, "duration": dur},
            "source_timerange": {"start": _us(self.start_s), "duration": dur},
            "track": self.track,
            "text": self.text,
            "volume": self.volume,
            "path": self.path,
        }


@dataclass
class JianyingDraft:
    name: str
    width: int = 1920
    height: int = 1080
    fps: int = 30
    clips: list[JianyingClip] = field(default_factory=list)

    def duration_s(self) -> float:
        return sum(max(0.0, c.duration_s) for c in self.clips if c.track == "video") or sum(
            max(0.0, c.duration_s) for c in self.clips
        )

    def to_content(self) -> dict[str, Any]:
        materials: dict[str, list[dict[str, Any]]] = {
            "videos": [],
            "audios": [],
            "texts": [],
        }
        tracks: dict[str, list[dict[str, Any]]] = {
            "video": [],
            "audio": [],
            "text": [],
        }
        cursor = {"video": 0, "audio": 0, "text": 0}
        for i, clip in enumerate(self.clips):
            mid = f"{clip.track}-{i:03d}"
            bucket = (
                "videos" if clip.track == "video" else "audios" if clip.track == "audio" else "texts"
            )
            materials[bucket].append(
                {
                    "id": mid,
                    "path": clip.path,
                    "duration": _us(clip.duration_s),
                    "text": clip.text,
                }
            )
            t0 = cursor.get(clip.track, 0)
            tracks.setdefault(clip.track, []).append(clip.to_segment(mid, t0))
            cursor[clip.track] = t0 + _us(clip.duration_s)
        return {
            "fps": self.fps,
            "duration": _us(self.duration_s()),
            "canvas_config": {
                "width": self.width,
                "height": self.height,
                "ratio": f"{self.width}:{self.height}",
            },
            "materials": materials,
            "tracks": [
                {"type": kind, "segments": segs} for kind, segs in tracks.items() if segs
            ],
        }

    def to_meta(self) -> dict[str, Any]:
        return {
            "draft_name": self.name,
            "tm_duration": _us(self.duration_s()),
            "draft_fold_path": "",
            "draft_root_path": "",
            "app": "JianyingPro",
            "region": "CN",
            "note": "Hevi NLE handoff. Not CapCut International. Import in Jianying desktop.",
        }


def clips_from_recut(
    clips: list[dict[str, Any]],
    *,
    film: str = "",
    captions: list[dict[str, Any]] | None = None,
    bgm: str = "",
) -> list[JianyingClip]:
    """从 nle recut/clip.factory 产物抽剪映轨。"""
    out: list[JianyingClip] = []
    for clip in clips:
        if str(clip.get("action") or "keep") == "drop":
            continue
        source = str(clip.get("source") or film or "")
        if not source:
            continue
        track = str(clip.get("track") or "video")
        if track not in {"video", "audio", "text"}:
            track = "video"
        out.append(
            JianyingClip(
                path=source,
                start_s=float(clip.get("source_in_s") or 0.0),
                duration_s=max(0.04, float(clip.get("duration_s") or 0.0)),
                track=track,
                text=str(clip.get("text") or clip.get("title") or ""),
            )
        )
    out.extend(
        JianyingClip(
            path="",
            start_s=float(cap.get("start") or 0.0),
            duration_s=max(0.04, float(cap.get("end") or 0.0) - float(cap.get("start") or 0.0)),
            track="text",
            text=str(cap.get("text") or ""),
        )
        for cap in captions or []
    )
    if bgm:
        dur = sum(c.duration_s for c in out if c.track == "video") or 1.0
        out.append(JianyingClip(path=bgm, start_s=0.0, duration_s=dur, track="audio", volume=0.28))
    return out


def write_jianying_draft(
    draft: JianyingDraft,
    dest_dir: Path,
    *,
    copy_media: bool = False,
) -> Path:
    """写草稿目录。copy_media=True 时把本地素材拷进 materials/。"""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    materials_dir = dest / "materials"
    materials_dir.mkdir(exist_ok=True)
    if copy_media:
        rewritten: list[JianyingClip] = []
        for i, clip in enumerate(draft.clips):
            src = Path(clip.path) if clip.path else None
            if src and src.exists() and src.is_file():
                target = materials_dir / f"{i:03d}_{src.name}"
                if src.resolve() != target.resolve():
                    shutil.copyfile(src, target)
                rewritten.append(
                    JianyingClip(
                        path=str(target),
                        start_s=clip.start_s,
                        duration_s=clip.duration_s,
                        track=clip.track,
                        text=clip.text,
                        volume=clip.volume,
                    )
                )
            else:
                rewritten.append(clip)
        draft = JianyingDraft(
            name=draft.name,
            width=draft.width,
            height=draft.height,
            fps=draft.fps,
            clips=rewritten,
        )
    (dest / "draft_content.json").write_text(
        json.dumps(draft.to_content(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (dest / "draft_meta_info.json").write_text(
        json.dumps(draft.to_meta(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return dest
