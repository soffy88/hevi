"""Preflight checks for the talking-head pipeline (no generation happens here).

Three input families are validated before any expensive stage runs:

* **portrait** — file exists, decodes as an image (PIL), is at least
  ``MIN_PORTRAIT_SIDE`` px on its short side, and contains a *frontal*
  face.  Face detection reuses the talkcraft avatar stack: yoloface-8n
  ONNX via ``hevi.layer4_legacy.talkcraft.omodul_impl._avatar._detect_face``
  (same session / letterbox / decode path as ``build_avatar_clip``), with
  landmarks from ``_detect_landmarks`` for the frontal assessment.  The
  pure decision logic lives in :func:`assess_frontal` so it is testable
  without the model.
* **script** — non-empty, sane length, and an estimated narration
  duration (CJK chars at ~4.2 chars/s + latin words at ~2.5 words/s —
  the measured LuxTTS narration pace band used elsewhere in hevi).
* **voice sample** (optional, Rachel-style clone-sample rules) — format
  MP3 / M4A / WAV, duration 10 s .. 5 min, size <= 20 MB.  The pure rule
  check is :func:`check_voice_sample_metadata`; file probing is a thin
  wrapper around it.

Every check returns measured values next to its threshold — nothing is a
bare boolean claim.  Heavy imports (PIL / onnxruntime via the avatar
module) happen inside functions so importing this module stays cheap.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

__all__ = [
    "MAX_VOICE_SAMPLE_BYTES",
    "MIN_PORTRAIT_SIDE",
    "assess_frontal",
    "check_voice_sample_metadata",
    "count_script_units",
    "default_face_detector",
    "estimate_script_seconds",
    "run_preflight",
    "validate_portrait",
    "validate_script",
    "validate_voice_sample",
]

PORTRAIT_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VOICE_SAMPLE_SUFFIXES = {".mp3", ".m4a", ".wav"}
MAX_VOICE_SAMPLE_BYTES = 20 * 1024 * 1024  # 20 MB (Rachel sample rule)
VOICE_SAMPLE_MIN_S = 10.0
VOICE_SAMPLE_MAX_S = 300.0  # 5 min
MIN_PORTRAIT_SIDE = 256
MIN_FACE_SCORE = 0.5

_CJK_RE = re.compile(r"[一-鿿぀-ヿ가-힯]")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_SENTENCE_END_RE = re.compile(r"[。！？!?…]")

# A face detector maps an image path to
# {"face": (x1, y1, x2, y2, score) | None, "landmarks": [(x, y), ...] | None,
#  "error": str | None}.  Tests inject fakes with this shape (a bare tuple
# (face, landmarks) is also accepted).
FaceDetector = Callable[[Path], Any]


# ---------------------------------------------------------------------------
# script
# ---------------------------------------------------------------------------
def count_script_units(text: str) -> dict[str, Any]:
    """Count narration units in ``text`` (pure)."""
    source = text or ""
    cjk = len(_CJK_RE.findall(source))
    latin_words = len(_WORD_RE.findall(source))
    sentences = len(_SENTENCE_END_RE.findall(source))
    return {
        "chars_total": len(source),
        "chars_no_space": len("".join(source.split())),
        "cjk_chars": cjk,
        "latin_words": latin_words,
        "sentences": sentences,
    }


def estimate_script_seconds(text: str) -> float:
    """Estimated narration seconds for ``text`` (pure).

    CJK at 4.2 chars/s, latin/digit words at 2.5 words/s, plus a 0.15 s
    pause per sentence terminator.  This is a planning estimate for the
    preflight report, not a measured duration.
    """
    units = count_script_units(text)
    seconds = units["cjk_chars"] / 4.2 + units["latin_words"] * 0.4
    seconds += units["sentences"] * 0.15
    # Non-CJK, non-latin-word characters (e.g. kana counted above, other
    # scripts) fall back to the raw non-space character rate.
    covered = units["cjk_chars"] + sum(len(w) for w in _WORD_RE.findall(text or ""))
    other = max(0, units["chars_no_space"] - covered)
    seconds += other / 4.2
    return round(seconds, 2)


def validate_script(
    text: str, *, min_chars: int = 2, max_chars: int = 10_000, max_seconds: float = 900.0
) -> dict[str, Any]:
    """Validate the narration script (pure apart from the input string)."""
    stripped = (text or "").strip()
    units = count_script_units(stripped)
    estimated = estimate_script_seconds(stripped)
    checks = [
        {
            "name": "non_empty",
            "ok": units["chars_no_space"] >= min_chars,
            "value": units["chars_no_space"],
            "threshold": f">= {min_chars} non-space chars",
        },
        {
            "name": "length_cap",
            "ok": units["chars_total"] <= max_chars,
            "value": units["chars_total"],
            "threshold": f"<= {max_chars} chars",
        },
        {
            "name": "estimated_duration",
            "ok": estimated <= max_seconds,
            "value": estimated,
            "threshold": f"<= {max_seconds} s estimated",
        },
    ]
    errors = [f"script check failed: {c['name']} ({c['value']} vs {c['threshold']})" for c in checks if not c["ok"]]
    return {
        "ok": not errors,
        "checks": checks,
        "errors": errors,
        "units": units,
        "estimated_seconds": estimated,
    }


# ---------------------------------------------------------------------------
# portrait: frontal assessment (pure) + yoloface detector (reused)
# ---------------------------------------------------------------------------
def assess_frontal(
    face: tuple[float, float, float, float, float] | None,
    landmarks: list[tuple[float, float]] | None,
    *,
    image_size: tuple[int, int],
    min_score: float = MIN_FACE_SCORE,
) -> dict[str, Any]:
    """Decide whether a detected face counts as frontal (pure).

    ``face`` is ``(x1, y1, x2, y2, score)`` in source pixels (the
    ``_detect_face`` / ``decode_yoloface`` shape).  ``landmarks`` is the
    5-point yoloface layout (left eye, right eye, nose, left mouth,
    right mouth) when available; without landmarks the verdict rests on
    box geometry only and is reported as ``landmarks_checked=False``.
    """
    width, height = image_size
    if face is None:
        return {
            "ok": False,
            "frontal": False,
            "landmarks_checked": False,
            "metrics": {},
            "reasons": ["no face detected"],
        }
    x1, y1, x2, y2, score = (float(v) for v in face)
    fw, fh = max(1.0, x2 - x1), max(1.0, y2 - y1)
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    metrics: dict[str, Any] = {
        "face_box": [round(v, 1) for v in (x1, y1, x2, y2)],
        "face_score": round(score, 4),
        "face_width_share": round(fw / max(1, width), 4),
        "face_height_share": round(fh / max(1, height), 4),
        "face_centre": [round(cx / max(1, width), 4), round(cy / max(1, height), 4)],
        "face_aspect": round(fw / fh, 4),
    }
    reasons: list[str] = []
    if score < min_score:
        reasons.append(f"face score {score:.3f} < {min_score}")
    if not (0.05 <= metrics["face_width_share"] <= 0.95):
        reasons.append(f"face width share {metrics['face_width_share']} outside 0.05..0.95")
    if not (0.2 <= metrics["face_centre"][0] <= 0.8 and 0.1 <= metrics["face_centre"][1] <= 0.9):
        reasons.append("face centre too close to the frame edge")
    if not (0.5 <= metrics["face_aspect"] <= 1.8):
        reasons.append(f"face aspect {metrics['face_aspect']} outside 0.5..1.8")

    landmarks_checked = bool(landmarks) and len(landmarks) >= 3
    if landmarks_checked:
        assert landmarks is not None
        left_eye, right_eye, nose = landmarks[0], landmarks[1], landmarks[2]
        eye_mid_x = (float(left_eye[0]) + float(right_eye[0])) / 2.0
        nose_offset = abs(float(nose[0]) - eye_mid_x) / fw
        eye_tilt = abs(float(left_eye[1]) - float(right_eye[1])) / fh
        metrics["nose_offset_share"] = round(nose_offset, 4)
        metrics["eye_tilt_share"] = round(eye_tilt, 4)
        if nose_offset > 0.20:
            reasons.append(f"nose offset {nose_offset:.3f} of face width > 0.20 (not frontal)")
        if eye_tilt > 0.15:
            reasons.append(f"eye tilt {eye_tilt:.3f} of face height > 0.15 (head tilted/turned)")
    return {
        "ok": not reasons,
        "frontal": not reasons,
        "landmarks_checked": landmarks_checked,
        "metrics": metrics,
        "reasons": reasons,
    }


def default_face_detector(image_path: Path) -> dict[str, Any]:
    """Detect face + landmarks with the talkcraft yoloface stack (reused).

    Uses ``_avatar._detect_face`` (which owns the ONNX session for
    ``/home/soffy/models/wav2lip/yoloface_8n.onnx``) and
    ``_avatar._detect_landmarks`` — exactly the detection ``build_avatar_clip``
    runs before lip-sync, so preflight and rendering agree on the face.
    Never raises: failures come back as ``error`` so the caller records
    them in the ledger instead of crashing the pipeline.
    """
    try:
        from PIL import Image

        from hevi.layer4_legacy.talkcraft.omodul_impl._avatar import (
            _detect_face,
            _detect_landmarks,
        )

        img = Image.open(Path(image_path)).convert("RGB")
        face = _detect_face(img, required=False)
        landmarks = None
        if face is not None:
            try:
                landmarks = _detect_landmarks(img)
            except Exception:
                landmarks = None
        return {"face": face, "landmarks": landmarks, "error": None}
    except Exception as exc:  # model missing, onnxruntime missing, ...
        return {"face": None, "landmarks": None, "error": f"{type(exc).__name__}: {exc}"}


def _normalise_detector_result(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return {
            "face": raw.get("face"),
            "landmarks": raw.get("landmarks"),
            "error": raw.get("error"),
        }
    if isinstance(raw, tuple) and len(raw) == 2:
        return {"face": raw[0], "landmarks": raw[1], "error": None}
    if raw is None:
        return {"face": None, "landmarks": None, "error": None}
    return {"face": raw, "landmarks": None, "error": None}


def validate_portrait(
    path: str | Path,
    *,
    face_detector: FaceDetector | None = None,
    min_side: int = MIN_PORTRAIT_SIDE,
    min_face_score: float = MIN_FACE_SCORE,
    require_face: bool = True,
) -> dict[str, Any]:
    """Validate the portrait image: decodable, big enough, frontal face."""
    portrait = Path(path)
    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    info: dict[str, Any] = {"path": str(portrait)}

    exists = portrait.is_file()
    checks.append({"name": "exists", "ok": exists, "value": str(portrait), "threshold": "file exists"})
    if not exists:
        errors.append(f"portrait not found: {portrait}")
        return {"ok": False, "checks": checks, "errors": errors, "warnings": warnings, **info}

    suffix_ok = portrait.suffix.lower() in PORTRAIT_SUFFIXES
    checks.append(
        {"name": "format_suffix", "ok": suffix_ok, "value": portrait.suffix.lower(),
         "threshold": f"one of {sorted(PORTRAIT_SUFFIXES)}"}
    )
    if not suffix_ok:
        errors.append(f"unsupported portrait suffix: {portrait.suffix}")

    width = height = 0
    image_format: str | None = None
    try:
        from PIL import Image

        with Image.open(portrait) as img:
            img.verify()
        with Image.open(portrait) as img:
            width, height = img.size
            image_format = img.format
        decodable = width > 0 and height > 0
    except Exception as exc:
        decodable = False
        errors.append(f"portrait is not decodable as an image: {exc}")
    checks.append({"name": "decodable", "ok": decodable, "value": image_format, "threshold": "PIL can decode"})
    info.update({"width": width, "height": height, "format": image_format})
    if not decodable:
        return {"ok": False, "checks": checks, "errors": errors, "warnings": warnings, **info}

    size_ok = min(width, height) >= min_side
    checks.append(
        {"name": "min_size", "ok": size_ok, "value": f"{width}x{height}",
         "threshold": f"short side >= {min_side}px"}
    )
    if not size_ok:
        errors.append(f"portrait too small: {width}x{height} (short side < {min_side}px)")

    # Face / frontal check.  Skipped only when the image already failed the
    # size gate (detection on a thumbnail is meaningless) — the failure is
    # already recorded above either way.
    frontal: dict[str, Any] | None = None
    if size_ok:
        detector = face_detector or default_face_detector
        try:
            detected = _normalise_detector_result(detector(portrait))
        except Exception as exc:
            detected = {"face": None, "landmarks": None, "error": f"{type(exc).__name__}: {exc}"}
        if detected.get("error"):
            checks.append(
                {"name": "face_frontal", "ok": not require_face, "value": None,
                 "threshold": "yoloface detection runs", "detail": str(detected["error"])}
            )
            if require_face:
                errors.append(f"face detection unavailable: {detected['error']}")
            else:
                warnings.append(f"face detection unavailable: {detected['error']}")
        else:
            frontal = assess_frontal(
                detected.get("face"),
                detected.get("landmarks"),
                image_size=(width, height),
                min_score=min_face_score,
            )
            checks.append(
                {"name": "face_frontal", "ok": bool(frontal["ok"]), "value": frontal["metrics"],
                 "threshold": f"frontal face, score >= {min_face_score}"}
            )
            if not frontal["ok"]:
                errors.extend(f"portrait face: {r}" for r in frontal["reasons"])
    info["face"] = frontal
    return {"ok": not errors, "checks": checks, "errors": errors, "warnings": warnings, **info}


# ---------------------------------------------------------------------------
# voice sample (optional; Rachel clone-sample rules)
# ---------------------------------------------------------------------------
def check_voice_sample_metadata(
    *, suffix: str, size_bytes: int, duration_s: float | None
) -> dict[str, Any]:
    """Pure Rachel-rule check for a voice sample's metadata."""
    checks = [
        {
            "name": "format",
            "ok": suffix.lower() in VOICE_SAMPLE_SUFFIXES,
            "value": suffix.lower(),
            "threshold": f"one of {sorted(VOICE_SAMPLE_SUFFIXES)}",
        },
        {
            "name": "size",
            "ok": 0 < size_bytes <= MAX_VOICE_SAMPLE_BYTES,
            "value": size_bytes,
            "threshold": f"<= {MAX_VOICE_SAMPLE_BYTES} bytes (20 MB)",
        },
        {
            "name": "duration",
            "ok": duration_s is not None and VOICE_SAMPLE_MIN_S <= duration_s <= VOICE_SAMPLE_MAX_S,
            "value": duration_s,
            "threshold": f"{VOICE_SAMPLE_MIN_S:.0f}s .. {VOICE_SAMPLE_MAX_S:.0f}s",
        },
    ]
    errors = [
        f"voice sample check failed: {c['name']} ({c['value']} vs {c['threshold']})"
        for c in checks
        if not c["ok"]
    ]
    return {"ok": not errors, "checks": checks, "errors": errors}


def _probe_audio_duration(path: Path) -> float:
    """Duration via the talkcraft ffprobe wrapper, WAV fallback via stdlib."""
    try:
        from hevi.layer4_legacy.talkcraft.omodul_impl._media import duration

        return float(duration(path))
    except Exception:
        if path.suffix.lower() == ".wav":
            import wave

            with wave.open(str(path), "rb") as wav:
                return wav.getnframes() / float(wav.getframerate())
        raise


def validate_voice_sample(
    path: str | Path, *, duration_prober: Callable[[Path], float] | None = None
) -> dict[str, Any]:
    """Validate an optional voice-clone sample file (Rachel rules)."""
    sample = Path(path)
    if not sample.is_file():
        return {
            "ok": False,
            "path": str(sample),
            "checks": [],
            "errors": [f"voice sample not found: {sample}"],
        }
    prober = duration_prober or _probe_audio_duration
    try:
        duration_s: float | None = round(float(prober(sample)), 3)
    except Exception as exc:
        duration_s = None
        probe_error = f"could not probe voice sample duration: {exc}"
    else:
        probe_error = None
    result = check_voice_sample_metadata(
        suffix=sample.suffix, size_bytes=sample.stat().st_size, duration_s=duration_s
    )
    if probe_error:
        result["errors"].append(probe_error)
        result["ok"] = False
    result["path"] = str(sample)
    result["duration_s"] = duration_s
    result["size_bytes"] = sample.stat().st_size
    return result


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------
def run_preflight(
    *,
    script_text: str,
    portrait_path: str | Path,
    voice_sample: str | Path | None = None,
    face_detector: FaceDetector | None = None,
    duration_prober: Callable[[Path], float] | None = None,
) -> dict[str, Any]:
    """Run every preflight check and aggregate the verdict."""
    script = validate_script(script_text)
    portrait = validate_portrait(portrait_path, face_detector=face_detector)
    sample = (
        validate_voice_sample(voice_sample, duration_prober=duration_prober)
        if voice_sample
        else None
    )
    errors: list[str] = []
    errors.extend(script["errors"])
    errors.extend(portrait["errors"])
    if sample is not None:
        errors.extend(sample["errors"])
    warnings: list[str] = list(portrait.get("warnings") or [])
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "script": script,
        "portrait": portrait,
        "voice_sample": sample,
        "estimated_seconds": script["estimated_seconds"],
    }
