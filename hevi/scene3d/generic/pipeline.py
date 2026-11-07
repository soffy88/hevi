"""omodul: scene JSON -> validated scene -> baked camera -> frames -> mp4 -> verify."""
from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any

from .camera_path import bake_camera, frame_times
from .html import build_html
from .spec import SceneError, iter_objects, normalize_scene
from .templates import expand_template


def prepare(doc: dict[str, Any] | str | Path, *, base_dir: str | Path | None = None,
            enforce_prompt: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if isinstance(doc, (str, Path)):
        p = Path(doc)
        base_dir = base_dir or p.parent
        doc = json.loads(p.read_text(encoding="utf-8"))
    scene = normalize_scene(expand_template(doc), base_dir=base_dir, enforce_prompt=enforce_prompt)
    cam = bake_camera(scene["camera"], float(scene["duration_s"]), int(scene["fps"]))
    return scene, cam


def _stage_gltf(scene: dict[str, Any], workdir: Path) -> None:
    adir = workdir / "assets"
    for o in iter_objects(scene["objects"]):
        if o["type"] == "gltf":
            src = Path(o["src"])
            adir.mkdir(parents=True, exist_ok=True)
            name = f"{o['id']}{src.suffix.lower()}"
            shutil.copyfile(src, adir / name)
            o["url"] = f"./assets/{name}"
            if src.suffix.lower() == ".gltf":  # copy sibling buffers/textures
                for sib in src.parent.iterdir():
                    if sib.is_file() and sib != src and sib.suffix.lower() in (".bin", ".png", ".jpg", ".jpeg", ".webp", ".ktx2"):
                        shutil.copyfile(sib, adir / sib.name)


def render_scene(doc: dict[str, Any] | str | Path, out_dir: str | Path, *,
                 base_dir: str | Path | None = None, keep_frames: bool = False,
                 enforce_prompt: bool = True, sheet: bool = True) -> dict[str, Any]:
    from hevi.layer4_legacy.scene3d.renderer import ffprobe_frames, sha256

    from .browser_render import capture_frames, contact_sheet, encode_mp4, stage_workdir

    t0 = time.perf_counter()
    scene, cam = prepare(doc, base_dir=base_dir, enforce_prompt=enforce_prompt)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    work = out / "_work"
    if work.exists():
        shutil.rmtree(work)
    _stage_gltf(scene, work)
    page = stage_workdir(work, build_html(scene, cam))
    times = frame_times(float(scene["duration_s"]), int(scene["fps"]))
    frames = capture_frames(work, page.name, width=scene["width"], height=scene["height"],
                            times=times, frames_dir=work / "frames")
    t_cap = time.perf_counter()
    video = encode_mp4(work / "frames", int(scene["fps"]), out / f"{scene['name']}.mp4")
    probe = ffprobe_frames(video)
    if probe["nb_read_frames"] != len(times):
        raise SceneError(f"frame count mismatch: expected {len(times)} got {probe['nb_read_frames']}")
    if (probe["width"], probe["height"]) != (scene["width"], scene["height"]):
        raise SceneError(f"size mismatch {probe['width']}x{probe['height']}")
    fh = hashlib.sha256()
    for f in frames:
        fh.update(hashlib.sha256(f.read_bytes()).digest())
    sheet_path = None
    if sheet:
        step = max(1, len(frames) // 8)
        sheet_path = str(contact_sheet(frames[::step][:8], out / "contact_sheet.png"))
    (out / "scene.normalized.json").write_text(json.dumps(scene, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "camera.json").write_text(json.dumps(cam), encoding="utf-8")
    if keep_frames:
        shutil.move(str(work / "frames"), str(out / "frames"))
    shutil.rmtree(work, ignore_errors=True)
    result = {"mp4": str(video), "sha256": sha256(video), "frames_sha256": fh.hexdigest(),
              "frame_count": len(frames), "nb_read_frames": probe["nb_read_frames"],
              "width": scene["width"], "height": scene["height"], "fps": scene["fps"],
              "duration_s": scene["duration_s"], "prompt_report": scene["prompt_report"],
              "contact_sheet": sheet_path, "capture_s": round(t_cap - t0, 2),
              "total_s": round(time.perf_counter() - t0, 2)}
    (out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result
