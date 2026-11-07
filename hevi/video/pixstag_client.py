"""PixStag REST client for hevi providers (stdlib only).

PixStag (https://pixstag.com) hosts MiniMax-H3 / doubao-seedance models behind
a unified v2 video API. Auth: ``PIXSTAG_API_KEY`` env (``Authorization: Bearer``,
per https://pixstag.com/docs/api curl examples). Base: ``PIXSTAG_API_BASE`` env,
default ``https://pixstag.com``. Never logs the key.

Endpoints:
  POST /api/v2/video_generation          -> {task_id}
  GET  /api/v2/query/video_generation/{task_id} -> {task: {...status, content, usage...}}
  GET  /api/v2/user/me                   -> {user_id, credit, credit_frozen, credit_valid_time}

Pricing (2026-10-20, from docs/pricing): 720P = 1 credit/second; MiniMax-H3
approx $0.015/second. Credits expire (~31 days), so callers should report
``me()`` balance and expiry alongside generation results.
"""

from __future__ import annotations

import base64
import datetime as _dt
import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TERMINAL_SUCCESS = "succeeded"
_TERMINAL_FAILURE = {"failed", "cancelled"}

MODELS = ("MiniMax-H3", "doubao-seedance-2", "doubao-seedance-2-5")
RATIOS = ("adaptive", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16")
RESOLUTIONS = ("720P", "768P", "1080P", "2K")
DURATION_MIN, DURATION_MAX = 4, 30
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
IMAGE_MAX_BYTES = 3 * 1024 * 1024  # docs: image/audio max 3M

_CREDITS_PER_SECOND = {"720P": 1.0}  # other resolutions not published
_USD_PER_SECOND = {"MiniMax-H3": 0.015}


class PixStagError(RuntimeError):
    """Raised when PixStag fails, is unreachable, or has no API key."""


def _api_base() -> str:
    return os.environ.get("PIXSTAG_API_BASE", "https://pixstag.com").rstrip("/")


def _api_key() -> str:
    key = os.environ.get("PIXSTAG_API_KEY", "").strip()
    if not key:
        raise PixStagError(
            "PIXSTAG_API_KEY is not set. Generate a key at https://pixstag.com "
            "(account page) and export PIXSTAG_API_KEY to use PixStag-backed providers."
        )
    return key


def _request_json(method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
    url = f"{_api_base()}{path}"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        if exc.code in (401, 403):
            raise PixStagError(
                f"PixStag authentication failed ({exc.code}): check PIXSTAG_API_KEY "
                f"against https://pixstag.com account page. Server said: {detail}"
            ) from exc
        raise PixStagError(
            f"PixStag API request failed ({method} {path}): HTTP {exc.code}: {detail}"
        ) from exc
    except Exception as exc:  # noqa: BLE001 - fail loud with context
        raise PixStagError(f"PixStag API request failed ({method} {path}): {exc}") from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PixStagError(f"PixStag returned non-JSON ({method} {path}): {body[:200]}") from exc
    if not isinstance(parsed, dict):
        raise PixStagError(f"PixStag returned unexpected shape ({method} {path})")
    return parsed


def create_video(body: dict[str, Any]) -> str:
    """Submit a generation job; return the task_id."""
    resp = _request_json("POST", "/api/v2/video_generation", body)
    task_id = resp.get("task_id")
    if not task_id:
        raise PixStagError(f"PixStag create_video returned no task_id: {str(resp)[:300]}")
    return str(task_id)


def query_task(task_id: str) -> dict[str, Any]:
    """Query one task. The API wraps the object in a ``task`` field."""
    resp = _request_json("GET", f"/api/v2/query/video_generation/{task_id}", None)
    task = resp.get("task")
    if isinstance(task, dict):
        return task
    return resp


def me() -> dict[str, Any]:
    """Current user info: credit, credit_frozen, credit_valid_time (unix ts)."""
    return _request_json("GET", "/api/v2/user/me", None)


def credit_expiry_iso(info: dict[str, Any]) -> str | None:
    ts = info.get("credit_valid_time")
    try:
        return _dt.datetime.fromtimestamp(int(ts), tz=_dt.timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def wait_task(
    task_id: str, *, timeout_s: float = 600.0, poll_interval_s: float = 5.0
) -> dict[str, Any]:
    """Poll until the task reaches a terminal state. Raises on failure/timeout."""
    deadline = time.monotonic() + timeout_s
    while True:
        task = query_task(task_id)
        status = str(task.get("status", ""))
        if status == _TERMINAL_SUCCESS:
            return task
        if status in _TERMINAL_FAILURE:
            err = task.get("error") or {}
            raise PixStagError(
                f"PixStag task {task_id} ended with status {status}: "
                f"code={err.get('code')} message={err.get('message')}"
            )
        if time.monotonic() >= deadline:
            raise PixStagError(
                f"PixStag task {task_id} did not finish within {timeout_s:.0f}s "
                f"(last status: {status})"
            )
        time.sleep(poll_interval_s)


def download_file(url: str, dest: Path, *, timeout_s: float = 120.0) -> Path:
    """Download a (time-limited) result URL to ``dest``. Presigned URL: no auth."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp, open(dest, "wb") as f:
            while chunk := resp.read(65536):
                f.write(chunk)
    except Exception as exc:  # noqa: BLE001
        raise PixStagError(f"PixStag result download failed: {exc}") from exc
    return dest


def encode_image(path: str | Path, *, data_uri: bool = False) -> str:
    """Read a local jpg/png (<=3MB) and return base64 for the image_url field.

    Docs: the ``url`` field of image_url accepts "url地址或base64信息".
    ``data_uri=True`` wraps it as ``data:image/<ext>;base64,...``; default is the
    raw base64 string, which is the literal reading of the docs. Flip the flag if
    the server ever rejects the raw form.
    """
    p = Path(path)
    if not p.is_file():
        raise PixStagError(f"image file not found: {p}")
    if p.suffix.lower() not in IMAGE_EXTENSIONS:
        raise PixStagError(f"image must be jpg/png for PixStag (got {p.suffix}): {p}")
    size = p.stat().st_size
    if size > IMAGE_MAX_BYTES:
        raise PixStagError(f"image exceeds 3MB for PixStag ({size} bytes): {p}")
    raw = base64.b64encode(p.read_bytes()).decode("ascii")
    if data_uri:
        mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        return f"data:{mime};base64,{raw}"
    return raw


def _image_entry(source: str | Path, role: str, *, data_uri: bool) -> dict[str, Any]:
    s = str(source)
    if s.startswith(("http://", "https://")):
        url = s
    else:
        url = encode_image(s, data_uri=data_uri)
    entry: dict[str, Any] = {"type": "image_url", "image_url": {"url": url}}
    if role:
        entry["role"] = role
    return entry


def build_body(
    *,
    prompt: str,
    model: str = "MiniMax-H3",
    duration: int = 5,
    ratio: str = "9:16",
    resolution: str = "720P",
    first_frame: str | Path | None = None,
    last_frame: str | Path | None = None,
    reference_images: list[str | Path] | tuple = (),
    use_context_ir: bool = False,
    aigc_watermark: bool = False,
    return_last_frame: bool = False,
    data_uri: bool = False,
) -> dict[str, Any]:
    """Build the POST body for /api/v2/video_generation."""
    if not str(prompt).strip():
        raise PixStagError("prompt is required (PixStag requires a non-empty text)")
    if model not in MODELS:
        raise PixStagError(f"unsupported model {model!r}; choose from {MODELS}")
    if not (DURATION_MIN <= int(duration) <= DURATION_MAX):
        raise PixStagError(f"duration must be an integer {DURATION_MIN}..{DURATION_MAX}")
    if ratio not in RATIOS:
        raise PixStagError(f"unsupported ratio {ratio!r}; choose from {RATIOS}")
    if resolution not in RESOLUTIONS:
        raise PixStagError(f"unsupported resolution {resolution!r}; choose from {RESOLUTIONS}")
    if len(prompt) > 5000:
        raise PixStagError("prompt exceeds 5000 chars (PixStag limit)")
    if len(reference_images) > 8:
        raise PixStagError("reference_images limited to 8 per call")

    content: list[dict[str, Any]] = [{"type": "text", "text": str(prompt)}]
    if first_frame is not None:
        content.append(_image_entry(first_frame, "first_frame", data_uri=data_uri))
    if last_frame is not None:
        content.append(_image_entry(last_frame, "last_frame", data_uri=data_uri))
    for ref in reference_images:
        content.append(_image_entry(ref, "reference_image", data_uri=data_uri))

    body: dict[str, Any] = {
        "model": model,
        "duration": int(duration),
        "ratio": ratio,
        "resolution": resolution,
        "content": content,
    }
    if use_context_ir:
        body["use_context_ir"] = True
    if aigc_watermark:
        body["aigc_watermark"] = True
    if return_last_frame:
        body["return_last_frame"] = True
    return body


def estimate_credits(duration_s: int, resolution: str) -> float | None:
    """Estimated credit spend. Published rate only covers 720P (1 credit/sec)."""
    rate = _CREDITS_PER_SECOND.get(resolution)
    return round(rate * duration_s, 2) if rate is not None else None


def estimate_usd(duration_s: int, model: str) -> float | None:
    rate = _USD_PER_SECOND.get(model)
    return round(rate * duration_s, 4) if rate is not None else None


def generate_clip(
    *,
    output_path: str | Path,
    timeout_s: float = 600.0,
    poll_interval_s: float = 5.0,
    **body_kwargs: Any,
) -> dict[str, Any]:
    """Full flow: build body -> create -> wait -> download video.

    ``body_kwargs`` are passed to :func:`build_body`. Returns a dict with
    task_id, output_path, duration, usage, credit_estimate and usd_estimate.
    """
    body = build_body(**body_kwargs)
    task_id = create_video(body)
    task = wait_task(task_id, timeout_s=timeout_s, poll_interval_s=poll_interval_s)
    content = task.get("content") or {}
    video_url = content.get("url")
    if not video_url:
        raise PixStagError(f"PixStag task {task_id} succeeded but returned no content.url")
    dest = download_file(video_url, Path(output_path))
    duration_s = body_kwargs.get("duration", 5)
    resolution = body_kwargs.get("resolution", "720P")
    model = body_kwargs.get("model", "MiniMax-H3")
    return {
        "task_id": task_id,
        "output_path": str(dest),
        "model": model,
        "duration": duration_s,
        "ratio": body_kwargs.get("ratio", "9:16"),
        "resolution": resolution,
        "usage": task.get("usage", {}),
        "credit_estimate": estimate_credits(int(duration_s), str(resolution)),
        "usd_estimate": estimate_usd(int(duration_s), str(model)),
        "poster_url": content.get("poster_url"),
        "last_frame_url": content.get("last_frame_url"),
        "note": (
            "Credit estimate is pre-run and covers the published 720P=1 credit/sec rate only; "
            "final billing per PixStag account. Credits expire (~31 days) - see user/me."
        ),
    }
