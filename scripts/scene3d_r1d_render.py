"""Render the six R1D acceptance clips sequentially and verify exact reproducibility."""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from hevi.capabilities.scene3d import _build_spec
from hevi.layer4_legacy.scene3d import renderer as R
from hevi.layer4_legacy.scene3d.kids_gate import evaluate_frames

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "scene3d_r1d"
TEMP = ROOT / ".tmp" / "r1d_determinism"
RESOLUTION = 1080
SEED = 1234
CLIPS = [
    ("planet_orbit_16x9", "scene3d.planet_orbit", "16:9", "little_planet_orbit.json"),
    ("planet_orbit_9x16", "scene3d.planet_orbit", "9:16", "little_planet_orbit.json"),
    ("fox_wheat_9x16", "scene3d.fox_wheat", "9:16", "fox_in_wheat.json"),
    ("fox_wheat_16x9", "scene3d.fox_wheat", "16:9", "fox_in_wheat.json"),
    ("star_sea_9x16", "scene3d.star_sea", "9:16", "through_star_sea.json"),
    ("star_sea_16x9", "scene3d.star_sea", "16:9", "through_star_sea.json"),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_six_frame_sheet(frame_paths: list[Path], duration: float, out_path: Path) -> list[dict[str, Any]]:
    if len(frame_paths) < 6:
        raise RuntimeError(f"expected six frames for contact sheet, got {len(frame_paths)}")
    indexes = [round(i * (len(frame_paths) - 1) / 5) for i in range(6)]
    selected = [frame_paths[i] for i in indexes]
    sheet = Image.new("RGB", (960, 540), (24, 25, 56))
    draw = ImageDraw.Draw(sheet)
    thumb_box = (300, 225)
    for slot, (index, path) in enumerate(zip(indexes, selected)):
        image = Image.open(path).convert("RGB")
        image.thumbnail(thumb_box, Image.Resampling.LANCZOS)
        col = slot % 3
        row = slot // 3
        x0 = col * 320 + (320 - image.width) // 2
        y0 = row * 270 + 28 + (225 - image.height) // 2
        sheet.paste(image, (x0, y0))
        timestamp = min(duration, index / 30.0)
        draw.text((col * 320 + 10, row * 270 + 6), f"t={timestamp:.2f}s  frame {index + 1}", fill=(255, 255, 255))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=92)
    return [{"frame": indexes[i] + 1, "time_s": round(min(duration, indexes[i] / 30.0), 3), "path": str(selected[i])} for i in range(6)]


def build_spec(capability: str, aspect: str, preset_file: str):
    preset = json.loads((ROOT / "hevi" / "layer4_legacy" / "scene3d" / "examples" / preset_file).read_text())
    duration = float(preset["duration_s"])
    spec = _build_spec(
        capability,
        {"resolution": RESOLUTION, "fps": 30, "seed": SEED},
        duration=duration,
        aspect=aspect,
        seed=SEED,
    )
    return spec


def render_and_measure(name: str, capability: str, aspect: str, preset_file: str) -> dict[str, Any]:
    spec = build_spec(capability, aspect, preset_file)
    out_dir = OUTPUT / name
    out_dir.mkdir(parents=True, exist_ok=True)
    start = time.perf_counter()
    renderer = R.SceneRenderer(spec, out_dir)
    metrics = renderer.render()
    video = Path(metrics["video"])
    raw_probe = R.ffprobe(video)
    counted_probe = R.ffprobe_frames(video)
    expected = math.ceil(spec.duration_s * spec.fps)
    if counted_probe["nb_read_frames"] != expected:
        raise RuntimeError(f"{name}: expected {expected} frames, got {counted_probe['nb_read_frames']}")
    if abs(raw_probe["duration"] - spec.duration_s) > 0.15:
        raise RuntimeError(f"{name}: duration {raw_probe['duration']} differs from {spec.duration_s}")
    if raw_probe["width"] != spec.width or raw_probe["height"] != spec.height:
        raise RuntimeError(f"{name}: wrong resolution {raw_probe['width']}x{raw_probe['height']}")

    all_frames = [Path(p) for p in metrics["frames"]]
    sheet = out_dir / "contact_sheet_6f.png"
    selected = make_six_frame_sheet(all_frames, spec.duration_s, sheet)
    # Check the completed shot at 10 samples per second, downsized to keep the
    # kids gate's sampling cost stable while preserving the full-frame palette.
    sampled = [Image.open(all_frames[i]).convert("RGB").resize((64, 64), Image.Resampling.LANCZOS)
               for i in range(0, len(all_frames), 3)]
    gate = evaluate_frames(sampled, fps=10.0, duration_s=spec.duration_s)
    if not gate.passed:
        raise RuntimeError(f"{name}: kids_gate failed: {gate.as_dict()}")

    # Render the exact same spec again, serially in .tmp, then compare encoded bytes.
    det_dir = TEMP / name
    det_dir.mkdir(parents=True, exist_ok=True)
    det_renderer = R.SceneRenderer(spec, det_dir)
    det_metrics = det_renderer.render()
    det_video = Path(det_metrics["video"])
    det_hash = sha256(det_video)
    main_hash = sha256(video)
    if det_hash != main_hash:
        raise RuntimeError(f"{name}: deterministic SHA mismatch {main_hash} != {det_hash}")
    result = {
        "name": name,
        "capability": capability,
        "aspect": aspect,
        "seed": spec.seed,
        "duration_s": raw_probe["duration"],
        "width": raw_probe["width"],
        "height": raw_probe["height"],
        "codec": raw_probe["codec"],
        "r_frame_rate": counted_probe.get("r_frame_rate"),
        "frame_count": metrics["frame_count"],
        "nb_read_frames": counted_probe["nb_read_frames"],
        "sha256": main_hash,
        "deterministic_sha256": det_hash,
        "deterministic_match": True,
        "size_bytes": raw_probe["size_bytes"],
        "render_elapsed_s": round(time.perf_counter() - start, 2),
        "per_frame_s": metrics["per_frame_s"],
        "encode_s": metrics["encode_s"],
        "contact_sheet": str(sheet.relative_to(ROOT)),
        "contact_frames": selected,
        "kids_gate": gate.as_dict(),
        "video": str(video.relative_to(ROOT)),
        "determinism_video": str(det_video.relative_to(ROOT)),
    }
    (out_dir / "r1d_metrics.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    TEMP.mkdir(parents=True, exist_ok=True)
    result_path = OUTPUT / "r1d_render_results.json"
    previous = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
    prior_rows = {row["name"]: row for row in previous.get("clips", [])}
    prior_failures = {row["name"]: row for row in previous.get("failures", [])}
    only = {part.strip() for part in os.environ.get("SCENE3D_R1D_ONLY", "").split(",") if part.strip()}
    selected_clips = [clip for clip in CLIPS if not only or clip[0] in only]
    if only and only - {clip[0] for clip in CLIPS}:
        raise ValueError(f"unknown SCENE3D_R1D_ONLY names: {sorted(only - {clip[0] for clip in CLIPS})}")
    for name, _, _, _ in selected_clips:
        prior_rows.pop(name, None)
        prior_failures.pop(name, None)
    for name, capability, aspect, preset_file in selected_clips:
        print(f"START {name} aspect={aspect} resolution={RESOLUTION} seed={SEED}", flush=True)
        try:
            row = render_and_measure(name, capability, aspect, preset_file)
            prior_rows[name] = row
            print(json.dumps({"PASS": name, "sha256": row["sha256"], "duration_s": row["duration_s"], "resolution": f"{row['width']}x{row['height']}", "frames": row["nb_read_frames"], "mean_saturation": row["kids_gate"]["mean_saturation"]}, ensure_ascii=False), flush=True)
        except Exception as exc:
            prior_failures[name] = {"name": name, "error": f"{type(exc).__name__}: {exc}"}
            print(f"FAIL {name}: {type(exc).__name__}: {exc}", flush=True)
    rows = [prior_rows[clip[0]] for clip in CLIPS if clip[0] in prior_rows]
    failures = [prior_failures[clip[0]] for clip in CLIPS if clip[0] in prior_failures]
    summary = {
        "resolution_setting": RESOLUTION,
        "fps": 30,
        "seed": SEED,
        "clips": rows,
        "failures": failures,
        "complete": len(rows) == len(CLIPS) and not failures,
        "selected_this_run": [clip[0] for clip in selected_clips],
    }
    result_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"completed": len(rows), "failed": len(failures), "complete": summary["complete"], "summary": str(result_path.relative_to(ROOT))}, ensure_ascii=False), flush=True)
    # Per-clip failures are persisted in the machine-readable report; return 0
    # so the remote runner does not replay the whole expensive render batch.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
