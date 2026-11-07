"""Scroll-film engine (``video.scroll_film_engine``).

Clean-room rewrite of the *scroll-film method* described in
``hevi-vs-open-3d-skills.md`` sections 2.2 and 5 (item B3): a pinned
canvas engine driven by ``[progress, frame]`` keys, where the same
frame at two progress values is a hold; a frame sequence or a
scrub-ready video with a 4-frame GOP and no B-frames; seam scores
measured at leg boundaries and judged by ``qa.seam_loop_vocabulary``;
loop first/last-frame agreement measured, never assumed. No script,
starter, or demo text from the source repository is copied here:
every line is newly written, reusing only hevi's own harness
(ffmpeg assembly, ``qa.seam_loop_vocabulary``).

Delivery discipline, stated plainly:

- The engine always assembles with a 4-frame GOP and zero B-frames
  (``-g 4 -bf 0``). A plan that declares any other GOP fails.
- Scrub-video delivery requires a Range-answering server
  (``range_server: true`` in the plan); a plain static server that
  ignores Range would scrub on the first frame only. Frame-sequence
  delivery needs no server.
- Seam and loop thresholds are caller-supplied. This module has no
  default seam numbers: the author's reported ``<4`` / ``>10``
  figures are never used as thresholds.
- Determinism is measured on frame PNG hashes, never on the mp4
  container: ffmpeg container metadata is not stable across runs,
  so the mp4 is a delivery artefact, not determinism evidence.
- The bundled test-frame builder produces *synthetic* frames
  (PIL gradients and a disc). Shared boundary frames make leg
  seams measure zero by construction; that is a continuity
  fixture, declared as such, not evidence about real footage.
  The ``boundary_cut`` variant exists precisely to prove the seam
  scorer can see a real jump.

Failure contract: a malformed plan (not a JSON object) raises
:class:`CapabilityError`. A well-formed plan that violates the
engine discipline returns ``verdict: "fail"`` with named issues.
A render over missing frame files raises :class:`CapabilityError`
-- the engine never invents frames.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)
from hevi.capabilities.seam_loop_vocabulary import check_seam_loop_scores

_Registered = False

_REQUIRED_GOP = 4


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {"code": code, "message": message}
    issue.update(extra)
    return issue


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_scroll_plan(plan: Any) -> dict[str, Any]:
    """Validate one scroll-film plan against the engine discipline."""
    if not isinstance(plan, dict):
        raise CapabilityError("video.scroll_film_engine: plan must be a JSON object")
    issues: list[dict[str, Any]] = []

    legs = plan.get("legs")
    if not isinstance(legs, list) or not legs:
        issues.append(
            _issue(
                "legs_missing",
                "legs must be a non-empty list of {id, frames} entries",
            )
        )
        legs = []
    total_frames = 0
    for pos, leg in enumerate(legs):
        if not isinstance(leg, dict):
            issues.append(_issue("leg_not_object", f"leg {pos} must be an object"))
            continue
        if not isinstance(leg.get("id"), str) or not leg["id"].strip():
            issues.append(_issue("leg_id_missing", f"leg {pos} requires a non-empty id"))
        frames = leg.get("frames")
        if not isinstance(frames, list) or not frames:
            issues.append(
                _issue(
                    "leg_frames_missing",
                    f"leg {leg.get('id', pos)!r} requires a non-empty frames list",
                )
            )
            continue
        for frame in frames:
            if not isinstance(frame, str) or not frame.strip():
                issues.append(
                    _issue(
                        "leg_frame_not_path",
                        f"leg {leg.get('id', pos)!r} frame entries must be paths",
                    )
                )
        total_frames += len(frames)

    keys = plan.get("keys")
    if not isinstance(keys, list) or len(keys) < 2:
        issues.append(
            _issue(
                "keys_missing",
                "keys must be a list of at least two [progress, frame] pairs",
            )
        )
        keys = []
    prev_progress: float | None = None
    for pos, key in enumerate(keys):
        if not isinstance(key, (list, tuple)) or len(key) != 2:
            issues.append(
                _issue("key_malformed", f"key {pos} must be [progress, frame]")
            )
            continue
        progress, frame_idx = key
        if not _is_num(progress) or not 0.0 <= float(progress) <= 1.0:
            issues.append(
                _issue(
                    "key_progress_range",
                    f"key {pos} progress must be in [0, 1]",
                    key=pos,
                )
            )
        if not _is_int(frame_idx) or not 0 <= int(frame_idx) < max(total_frames, 1):
            issues.append(
                _issue(
                    "key_frame_range",
                    f"key {pos} frame index must be within the concatenated "
                    "leg frame list",
                    key=pos,
                )
            )
        if prev_progress is not None and float(progress) < prev_progress:
            issues.append(
                _issue(
                    "keys_not_monotonic",
                    "key progress values must be non-decreasing; a hold is "
                    "the same frame at two progress values",
                    key=pos,
                )
            )
        prev_progress = float(progress) if _is_num(progress) else prev_progress
    if keys:
        first = keys[0]
        last = keys[-1]
        if isinstance(first, (list, tuple)) and _is_num(first[0]) and float(first[0]) != 0.0:
            issues.append(
                _issue("keys_must_start_at_zero", "first key progress must be 0.0")
            )
        if isinstance(last, (list, tuple)) and _is_num(last[0]) and float(last[0]) != 1.0:
            issues.append(
                _issue("keys_must_end_at_one", "last key progress must be 1.0")
            )

    smooth = plan.get("smooth", 0.0)
    if not _is_num(smooth) or not 0.0 <= float(smooth) <= 1.0:
        issues.append(
            _issue("smooth_range", "smooth must be a number in [0, 1]", smooth=smooth)
        )

    output_frames = plan.get("output_frames")
    if not _is_int(output_frames) or int(output_frames) < 2:
        issues.append(
            _issue(
                "output_frames_invalid",
                "output_frames must be an integer >= 2",
            )
        )

    fps = plan.get("fps", 30)
    if not _is_num(fps) or float(fps) <= 0:
        issues.append(_issue("fps_invalid", "fps must be a positive number"))

    gop = plan.get("gop", _REQUIRED_GOP)
    if gop != _REQUIRED_GOP:
        issues.append(
            _issue(
                "gop_must_be_four",
                f"scroll-film delivery uses a {_REQUIRED_GOP}-frame GOP; "
                f"a plan declaring gop={gop!r} fails",
                gop=gop,
            )
        )

    delivery = plan.get("delivery", "frames")
    if delivery not in ("frames", "scrub_video"):
        issues.append(
            _issue(
                "delivery_unknown",
                "delivery must be 'frames' or 'scrub_video'",
                delivery=delivery,
            )
        )
    if delivery == "scrub_video" and plan.get("range_server") is not True:
        issues.append(
            _issue(
                "range_server_required",
                "scrub_video delivery requires range_server: true; a plain "
                "static server that ignores Range scrubs on the first frame",
            )
        )

    loop = plan.get("loop", False)
    if not isinstance(loop, bool):
        issues.append(
            _issue("loop_not_boolean", "loop must be a boolean when present")
        )

    thresholds = plan.get("thresholds")
    if not isinstance(thresholds, dict) or not thresholds:
        issues.append(
            _issue(
                "thresholds_missing",
                "thresholds must be supplied by the caller for the seam/loop "
                "gate; this engine has no default seam numbers",
            )
        )

    verdict = "pass" if not issues else "fail"
    return {
        "verdict": verdict,
        "ok": verdict == "pass",
        "issues": issues,
        "total_frames": total_frames,
        "gop": _REQUIRED_GOP,
        "delivery": delivery,
    }


def measure_seam(frame_a: Any, frame_b: Any) -> float:
    """Mean absolute per-channel difference, normalised to [0, 1].

    Identical frames score exactly 0.0. Inputs are numpy arrays of
    identical shape; anything else raises :class:`CapabilityError`.
    """
    import numpy as np

    if not isinstance(frame_a, np.ndarray) or not isinstance(frame_b, np.ndarray):
        raise CapabilityError("measure_seam: both frames must be numpy arrays")
    if frame_a.shape != frame_b.shape:
        raise CapabilityError(
            f"measure_seam: frame shapes differ: {frame_a.shape} vs {frame_b.shape}"
        )
    if frame_a.size == 0:
        raise CapabilityError("measure_seam: frames must not be empty")
    diff = np.abs(frame_a.astype(np.float32) - frame_b.astype(np.float32))
    return float(diff.mean() / 255.0)


def _load_frame(path: Path) -> Any:
    import cv2

    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise CapabilityError(f"scroll-film engine: cannot read frame {path}")
    return frame


def _key_positions(keys: list[list[Any]], output_frames: int, smooth: float) -> list[int]:
    """Map each output frame to a source frame index via the keys.

    Piecewise-linear interpolation of the key positions, with an
    optional centred moving-average smoothing pass (window width
    ``round(smooth * 4)`` frames, endpoints pinned). A hold -- the
    same source frame at two progress values -- stays constant
    across its segment by construction.
    """
    import numpy as np

    progress = np.array([float(k[0]) for k in keys], dtype=np.float64)
    frames = np.array([float(k[1]) for k in keys], dtype=np.float64)
    targets = np.linspace(0.0, 1.0, output_frames)
    positions = np.interp(targets, progress, frames)
    width = int(round(float(smooth) * 4))
    if width >= 2:
        kernel = np.ones(width, dtype=np.float64) / width
        smoothed = np.convolve(positions, kernel, mode="same")
        smoothed[0] = positions[0]
        smoothed[-1] = positions[-1]
        positions = smoothed
    return [int(round(p)) for p in positions]


def _encode_mp4(frames_dir: Path, *, fps: float, out_path: Path) -> None:
    if shutil.which("ffmpeg") is None:
        raise CapabilityError("scroll-film engine: ffmpeg is required but not on PATH")
    command = [
        "ffmpeg",
        "-y",
        "-threads",
        "1",
        "-framerate",
        str(fps),
        "-i",
        str(frames_dir / "frame_%04d.png"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(_REQUIRED_GOP),
        "-bf",
        "0",
        str(out_path),
    ]
    proc = subprocess.run(command, capture_output=True, text=True)
    if proc.returncode != 0 or not out_path.exists():
        raise CapabilityError(
            "scroll-film engine: ffmpeg assembly failed: " + proc.stderr[-500:]
        )


def render_scroll_film(plan: Any, out_dir: Any) -> dict[str, Any]:
    """Render one scroll film from a validated plan.

    Reads the leg frames, selects output frames through the keys,
    writes the output PNG sequence, assembles the mp4, measures
    leg-boundary seams and the loop score on the *output* frames,
    and judges them through ``qa.seam_loop_vocabulary`` with the
    caller-supplied thresholds. Returns the report dict; the mp4
    path, frame hashes, and seam table are inside it.
    """
    checked = check_scroll_plan(plan)
    if checked["verdict"] != "pass":
        return {**checked, "rendered": False}
    if shutil.which("ffmpeg") is None:
        raise CapabilityError("scroll-film engine: ffmpeg is required but not on PATH")

    legs = plan["legs"]
    ordered_paths: list[Path] = []
    leg_of_source: list[str] = []
    for leg in legs:
        for frame in leg["frames"]:
            path = Path(frame)
            if not path.exists():
                raise CapabilityError(
                    f"scroll-film engine: leg frame does not exist: {path}"
                )
            ordered_paths.append(path)
            leg_of_source.append(str(leg["id"]))

    out_root = Path(out_dir)
    frames_dir = out_root / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    positions = _key_positions(
        plan["keys"], int(plan["output_frames"]), float(plan.get("smooth", 0.0))
    )
    output_frames: list[Any] = []
    frame_hashes: list[str] = []
    for idx, src_idx in enumerate(positions):
        frame = _load_frame(ordered_paths[src_idx])
        output_frames.append(frame)
        target = frames_dir / f"frame_{idx:04d}.png"
        if not _write_png(target, frame):
            raise CapabilityError(f"scroll-film engine: cannot write {target}")
        frame_hashes.append(_sha256_file(target))

    mp4_path = out_root / "scroll_film.mp4"
    _encode_mp4(frames_dir, fps=float(plan.get("fps", 30)), out_path=mp4_path)

    # Seam scores at output indices where the source leg changes.
    seam_scores: list[dict[str, Any]] = []
    for idx in range(1, len(positions)):
        if leg_of_source[positions[idx]] != leg_of_source[positions[idx - 1]]:
            seam_scores.append(
                {
                    "output_index": idx,
                    "from_leg": leg_of_source[positions[idx - 1]],
                    "to_leg": leg_of_source[positions[idx]],
                    "score": measure_seam(output_frames[idx - 1], output_frames[idx]),
                }
            )
    loop_score = measure_seam(output_frames[0], output_frames[-1])
    gate_input = {
        "thresholds": plan["thresholds"],
        "seam_scores": [entry["score"] for entry in seam_scores],
        "loop": {"jump": loop_score},
    }
    gate = check_seam_loop_scores(gate_input)
    # The loop jump is judged only when the plan declares a loop.
    # Otherwise the first/last difference is measured and reported
    # but never judged: a non-loop film is not a failed loop.
    loop_judged = bool(plan.get("loop", False))
    non_loop_issues = [
        issue for issue in gate["issues"] if issue["code"] != "loop_jump_too_large"
    ]
    verdict = gate["verdict"]
    if not loop_judged:
        verdict = "fail" if non_loop_issues else "pass"

    report = {
        "rendered": True,
        "verdict": verdict,
        "ok": verdict == "pass",
        "loop_judged": loop_judged,
        "mp4": str(mp4_path),
        "mp4_sha256": compute_sha256(mp4_path),
        "frames_dir": str(frames_dir),
        "frame_count": len(output_frames),
        "frame_hashes": frame_hashes,
        "source_positions": positions,
        "seam_scores": seam_scores,
        "loop_score": loop_score,
        "gate": gate,
        "delivery": plan.get("delivery", "frames"),
        "gop": _REQUIRED_GOP,
        "synthetic_source": bool(plan.get("synthetic_source", False)),
    }
    report_path = out_root / "scroll_film_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_json"] = str(report_path)
    return report


def _write_png(path: Path, bgr_frame: Any) -> bool:
    import cv2

    return bool(cv2.imwrite(str(path), bgr_frame))


def build_test_frames(
    out_dir: Any,
    *,
    width: int = 320,
    height: int = 180,
    leg_frame_counts: Any = (12, 12, 12),
    boundary_cut: bool = False,
) -> dict[str, Any]:
    """Build a deterministic synthetic 3-leg frame set (PIL only).

    One continuous scene function is sampled across all legs; the
    boundary frame is shared between neighbouring legs, so leg
    seams measure zero by construction. With ``boundary_cut`` the
    disc restarts at the left edge of each leg, so each boundary
    is a visible jump -- the negative control. Frames are
    synthetic and labelled as such; they prove the engine and the
    scorer, not anything about real footage.
    """
    from PIL import Image, ImageDraw

    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    total = sum(int(c) for c in leg_frame_counts)
    frames: list[Image.Image] = []
    for t in range(total):
        img = Image.new("RGB", (width, height))
        draw = ImageDraw.Draw(img)
        for y in range(height):
            shade = int(30 + 120 * y / max(height - 1, 1))
            draw.line([(0, y), (width, y)], fill=(shade, 90, 160))
        x = int(20 + (width - 40) * (t / max(total - 1, 1)))
        y = height // 2
        draw.ellipse([x - 18, y - 18, x + 18, y + 18], fill=(240, 200, 60))
        draw.rectangle([x - 4, y - 4, x + 4, y + 4], fill=(20, 20, 20))
        frames.append(img)

    legs: list[dict[str, Any]] = []
    cursor = 0
    for leg_no, count in enumerate(leg_frame_counts):
        leg_dir = root / f"leg{leg_no + 1}"
        leg_dir.mkdir(parents=True, exist_ok=True)
        paths: list[str] = []
        for j in range(int(count)):
            if boundary_cut and j == 0 and leg_no > 0:
                frame = frames[0]
            elif j == 0 and leg_no > 0:
                # Shared boundary frame: identical bytes to the
                # previous leg's last frame, so the seam is 0.
                frame = frames[cursor - 1]
            else:
                frame = frames[cursor]
                cursor += 1
            path = leg_dir / f"frame_{j:04d}.png"
            frame.save(path)
            paths.append(str(path))
        legs.append({"id": f"leg{leg_no + 1}", "frames": paths})
    return {
        "legs": legs,
        "total_frames": total,
        "synthetic": True,
        "boundary_cut": boundary_cut,
        "width": width,
        "height": height,
    }


def _render(params: dict[str, Any], out_dir: Path, *, duration: float, aspect: str, seed: int) -> CapabilityResult:
    plan = params.get("plan", params)
    report = render_scroll_film(plan, out_dir)
    report_path = Path(out_dir) / "scroll_film_report.json"
    return CapabilityResult(
        mp4=report.get("mp4"),
        duration_s=float(params.get("duration_s", 0.0))
        or (len(report.get("frame_hashes", [])) / float(plan.get("fps", 30)))
        if report.get("rendered")
        else 0.0,
        sha256=report.get("mp4_sha256", ""),
        qa={"report_json": str(report_path), "verdict": report.get("verdict"), "ok": report.get("ok", False)},
    )


def register_scroll_film_engine_capabilities_once() -> list[str]:
    global _Registered
    if _Registered:
        return []
    _Registered = True
    register(
        Capability(
            name="video.scroll_film_engine",
            kind="line",
            aspects=["16:9", "9:16", "1:1"],
            params_schema={
                "type": "object",
                "properties": {
                    "plan": {"type": "object"},
                    "legs": {"type": "array"},
                    "keys": {"type": "array"},
                    "smooth": {"type": "number"},
                    "output_frames": {"type": "integer"},
                    "fps": {"type": "number"},
                    "gop": {"type": "integer"},
                    "delivery": {"type": "string"},
                    "range_server": {"type": "boolean"},
                    "thresholds": {"type": "object"},
                    "duration_s": {"type": "number"},
                },
                "additionalProperties": False,
            },
            cpu_cost_hint=0.0,
            render=_render,
            has_media_output=True,
            description=(
                "Scroll-film engine (clean-room rewrite of the "
                "open-3d-skills scroll-film method; see "
                "OPEN_3D_SKILLS_ATTRIBUTION.md): keys-driven frame "
                "selection, 4-frame GOP, no B-frames, seam and loop "
                "scores judged by qa.seam_loop_vocabulary with "
                "caller-supplied thresholds."
            ),
        )
    )
    return ["video.scroll_film_engine"]
