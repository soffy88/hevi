"""HEVI OpenVoice provider service (CPU-capable OpenVoice v1 inference).

Contract consumed by hevi.audio.providers.openvoice.OpenVoiceProvider:
  GET  /health, /ready              -> model_status()
  POST /v1/references               -> register reference audio (raw body or multipart "file"), keyed by sha256
  POST /v1/synthesize {text, language, options, reference_sha256} -> {artifact_url, model, ...}
  GET  /v1/artifacts/{name}         -> wav bytes
Reference audio is resolved by sha256 from the registry, or by scanning
OPENVOICE_REFERENCE_DIRS (colon separated, shared read-only mounts).
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from model_bootstrap import model_status
from pydantic import BaseModel

app = FastAPI(title="HEVI OpenVoice optional provider")

MODEL_DIR = Path(os.getenv("OPENVOICE_MODEL_DIR", "/models/openvoice"))
DATA_DIR = Path(os.getenv("OPENVOICE_DATA_DIR", "/data/openvoice"))
REF_DIR = DATA_DIR / "references"
OUT_DIR = DATA_DIR / "artifacts"
SE_DIR = DATA_DIR / "se_cache"
AUDIO_EXT = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac", ".opus"}
LANGS = {"en": ("EN", "English", "en_default_se.pth"), "zh": ("ZH", "Chinese", "zh_default_se.pth")}
_lock = threading.Lock()
_models: dict[str, Any] = {}
_sha_cache: dict[tuple[str, float, int], str] = {}


class SynthesisRequest(BaseModel):
    text: str
    language: str
    options: dict[str, Any] = {}
    reference_sha256: str


def _sha(path: Path) -> str:
    key = (str(path), path.stat().st_mtime, path.stat().st_size)
    if key not in _sha_cache:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _sha_cache[key] = h.hexdigest()
    return _sha_cache[key]


def _find_reference(sha: str) -> Path | None:
    for p in REF_DIR.glob(f"{sha}.*"):
        return p
    for root in filter(None, os.getenv("OPENVOICE_REFERENCE_DIRS", "").split(":")):
        base = Path(root)
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            if p.suffix.lower() in AUDIO_EXT and p.is_file() and p.stat().st_size < 200 << 20:
                try:
                    if _sha(p) == sha:
                        return p
                except OSError:
                    continue
    return None


def _load(lang_code: str):
    import torch
    from openvoice.api import BaseSpeakerTTS, ToneColorConverter

    device = os.getenv("OPENVOICE_DEVICE", "cpu")
    if "converter" not in _models:
        # Upstream v1 ToneColorConverter cannot take enable_watermark (passes it to the base
        # __init__) and otherwise imports wavmark, whose weights live on HF. Stub it so the
        # watermark model is None (add_watermark is then a no-op).
        import sys
        import types

        if "wavmark" not in sys.modules:
            sys.modules["wavmark"] = types.SimpleNamespace(
                load_model=lambda: types.SimpleNamespace(to=lambda *_a, **_k: None)
            )
        conv = ToneColorConverter(str(MODEL_DIR / "checkpoints/converter/config.json"), device=device)
        conv.load_ckpt(str(MODEL_DIR / "checkpoints/converter/checkpoint.pth"))
        _models["converter"] = conv
    if lang_code not in _models:
        folder, _, se_file = LANGS[lang_code]
        base_dir = MODEL_DIR / "checkpoints/base_speakers" / folder
        tts = BaseSpeakerTTS(str(base_dir / "config.json"), device=device)
        tts.load_ckpt(str(base_dir / "checkpoint.pth"))
        _models[lang_code] = (tts, torch.load(str(base_dir / se_file), map_location=device))
    return _models["converter"], _models[lang_code]


@app.get("/health")
def health() -> dict[str, Any]:
    return model_status()


@app.get("/ready")
def ready() -> dict[str, Any]:
    return model_status()


@app.post("/v1/references")
async def register_reference(request: Request) -> dict[str, Any]:
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/"):
        form = await request.form()
        upload = form.get("file")
        if upload is None:
            raise HTTPException(422, "multipart field 'file' required")
        data, name = await upload.read(), upload.filename or "ref.wav"
    else:
        data, name = await request.body(), request.headers.get("x-filename", "ref.wav")
    if not data:
        raise HTTPException(422, "empty reference audio")
    sha = hashlib.sha256(data).hexdigest()
    suffix = Path(name).suffix.lower() if Path(name).suffix.lower() in AUDIO_EXT else ".wav"
    REF_DIR.mkdir(parents=True, exist_ok=True)
    (REF_DIR / f"{sha}{suffix}").write_bytes(data)
    return {"reference_sha256": sha, "bytes": len(data)}


@app.post("/v1/synthesize")
def synthesize(req: SynthesisRequest) -> dict[str, Any]:
    status = model_status()
    if status.get("status") != "READY":
        raise HTTPException(status_code=503, detail=status)
    lang = (req.language or "en").lower()[:2]
    if lang not in LANGS:
        raise HTTPException(422, f"unsupported language for OpenVoice v1 checkpoints: {req.language} (en, zh)")
    if not req.text.strip():
        raise HTTPException(422, "empty text")
    ref = _find_reference(req.reference_sha256)
    if ref is None:
        raise HTTPException(404, {"status": "REFERENCE_NOT_FOUND", "reference_sha256": req.reference_sha256,
                                  "hint": "POST /v1/references first, or place it under OPENVOICE_REFERENCE_DIRS"})
    import torch

    opts = req.options or {}
    speaker = str(opts.get("speaker") or "default")
    speed = float(opts.get("speed") or 1.0)
    tau = float(opts.get("tau") or 0.3)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SE_DIR.mkdir(parents=True, exist_ok=True)
    started = time.time()
    with _lock:
        conv, (tts, source_se) = _load(lang)
        if lang == "zh":
            speaker = "default"
        if speaker not in tts.hps.speakers:
            speaker = "default"
        se_path = SE_DIR / f"{req.reference_sha256}.pth"
        if se_path.is_file():
            target_se = torch.load(str(se_path), map_location=conv.device)
        else:
            target_se = conv.extract_se([str(ref)], se_save_path=str(se_path))
        job = uuid.uuid4().hex
        src = OUT_DIR / f"{job}.base.wav"
        out = OUT_DIR / f"{job}.wav"
        tts.tts(req.text, str(src), speaker=speaker, language=LANGS[lang][1], speed=speed)
        conv.convert(audio_src_path=str(src), src_se=source_se, tgt_se=target_se, output_path=str(out), tau=tau)
        src.unlink(missing_ok=True)
    return {
        "artifact_url": f"/v1/artifacts/{out.name}",
        "model": f"{status.get('model')}@{status.get('model_version')}",
        "language": lang,
        "speaker": speaker,
        "elapsed_s": round(time.time() - started, 2),
        "device": os.getenv("OPENVOICE_DEVICE", "cpu"),
    }


@app.get("/v1/artifacts/{name}")
def artifact(name: str) -> FileResponse:
    path = OUT_DIR / Path(name).name
    if not path.is_file():
        raise HTTPException(404, "artifact not found")
    return FileResponse(path, media_type="audio/wav")
