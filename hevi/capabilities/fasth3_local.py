"""Local FastH3 Reference-to-Video capability (ComfyUI on ubuntu26).

Registers one ``hevi.capabilities`` entry:

* ``video.fasth3_local`` — reference image + prompt -> MP4 through the
  local ComfyUI service (MiniMax FastH3, INT8 weights, low-VRAM mode),
  submitted over the ComfyUI HTTP API, polled via /history, and
  downloaded via /view.  No paid calls: everything runs on the local
  RTX 3080.

Workflow node graph (do not redesign it): this is exactly the graph in
``/data/soffy/fasth3-comfy/workflow_test.json`` that produced the
verified test clip ``ComfyUI/output/fasth3_test_00001_.mp4``
(1024x576, 5.167s, H.264 + AAC, ~213.8s wall, ~9854 MiB peak on the
10 GiB card, 2026-10-25).  The one early failure of that graph is
worth remembering: passing the reference as a flat ``ref_image_1``
input to MiniMaxH3ReferenceToVideo raises
``got an unexpected keyword argument 'ref_image_1'``; the working
shape is the ``ref_images`` dict ``{"ref_image_1": ["1", 0]}``.

Locked official values (never tuned per call):
steps=8, guidance (cfg)=1.0, video shift=12.0, audio shift=3.0,
INT8 diffusion + INT8 encoder + INT8 video VAE + FP32 audio VAE,
1024x576 at 24 fps, euler/simple sampler, low-VRAM ComfyUI server.

Duration contract: the caller requests 5-15 s (the trained interval;
the node tooltip says ~124-362 frames).  Anything outside raises
``CapabilityError`` before any GPU work is submitted.  Frames are
``max(124, round(duration * 24))`` because 124 frames is the trained
floor even for a nominal 5 s request (124/24 = 5.167 s actual).

Failure policy (CAPABILITY_CONTRACT.md): a missing reference file, a
missing GPU (nvidia-smi failure), an unreachable ComfyUI, a ComfyUI
execution error, a missing output, or a probe mismatch all raise
``CapabilityError``.  A ComfyUI execution error is re-raised WITH the
raw ComfyUI error text (node id, exception type and message), never
swallowed or paraphrased into a generic message.  No fake success.

VRAM: peak GPU memory is sampled from ``nvidia-smi`` on every poll
iteration during generation and reported in ``qa["peak_vram_mib"]``.

Verified on ubuntu26, 2026-10-26 (do not claim more):
* Real 5 s clip through this capability (see tests/test_fasth3_local.py,
  gated on HEVI_FASTH3_REAL_TEST=1): reference
  ``ComfyUI/input/ref_school.jpg``, 124 frames, output probed after
  download.  Exact numbers are in the test run log, not asserted here,
  because wall time and peak VRAM vary with what else holds the card.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from hevi.capabilities.errors import CapabilityError
from hevi.capabilities.registry import (
    Capability,
    CapabilityResult,
    compute_sha256,
    register,
)

_Registered = False

DEFAULT_BASE_URL = "http://127.0.0.1:8188"
FPS = 24
WIDTH, HEIGHT = 1024, 576
STEPS = 8
CFG = 1.0
SHIFT_VIDEO = 12.0
SHIFT_AUDIO = 3.0
MIN_DURATION_S = 5.0
MAX_DURATION_S = 15.0
MIN_FRAMES = 124
MAX_FRAMES = 360
DEFAULT_SEED = 777
SAMPLER = "euler"
SCHEDULER = "simple"

UNET_NAME = "fasth3_omniref_8step_pruned_int8_convrot.safetensors"
CLIP_NAME = "qwen3vl_32b_minimax_h3_int8_convrot.safetensors"
VIDEO_VAE_NAME = "minimax_h3_video_vae_int8_convrot.safetensors"
AUDIO_VAE_NAME = "minimax_h3_audio_vae_fp32.safetensors"

_DESCRIPTION = (
    "Local FastH3 Reference-to-Video via the ubuntu26 ComfyUI service "
    "(http://127.0.0.1:8188, low-VRAM): reference image + prompt -> "
    "1024x576 MP4 with generated audio. Locked to the official values: "
    "8 steps, guidance 1.0, video shift 12.0, audio shift 3.0, INT8 "
    "diffusion/encoder/video-VAE + FP32 audio VAE. Duration must be "
    "5-15 s (trained interval); out-of-range requests are refused "
    "before submission. Local and free: no paid calls. Wall time is "
    "roughly 40 s per output second on the RTX 3080, so keep shots "
    "short and queue them; ComfyUI failures surface verbatim."
)


def build_workflow(ref_name: str, prompt: str, frames: int, seed: int,
                   filename_prefix: str) -> dict[str, Any]:
    """Build the exact workflow_test.json node graph with params filled in."""
    if not ref_name or not str(ref_name).strip():
        raise CapabilityError("video.fasth3_local needs a reference image name")
    if not prompt or not str(prompt).strip():
        raise CapabilityError("video.fasth3_local needs a non-empty prompt")
    if frames < MIN_FRAMES or frames > MAX_FRAMES:
        raise CapabilityError(
            f"frame count must be in [{MIN_FRAMES}, {MAX_FRAMES}], got {frames}")
    return {
        "1": {"class_type": "LoadImage", "inputs": {"image": ref_name}},
        "2": {"class_type": "UNETLoader",
              "inputs": {"unet_name": UNET_NAME, "weight_dtype": "default"}},
        "3": {"class_type": "CLIPLoader",
              "inputs": {"clip_name": CLIP_NAME, "device": "default",
                         "type": "minimax"}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE_NAME}},
        "5": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE_NAME}},
        "6": {"class_type": "MiniMaxH3ReferenceToVideo",
              "inputs": {
                  "audio_vae": ["5", 0], "clip": ["3", 0],
                  "height": HEIGHT, "length": frames, "prompt": prompt,
                  "ref_images": {"ref_image_1": ["1", 0]},
                  "ref_image_size": "match", "vae": ["4", 0],
                  "width": WIDTH}},
        "7": {"class_type": "MiniMaxH3SigmaShift",
              "inputs": {"model": ["2", 0], "shift_audio": SHIFT_AUDIO,
                         "shift_video": SHIFT_VIDEO}},
        "8": {"class_type": "CLIPTextEncode",
              "inputs": {"clip": ["3", 0], "text": ""}},
        "9": {"class_type": "KSampler",
              "inputs": {"cfg": CFG, "denoise": 1.0,
                         "latent_image": ["6", 1], "model": ["7", 0],
                         "negative": ["8", 0], "positive": ["6", 0],
                         "sampler_name": SAMPLER, "scheduler": SCHEDULER,
                         "seed": seed, "steps": STEPS}},
        "10": {"class_type": "VAEDecode",
               "inputs": {"samples": ["9", 0], "vae": ["4", 0]}},
        "11": {"class_type": "VAEDecodeAudio",
               "inputs": {"samples": ["9", 0], "vae": ["5", 0]}},
        "12": {"class_type": "CreateVideo",
               "inputs": {"audio": ["11", 0], "fps": FPS, "images": ["10", 0]}},
        "13": {"class_type": "SaveVideo",
               "inputs": {"codec": "h264", "filename_prefix": filename_prefix,
                          "format": "mp4", "video": ["12", 0]}},
    }


def _http_json(base_url: str, path: str, payload: dict | None = None,
                timeout: float = 60.0) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        base_url.rstrip("/") + path, data=data,
        headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:2000]
        raise CapabilityError(
            f"video.fasth3_local: ComfyUI HTTP {exc.code} on {path}: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise CapabilityError(
            f"video.fasth3_local: cannot reach ComfyUI at {base_url} "
            f"({path}): {exc.reason}"
        ) from exc


def _upload_image(base_url: str, ref_path: Path) -> str:
    """Upload the reference image via /upload/image; return its server name."""
    import uuid

    boundary = "----fasth3" + uuid.uuid4().hex
    data = ref_path.read_bytes()
    body = (
        ("--" + boundary + "\r\nContent-Disposition: form-data; "
         "name=\"image\"; filename=\"" + ref_path.name + "\"\r\n"
         "Content-Type: application/octet-stream\r\n\r\n").encode()
        + data + b"\r\n"
        + ("--" + boundary + "\r\nContent-Disposition: form-data; "
           "name=\"overwrite\"\r\n\r\ntrue\r\n").encode()
        + ("--" + boundary + "--\r\n").encode()
    )
    req = urllib.request.Request(
        base_url.rstrip("/") + "/upload/image", data=body,
        headers={"Content-Type": "multipart/form-data; boundary=" + boundary})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:2000]
        raise CapabilityError(
            f"video.fasth3_local: image upload failed HTTP {exc.code}: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise CapabilityError(
            f"video.fasth3_local: cannot reach ComfyUI at {base_url} "
            f"for upload: {exc.reason}"
        ) from exc
    name = payload.get("name")
    if not name:
        raise CapabilityError(
            f"video.fasth3_local: upload returned no name: {payload}")
    return str(name)


def _check_gpu() -> int:
    """Return current used MiB, or raise if nvidia-smi / the card is gone."""
    try:
        proc = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=30, check=True)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise CapabilityError(
            f"video.fasth3_local: nvidia-smi failed, GPU not usable: {exc}"
        ) from exc
    try:
        return int(proc.stdout.strip().splitlines()[0].strip())
    except (ValueError, IndexError) as exc:
        raise CapabilityError(
            f"video.fasth3_local: cannot parse nvidia-smi output: "
            f"{proc.stdout!r}"
        ) from exc


def _sample_vram() -> int | None:
    try:
        return _check_gpu()
    except CapabilityError:
        return None


def _poll_history(base_url: str, prompt_id: str, timeout_s: float,
                  poll_interval_s: float = 10.0) -> tuple[dict[str, Any], float, int | None]:
    """Poll /history until completion; return (outputs, elapsed_s, peak_mib).

    A ComfyUI execution error raises CapabilityError carrying the raw
    history text, so the caller sees the original node id, exception
    type and message.
    """
    t0 = time.time()
    peak: int | None = None
    while True:
        sample = _sample_vram()
        if sample is not None:
            peak = sample if peak is None else max(peak, sample)
        hist = _http_json(base_url, "/history/" + prompt_id)
        if prompt_id in hist:
            entry = hist[prompt_id]
            status = entry.get("status", {})
            if status.get("completed"):
                return entry.get("outputs", {}), time.time() - t0, peak
            if status.get("status_str") == "error":
                raise CapabilityError(
                    "video.fasth3_local: ComfyUI execution error (raw history): "
                    + json.dumps(entry, indent=2)[:4000])
            messages = status.get("messages", [])
            if any(isinstance(m, list) and m and m[0] == "execution_error"
                   for m in messages):
                raise CapabilityError(
                    "video.fasth3_local: ComfyUI execution error (raw history): "
                    + json.dumps(entry, indent=2)[:4000])
        if time.time() - t0 > timeout_s:
            raise CapabilityError(
                f"video.fasth3_local: timed out after {timeout_s}s waiting "
                f"for prompt {prompt_id}")
        time.sleep(poll_interval_s)


def _download_output(base_url: str, outputs: dict[str, Any],
                     dest: Path) -> Path:
    node = outputs.get("13") or {}
    images = node.get("images") or []
    if not images:
        raise CapabilityError(
            f"video.fasth3_local: no SaveVideo output in ComfyUI history: "
            f"{json.dumps(outputs)[:2000]}")
    item = images[0]
    query = urllib.parse.urlencode({
        "filename": item["filename"],
        "subfolder": item.get("subfolder", ""),
        "type": item.get("type", "output"),
    })
    try:
        with urllib.request.urlopen(
                base_url.rstrip("/") + "/view?" + query, timeout=300) as resp:
            dest.write_bytes(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:2000]
        raise CapabilityError(
            f"video.fasth3_local: download failed HTTP {exc.code}: {body}"
        ) from exc
    except urllib.error.URLError as exc:
        raise CapabilityError(
            f"video.fasth3_local: download failed, cannot reach {base_url}: "
            f"{exc.reason}"
        ) from exc
    if dest.stat().st_size == 0:
        raise CapabilityError(f"video.fasth3_local: downloaded empty file {dest}")
    return dest


def _probe_mp4(path: Path) -> dict[str, Any]:
    ffmpeg_probe = shutil.which("ffprobe")
    if ffmpeg_probe is None:
        raise CapabilityError("video.fasth3_local: ffprobe not found")
    proc = subprocess.run(
        [ffmpeg_probe, "-v", "error", "-show_entries",
         "format=duration:stream=codec_name,codec_type,width,height",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise CapabilityError(
            f"video.fasth3_local: ffprobe failed on {path}: "
            f"{proc.stderr.strip()[-1000:]}")
    probe = json.loads(proc.stdout)
    streams = probe.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise CapabilityError(f"video.fasth3_local: no video stream in {path}")
    if audio is None:
        raise CapabilityError(f"video.fasth3_local: no audio stream in {path}")
    return {
        "duration_s": float(probe.get("format", {}).get("duration", 0.0)),
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name"),
    }


def render(params: dict, out_dir: str | Path, *, duration: float,
           aspect: str, seed: int = 0) -> CapabilityResult:
    """Render params['reference_image'] + params['prompt'] to an MP4."""
    reference = params.get("reference_image", "")
    prompt = params.get("prompt", "")
    if not isinstance(reference, str) or not reference.strip():
        raise CapabilityError("video.fasth3_local needs params['reference_image']")
    if not isinstance(prompt, str) or not prompt.strip():
        raise CapabilityError("video.fasth3_local needs params['prompt']")
    ref_path = Path(reference)
    if not ref_path.exists():
        raise CapabilityError(
            f"video.fasth3_local: reference image not found: {reference}")
    if aspect != "16:9":
        raise CapabilityError(
            f"video.fasth3_local only supports 16:9, got {aspect!r}")
    effective = params.get("duration_s", duration)
    try:
        effective = float(effective)
    except (TypeError, ValueError) as exc:
        raise CapabilityError(
            f"video.fasth3_local: bad duration {effective!r}") from exc
    if effective < MIN_DURATION_S or effective > MAX_DURATION_S:
        raise CapabilityError(
            f"video.fasth3_local: duration {effective}s outside trained "
            f"interval [{MIN_DURATION_S}, {MAX_DURATION_S}]s; refused "
            f"before submission")
    frames = max(MIN_FRAMES, int(round(effective * FPS)))
    if frames > MAX_FRAMES:
        raise CapabilityError(
            f"video.fasth3_local: {frames} frames exceeds trained max "
            f"{MAX_FRAMES}")
    eff_seed = int(params.get("seed", seed) or DEFAULT_SEED)
    base_url = str(params.get("base_url", DEFAULT_BASE_URL))
    prefix = str(params.get("filename_prefix", "fasth3_local"))
    timeout_s = float(params.get("poll_timeout_s", 3600))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    _check_gpu()
    ref_name = _upload_image(base_url, ref_path)
    workflow = build_workflow(ref_name, prompt, frames, eff_seed, prefix)
    (out / "fasth3_workflow.json").write_text(
        json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")
    resp = _http_json(base_url, "/prompt", {"prompt": workflow})
    prompt_id = resp.get("prompt_id")
    if not prompt_id:
        raise CapabilityError(
            f"video.fasth3_local: /prompt returned no prompt_id: {resp}")
    outputs, elapsed_s, peak_mib = _poll_history(
        base_url, prompt_id, timeout_s)
    mp4_path = out / (prefix + ".mp4")
    _download_output(base_url, outputs, mp4_path)
    probe = _probe_mp4(mp4_path)
    if probe["width"] != WIDTH or probe["height"] != HEIGHT:
        raise CapabilityError(
            f"video.fasth3_local: probe mismatch on {mp4_path}: {probe} "
            f"(expected {WIDTH}x{HEIGHT})")
    if abs(probe["duration_s"] - frames / FPS) > 0.6:
        raise CapabilityError(
            f"video.fasth3_local: duration mismatch: probe "
            f"{probe['duration_s']}s vs {frames / FPS}s from {frames} frames")
    meta = {
        "prompt_id": prompt_id, "base_url": base_url,
        "reference_image": str(ref_path), "uploaded_ref_name": ref_name,
        "prompt": prompt, "requested_duration_s": effective,
        "frames": frames, "seed": eff_seed, "steps": STEPS, "cfg": CFG,
        "shift_video": SHIFT_VIDEO, "shift_audio": SHIFT_AUDIO,
        "unet": UNET_NAME, "clip": CLIP_NAME,
        "video_vae": VIDEO_VAE_NAME, "audio_vae": AUDIO_VAE_NAME,
        "elapsed_s": round(elapsed_s, 1), "peak_vram_mib": peak_mib,
        "probe": probe,
    }
    (out / "fasth3_meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return CapabilityResult(
        mp4=str(mp4_path), duration_s=probe["duration_s"],
        sha256=compute_sha256(mp4_path),
        qa=meta,
    )


def register_fasth3_local_capabilities_once() -> None:
    global _Registered
    if _Registered:
        return
    register(
        Capability(
            name="video.fasth3_local",
            kind="shot",
            aspects=["16:9"],
            params_schema={
                "type": "object",
                "properties": {
                    "reference_image": {
                        "type": "string",
                        "description": "Local path to the reference still; "
                        "uploaded to ComfyUI /upload/image before submission.",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Reference-to-Video prompt, starting "
                        "with '<Picture 1>' per ComfyUI convention.",
                    },
                    "base_url": {
                        "type": "string", "default": DEFAULT_BASE_URL,
                        "description": "ComfyUI base URL (same host as hevi).",
                    },
                    "filename_prefix": {
                        "type": "string", "default": "fasth3_local",
                    },
                    "seed": {"type": "integer", "default": DEFAULT_SEED},
                    "duration_s": {
                        "type": "number",
                        "description": "Optional override of the render "
                        "duration argument; still validated 5-15 s.",
                    },
                    "poll_timeout_s": {
                        "type": "number", "default": 3600,
                    },
                },
                "required": ["reference_image", "prompt"],
                "additionalProperties": False,
            },
            cpu_cost_hint=41.0,
            render=render,
            description=_DESCRIPTION,
            line="fasth3-local",
        )
    )
    _Registered = True


register_fasth3_local_capabilities_once()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference-image", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--prefix", default="fasth3_local")
    args = ap.parse_args(argv)
    result = render(
        {"reference_image": args.reference_image, "prompt": args.prompt,
         "base_url": args.base_url, "filename_prefix": args.prefix},
        args.out, duration=args.duration, aspect="16:9", seed=args.seed)
    print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
