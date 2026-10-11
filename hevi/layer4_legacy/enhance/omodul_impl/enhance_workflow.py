"""OMQUALITY enhancement transaction (omodul layer, standard 3O signature).

``enhance_media_workflow(config, input_data, output_dir)`` runs exactly one of
the four enhancement operations against a real media file and writes the
result next to a ``enhance_report.json`` ledger.  It never fakes an output: a
missing weight/dependency or a failed ffmpeg call yields ``status="failed"``.

Config keys
-----------
op                  : "matte" | "upscale" | "face_restore" | "lut"
scale               : 2 | 4                (upscale)
look / intensity    : str / float 0..1     (lut)
model               : rembg session name   (matte, default u2net)
weight              : GFPGAN blend 0..1    (face_restore, default 0.5)
allow_noncommercial : bool                 (face_restore, default False)
process_video       : bool                 (run op over decoded frames)
max_frames          : int                  (video safety cap, default 0 = all)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from hevi.layer4_legacy.enhance.oprim_impl.contracts import (
    LICENSE_COMMERCIAL_OK,
    LICENSE_NONCOMMERCIAL_ONLY,
    EnhanceResult,
)
from hevi.layer4_legacy.enhance.oprim_impl.media import (
    MediaError,
    extract_frames,
    media_kind,
    probe_media,
)
from hevi.layer4_legacy.enhance.oprim_impl.models import ModelUnavailable

logger = logging.getLogger(__name__)

#: 3O omodul pillars this transaction enables.
_enabled_pillars = {"report", "decision_trail"}

_OPS = ("matte", "upscale", "face_restore", "lut")


class EnhanceConfigError(ValueError):
    """The caller supplied an unusable configuration."""


class EnhanceUnavailable(RuntimeError):
    """A required local dependency or weight is missing (fail-closed)."""


def _resolve_input(config: dict[str, Any], input_data: dict[str, Any]) -> Path:
    raw = (
        input_data.get("input_path")
        or input_data.get("path")
        or config.get("input_path")
        or config.get("input")
    )
    if not raw:
        raise EnhanceConfigError("input_path is required")
    path = Path(str(raw))
    if not path.is_file():
        raise EnhanceConfigError(f"input not found: {path}")
    return path


def _noncommercial_allowed(config: dict[str, Any]) -> bool:
    if bool(config.get("allow_noncommercial")):
        return True
    return os.environ.get("HEVI_ENHANCE_ALLOW_NONCOMMERCIAL", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _run_image_op(
    op: str,
    src: Path,
    dest: Path,
    config: dict[str, Any],
    workdir: Path,
) -> tuple[dict[str, Any], str, str]:
    """Run one op on a single image. Returns (metrics, model, license)."""
    if op == "matte":
        from hevi.layer4_legacy.enhance.oprim_impl.matting import matte_image

        model = str(config.get("model") or "u2net")
        metrics = matte_image(
            src,
            dest,
            model=model,
            mask_path=workdir / f"{dest.stem}_mask.png",
            post_process=bool(config.get("post_process", True)),
        )
        return metrics, f"rembg:{model}", LICENSE_COMMERCIAL_OK

    if op == "upscale":
        from hevi.layer4_legacy.enhance.oprim_impl.superres import upscale_image

        scale = int(config.get("scale") or 2)
        metrics = upscale_image(src, dest, scale=scale, tile=int(config.get("tile") or 256))
        return metrics, f"RealESRGAN_x{scale}plus", LICENSE_COMMERCIAL_OK

    if op == "face_restore":
        if not _noncommercial_allowed(config):
            raise EnhanceConfigError(
                "face_restore uses GFPGAN research weights (non-commercial only); "
                "set allow_noncommercial=True to opt in"
            )
        from hevi.layer4_legacy.enhance.oprim_impl.face import restore_faces

        metrics = restore_faces(
            src,
            dest,
            weight=float(config.get("weight") or 0.5),
            upscale=int(config.get("upscale") or 2),
            only_center_face=bool(config.get("only_center_face", False)),
        )
        return metrics, "GFPGANv1.4", LICENSE_NONCOMMERCIAL_ONLY

    if op == "lut":
        from hevi.layer4_legacy.enhance.oprim_impl.lut import apply_lut

        look = str(config.get("look") or "neutral")
        metrics = apply_lut(
            src,
            dest,
            look=look,
            lut_dir=workdir / "luts",
            intensity=float(config.get("intensity") or 1.0),
        )
        return metrics, f"lut:{look}", LICENSE_COMMERCIAL_OK

    raise EnhanceConfigError(f"unknown op: {op}")


def enhance_media_workflow(
    config: dict[str, Any],
    input_data: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, Any]:
    """Run one enhancement op end-to-end; always returns a status dict."""
    config = dict(config or {})
    input_data = dict(input_data or {})
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    op = str(config.get("op") or input_data.get("op") or "")
    if op not in _OPS:
        return {"status": "failed", "error": f"op must be one of {_OPS}, got {op!r}"}

    try:
        src = _resolve_input(config, input_data)
    except EnhanceConfigError as exc:
        return {"status": "failed", "error": str(exc)}

    kind = media_kind(src)
    if kind not in ("image", "video"):
        return {"status": "failed", "error": f"unsupported input kind: {kind} ({src})"}

    results: list[dict[str, Any]] = []
    notes: list[str] = []
    try:
        if kind == "image":
            dest = out / f"{op}_{src.stem}{_out_suffix(op)}"
            metrics, model, lic = _run_image_op(op, src, dest, config, out)
            results.append(
                EnhanceResult(
                    op=op,
                    input_path=str(src),
                    output_path=str(dest),
                    backend=model,
                    model=model,
                    license=lic,
                    commercial_ok=lic == LICENSE_COMMERCIAL_OK,
                    metrics=metrics,
                ).to_dict()
            )
        else:
            notes.append("video input: op applied per decoded frame")
            results, notes = _run_video_op(op, src, out, config, notes)
    except (EnhanceConfigError, ModelUnavailable) as exc:
        return {"status": "failed", "error": str(exc), "op": op}
    except (MediaError, RuntimeError, OSError, ValueError) as exc:
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}", "op": op}

    report = {
        "status": "ok",
        "op": op,
        "input": str(src),
        "input_kind": kind,
        "output_dir": str(out),
        "results": results,
        "notes": notes,
    }
    (out / "enhance_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def _out_suffix(op: str) -> str:
    return ".png" if op in ("matte", "face_restore") else ".png"


def _run_video_op(
    op: str,
    src: Path,
    out: Path,
    config: dict[str, Any],
    notes: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Apply an image op across decoded video frames, then re-encode."""
    import cv2

    from hevi.layer4_legacy.enhance.oprim_impl.media import frames_to_video, video_to_frames

    info = probe_media(src)
    max_frames = int(config.get("max_frames") or 0)
    if not bool(config.get("process_video", False)):
        # default: enhance 4 representative frames + report (cheap, honest)
        frames = extract_frames(src, out / "frames", count=4)
        notes.append("process_video=False: enhanced 4 representative frames only")
        results = []
        for i, frame in enumerate(frames):
            dest = out / f"{op}_frame{i}{_out_suffix(op)}"
            metrics, model, lic = _run_image_op(op, frame, dest, config, out)
            results.append(
                EnhanceResult(
                    op=op,
                    input_path=str(frame),
                    output_path=str(dest),
                    backend=model,
                    model=model,
                    license=lic,
                    commercial_ok=lic == LICENSE_COMMERCIAL_OK,
                    metrics=metrics,
                ).to_dict()
            )
        return results, notes

    frames, fps = video_to_frames(src, out / "decoded", limit=max_frames)
    notes.append(f"decoded {len(frames)} frames @ {fps:.3f} fps")
    processed: list[Path] = []
    for i, frame in enumerate(frames):
        dest = out / "enhanced" / f"f_{i:06d}.png"
        _run_image_op(op, frame, dest, config, out)
        processed.append(dest)
    video_path = frames_to_video(
        processed, out / f"{op}_video.mp4", fps=fps, audio_from=src if info.has_audio else None
    )
    return (
        [
            EnhanceResult(
                op=op,
                input_path=str(src),
                output_path=str(video_path),
                backend=f"{op}:video",
                model=op,
                license=LICENSE_COMMERCIAL_OK,
                metrics={"frames": len(processed), "fps": fps},
            ).to_dict()
        ],
        notes,
    )


__all__ = [
    "EnhanceConfigError",
    "EnhanceUnavailable",
    "enhance_media_workflow",
]
