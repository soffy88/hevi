"""HEVI P5 — Editable Project Delivery (Jianying/CapCut).

Generates real editable project files from canonical production artifacts.
Validates structural integrity before release.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hevi.ops.p5_types import (
    CaptionStyleProfile,
    ContentItem,
    EditableProjectManifest,
)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _pid() -> str:
    return uuid.uuid4().hex[:12]


# ── Jianying Draft Structure ───────────────────────────────────────────

@dataclass
class JianyingTrack:
    """Single track in Jianying timeline."""
    track_id: str
    track_type: str  # video, audio, text, sticker
    segments: list[Any] = field(default_factory=list)  # JianyingSegment or dict
    attribute: int = 0  # 0=main, 1=PIP, etc.
    flag: int = 0
    is_default: bool = False


@dataclass
class JianyingSegment:
    """Single segment on a track."""
    segment_id: str
    material_id: str
    target_timerange: dict[str, int]  # start, duration (microseconds)
    source_timerange: dict[str, int]  # start, duration
    clip: dict[str, Any] = field(default_factory=dict)
    extra_material_refs: list[str] = field(default_factory=list)
    visible: bool = True
    volume: float = 1.0
    speed: float = 1.0
    transform: dict[str, float] = field(default_factory=lambda: {"x": 0.0, "y": 0.0, "rotation": 0.0, "scale_x": 1.0, "scale_y": 1.0})


@dataclass
class JianyingMaterial:
    """Material reference in project."""
    material_id: str
    type: str  # video, audio, image, text, font
    path: str
    duration: int = 0  # microseconds
    width: int = 1280
    height: int = 720
    fps: int = 30
    audio_channels: int = 2
    sample_rate: int = 48000
    file_hash: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


def _us(seconds: float) -> int:
    """Convert seconds to microseconds."""
    return int(seconds * 1_000_000)



def _srt_cues(text: str) -> list[dict[str, Any]]:
    """Parse the common SRT subset into {start,end,text}; unknown lines ignored."""
    import re

    pattern = re.compile(
        r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
        r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{3})(?P<body>.*?)(?:\n\s*\n|\Z)",
        re.S,
    )

    def seconds(stamp: str) -> float:
        hh, mm, rest = stamp.replace(",", ".").split(":")
        return int(hh) * 3600 + int(mm) * 60 + float(rest)

    cues = []
    for match in pattern.finditer(text):
        body = " ".join(
            line.strip() for line in match.group("body").splitlines() if line.strip()
        )
        if body:
            cues.append({"start": seconds(match.group("start")),
                         "end": seconds(match.group("end")), "text": body})
    return cues


def _native_text_items(mat: JianyingMaterial, start_s: float, dur_s: float,
                       clip: dict[str, Any]) -> list[Any]:
    from hevi.studio.jianying_native import NativeItem

    path = Path(mat.path)
    text = ""
    try:
        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            content = payload.get("content", payload) if isinstance(payload, dict) else {}
            text = str(content.get("text") or content.get("caption") or "")
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        text = ""
    cues = _srt_cues(text) if path.suffix.lower() in {".srt", ".vtt"} else []
    scale = clip.get("scale") or {}
    transform = clip.get("transform") or {}
    settings = {
        "alpha": float(clip.get("alpha") or 1.0),
        "scale_x": float(scale.get("x") or 1.0),
        "scale_y": float(scale.get("y") or 1.0),
        "transform_x": float(transform.get("x") or 0.0),
        "transform_y": float(transform.get("y") or 0.0),
        "rotation": float(clip.get("rotation") or 0.0),
    }
    if cues:
        return [
            NativeItem(track="text", start_s=start_s + c["start"],
                       duration_s=max(0.04, c["end"] - c["start"]),
                       text=c["text"], transform=dict(settings))
            for c in cues
        ]
    return [NativeItem(track="text", start_s=start_s, duration_s=max(0.04, dur_s),
                       text=text or " ", transform=dict(settings))]

# ── Jianying Draft Builder ─────────────────────────────────────────────

class JianyingDraftBuilder:
    """Builds a valid Jianying draft from production artifacts."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.draft_dir = self.output_dir / f"draft_{_pid()}"
        self.draft_dir.mkdir(parents=True)
        self.materials_dir = self.draft_dir / "materials"
        self.materials_dir.mkdir(parents=True)

        self.materials: list[JianyingMaterial] = []
        self.tracks: list[JianyingTrack] = []
        self._material_map: dict[str, str] = {}  # source_path -> material_id

    def add_video_material(self, source_path: Path, file_hash: str = "") -> str:
        """Add video material, return material_id."""
        mat_id = f"video_{_pid()}"
        if not file_hash:
            file_hash = _sha256_file(source_path)

        dest = self.materials_dir / f"{mat_id}{source_path.suffix}"
        shutil.copy2(source_path, dest)

        mat = JianyingMaterial(
            material_id=mat_id,
            type="video",
            path=str(dest),
            duration=_get_video_duration_us(source_path),
            width=1280,
            height=720,
            fps=30,
            file_hash=file_hash,
        )
        self.materials.append(mat)
        self._material_map[str(source_path)] = mat_id
        return mat_id

    def add_audio_material(self, source_path: Path, file_hash: str = "") -> str:
        """Add audio material, return material_id."""
        mat_id = f"audio_{_pid()}"
        if not file_hash:
            file_hash = _sha256_file(source_path)

        dest = self.materials_dir / f"{mat_id}{source_path.suffix}"
        shutil.copy2(source_path, dest)

        mat = JianyingMaterial(
            material_id=mat_id,
            type="audio",
            path=str(dest),
            duration=_get_audio_duration_us(source_path),
            audio_channels=2,
            sample_rate=48000,
            file_hash=file_hash,
        )
        self.materials.append(mat)
        self._material_map[str(source_path)] = mat_id
        return mat_id

    def add_image_material(self, source_path: Path, file_hash: str = "") -> str:
        """Add image material, return material_id."""
        mat_id = f"image_{_pid()}"
        if not file_hash:
            file_hash = _sha256_file(source_path)

        dest = self.materials_dir / f"{mat_id}{source_path.suffix}"
        shutil.copy2(source_path, dest)

        mat = JianyingMaterial(
            material_id=mat_id,
            type="image",
            path=str(dest),
            duration=0,
            width=1280,
            height=720,
            file_hash=file_hash,
        )
        self.materials.append(mat)
        self._material_map[str(source_path)] = mat_id
        return mat_id

    def add_font_material(self, source_path: Path, file_hash: str = "") -> str:
        """Add font material, return material_id."""
        mat_id = f"font_{_pid()}"
        if not file_hash:
            file_hash = _sha256_file(source_path)

        dest = self.materials_dir / f"{mat_id}{source_path.suffix}"
        shutil.copy2(source_path, dest)

        mat = JianyingMaterial(
            material_id=mat_id,
            type="font",
            path=str(dest),
            file_hash=file_hash,
        )
        self.materials.append(mat)
        self._material_map[str(source_path)] = mat_id
        return mat_id

    def create_video_track(self, segments: list[JianyingSegment]) -> JianyingTrack:
        track = JianyingTrack(
            track_id=f"track_video_{_pid()}",
            track_type="video",
            segments=segments,
        )
        self.tracks.append(track)
        return track

    def create_audio_track(self, segments: list[JianyingSegment]) -> JianyingTrack:
        track = JianyingTrack(
            track_id=f"track_audio_{_pid()}",
            track_type="audio",
            segments=segments,
        )
        self.tracks.append(track)
        return track

    def create_text_track(self, segments: list[JianyingSegment]) -> JianyingTrack:
        track = JianyingTrack(
            track_id=f"track_text_{_pid()}",
            track_type="text",
            segments=segments,
        )
        self.tracks.append(track)
        return track

    def build_draft_json(self, canvas_width: int = 1280, canvas_height: int = 720, fps: int = 30) -> dict[str, Any]:
        """Generate complete draft_content.json structure."""
        total_duration = max(
            (max((s.target_timerange["start"] + s.target_timerange["duration"] for s in track.segments), default=0)
             for track in self.tracks),
            default=0
        )

        return {
            "version": "2.0.0",
            "create_time": int(time.time() * 1000),
            "update_time": int(time.time() * 1000),
            "draft_id": f"draft_{_pid()}",
            "draft_name": "HEVI Emotional Book Review",
            "draft_root": str(self.draft_dir),
            "materials": [asdict(m) for m in self.materials],
            "tracks": [asdict(t) for t in self.tracks],
            "canvas_config": {
                "width": canvas_width,
                "height": canvas_height,
                "ratio": f"{canvas_width}:{canvas_height}",
            },
            "duration": total_duration,
            "fps": fps,
            "speed": 1.0,
            "volume": 1.0,
            "pitch": 1.0,
        }

    def _material(self, material_id: str) -> JianyingMaterial | None:
        return next((m for m in self.materials if m.material_id == material_id), None)

    def _native_items(self) -> list[Any]:
        from hevi.studio.jianying_native import NativeItem

        items: list[NativeItem] = []
        for track in self.tracks:
            kind = "audio" if track.track_type == "audio" else "text" if track.track_type == "text" else "video"
            for raw in track.segments:
                seg = raw if isinstance(raw, dict) else asdict(raw)
                mat = self._material(str(seg.get("material_id") or ""))
                target = seg.get("target_timerange") or {}
                source = seg.get("source_timerange") or {}
                start_s = float(target.get("start") or 0) / 1_000_000
                dur_s = float(target.get("duration") or 0) / 1_000_000
                src_start_s = float(source.get("start") or 0) / 1_000_000
                if not mat:
                    continue
                if kind == "text":
                    items.extend(
                        _native_text_items(mat, start_s, dur_s, seg.get("clip") or {})
                    )
                    continue
                clip = seg.get("clip") or {}
                scale = clip.get("scale") or {}
                transform = clip.get("transform") or {}
                items.append(
                    NativeItem(
                        track=kind,
                        start_s=start_s,
                        duration_s=max(0.04, dur_s),
                        path=mat.path,
                        source_start_s=src_start_s,
                        volume=float(seg.get("volume") or 1.0),
                        transform={
                            "alpha": float(clip.get("alpha") or 1.0),
                            "scale_x": float(scale.get("x") or 1.0),
                            "scale_y": float(scale.get("y") or 1.0),
                            "transform_x": float(transform.get("x") or 0.0),
                            "transform_y": float(transform.get("y") or 0.0),
                            "rotation": float(clip.get("rotation") or 0.0),
                        },
                    )
                )
        return items

    def _write_text_capabilities(self) -> None:
        """Keep parametric-text sidecars readable next to a native draft.

        P5.1 records style capability in JSON sidecars.  A native draft carries
        text inline, so the sidecars are preserved in a parallel folder and
        indexed by element id; the projection reads them instead of guessing.
        """
        records: list[dict[str, Any]] = []
        sidecar_dir = self.draft_dir / "hevi_sidecars"
        for mat in self.materials:
            if mat.type != "text":
                continue
            src = Path(mat.path)
            if src.suffix.lower() != ".json" or not src.is_file():
                continue
            try:
                payload = json.loads(src.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            sidecar_dir.mkdir(exist_ok=True)
            dest = sidecar_dir / src.name
            if not dest.exists():
                shutil.copyfile(src, dest)
            records.append(
                {
                    "element_id": payload.get("element_id"),
                    "path": str(dest),
                    "supported_fields": payload.get("supported_fields") or [],
                    "unsupported_fields": payload.get("unsupported_fields") or [],
                    "content": payload.get("content") or {},
                }
            )
        if records:
            (self.draft_dir / "hevi_text_capabilities.json").write_text(
                json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
            )

    def save(self, canvas_width: int = 1280, canvas_height: int = 720, fps: int = 30) -> Path:
        """Save a *native* JianYing Pro draft into this builder's folder."""
        from hevi.studio.jianying_native import write_native_draft

        export = write_native_draft(
            "hevi_editable",
            self._native_items(),
            self.draft_dir,
            width=canvas_width,
            height=canvas_height,
            fps=fps,
            copy_media=False,
            package_zip=False,
            in_place=True,
        )
        self._write_text_capabilities()
        info = {
            "draft_name": export.name,
            "draft_root": str(self.draft_dir),
            "format": "jianying_native",
            "duration": round(export.duration_s * 1_000_000),
            "fps": fps,
        }
        (self.draft_dir / "draft_info.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return Path(export.draft_dir)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_video_duration_us(path: Path) -> int:
    import subprocess
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=False
    )
    try:
        return _us(float(result.stdout.strip()))
    except ValueError:
        return 0


def _get_audio_duration_us(path: Path) -> int:
    import subprocess
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=False
    )
    try:
        return _us(float(result.stdout.strip()))
    except ValueError:
        return 0


# ── High-level Content to Jianying ─────────────────────────────────────

def build_jianying_from_content(
    item: ContentItem,
    output_dir: Path,
    caption_style: CaptionStyleProfile | None = None,
) -> EditableProjectManifest:
    """Build complete Jianying project from ContentItem."""
    builder = JianyingDraftBuilder(output_dir)

    if item.final_mp4 and Path(item.final_mp4).exists():
        video_mat_id = builder.add_video_material(Path(item.final_mp4))
        video_seg = JianyingSegment(
            segment_id=f"seg_main_{_pid()}",
            material_id=video_mat_id,
            target_timerange={"start": 0, "duration": _get_video_duration_us(Path(item.final_mp4))},
            source_timerange={"start": 0, "duration": _get_video_duration_us(Path(item.final_mp4))},
        )
        builder.create_video_track([video_seg])

    if item.voice_performance and Path(item.voice_performance.audio_path).exists():
        audio_mat_id = builder.add_audio_material(Path(item.voice_performance.audio_path))
        audio_seg = JianyingSegment(
            segment_id=f"seg_voice_{_pid()}",
            material_id=audio_mat_id,
            target_timerange={"start": 0, "duration": _get_audio_duration_us(Path(item.voice_performance.audio_path))},
            source_timerange={"start": 0, "duration": _get_audio_duration_us(Path(item.voice_performance.audio_path))},
            volume=1.0,
        )
        builder.create_audio_track([audio_seg])

    if item.audio_mix and item.audio_mix.music_policy and item.audio_mix.music_policy.track:
        bgm_asset = next((a for a in item.visual_assets if a.type == "bgm" and a.path), None)
        if bgm_asset and Path(bgm_asset.path).exists():
            bgm_mat_id = builder.add_audio_material(Path(bgm_asset.path))
            video_dur_us = _get_video_duration_us(Path(item.final_mp4)) if item.final_mp4 else 0
            bgm_seg = JianyingSegment(
                segment_id=f"seg_bgm_{_pid()}",
                material_id=bgm_mat_id,
                target_timerange={"start": 0, "duration": video_dur_us},
                source_timerange={"start": 0, "duration": video_dur_us},
                volume=10 ** (item.audio_mix.music_gain_db / 20) if item.audio_mix else 0.12,
            )
            audio_track = JianyingTrack(
                track_id=f"track_bgm_{_pid()}",
                track_type="audio",
                segments=[asdict(bgm_seg)],
            )
            builder.tracks.append(audio_track)

    draft_dir = builder.save()

    return EditableProjectManifest(
        project_type="jianying",
        project_path=str(draft_dir),
        timeline_json=str(Path(draft_dir) / "draft_content.json"),
        audio_refs=[m.path for m in builder.materials if m.type == "audio"],
        video_image_refs=[m.path for m in builder.materials if m.type in ("video", "image")],
        caption_refs=[],
        font_refs=[m.path for m in builder.materials if m.type == "font"],
        music_refs=[m.path for m in builder.materials if m.type == "audio" and "bgm" in m.path.lower()],
        duration_s=_us_to_s(max(
            (max((s.target_timerange["start"] + s.target_timerange["duration"] for s in track.segments), default=0)
             for track in builder.tracks),
            default=0
        )),
        artifact_hashes={
            "draft_content.json": _sha256_file(draft_dir / "draft_content.json"),
        },
    )


def _parse_srt_to_segments(srt_path: Path, style: CaptionStyleProfile | None) -> list[JianyingSegment]:
    return []


def _us_to_s(us: int) -> float:
    return us / 1_000_000


# ── Validation ─────────────────────────────────────────────────────────

def validate_jianying_draft(draft_dir: Path) -> tuple[bool, list[str]]:
    """Validate a native JianYing draft (or a legacy handoff plan honestly)."""
    errors: list[str] = []

    draft_content = draft_dir / "draft_content.json"
    if not draft_content.exists():
        errors.append("draft_content.json missing")
        return False, errors

    try:
        data = json.loads(draft_content.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        errors.append(f"draft_content.json invalid JSON: {e}")
        return False, errors

    if isinstance(data.get("materials"), dict):
        from hevi.studio.jianying_native import validate_native_draft

        report = validate_native_draft(draft_dir)
        return bool(report["valid"]), list(report["errors"])

    required = ["version", "draft_id", "materials", "tracks", "canvas_config", "duration", "fps"]
    errors.extend(
        f"missing required field: {field_name}"
        for field_name in required
        if field_name not in data
    )

    for mat in data.get("materials", []):
        mat_path = Path(mat.get("path", ""))
        if mat_path and not mat_path.exists():
            errors.append(f"material file missing: {mat_path}")

    errors.extend(
        f"track {track.get('track_id')} has no segments"
        for track in data.get("tracks", [])
        if not track.get("segments")
    )

    return len(errors) == 0, errors


def validate_editable_delivery(ep: EditableProjectManifest) -> tuple[bool, list[str]]:
    """Full editable project validation for delivery gate."""
    errors = []

    if not ep.project_path or not Path(ep.project_path).exists():
        errors.append(f"project_path not found: {ep.project_path}")
        return False, errors

    valid, errors = validate_jianying_draft(Path(ep.project_path))
    if not valid:
        return False, errors

    for ref_list in [ep.audio_refs, ep.video_image_refs, ep.caption_refs, ep.font_refs, ep.music_refs]:
        for ref in ref_list:
            if not Path(ref).exists():
                errors.append(f"referenced asset missing: {ref}")

    if ep.duration_s <= 0:
        errors.append("duration_s must be positive")

    return len(errors) == 0, errors


# ── CapCut Support (Future) ────────────────────────────────────────────

def build_capcut_from_content(item: ContentItem, output_dir: Path) -> EditableProjectManifest:
    """Build CapCut project (stub - similar structure to Jianying)."""
    raise NotImplementedError("CapCut export not yet implemented")


__all__ = [
    "JianyingDraftBuilder",
    "JianyingMaterial",
    "JianyingSegment",
    "JianyingTrack",
    "build_capcut_from_content",
    "build_jianying_from_content",
    "validate_editable_delivery",
    "validate_jianying_draft",
]