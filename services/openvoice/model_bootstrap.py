"""Runtime model acquisition for the isolated OpenVoice service."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path


def model_status() -> dict[str, str]:
    root = Path(os.getenv("OPENVOICE_MODEL_DIR", "/models/openvoice"))
    manifest = root / "model-manifest.json"
    if not manifest.is_file():
        return {"status": "BLOCKED_MODEL_MISSING", "model_dir": str(root), "model": os.getenv("OPENVOICE_MODEL_ID", "")}
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "BLOCKED_MODEL_RUNTIME", "model_dir": str(root), "model": os.getenv("OPENVOICE_MODEL_ID", "")}
    model_file = root / str(payload.get("artifact", ""))
    if not model_file.is_file() or model_file.stat().st_size == 0:
        return {"status": "BLOCKED_MODEL_MISSING", "model_dir": str(root), "model": str(payload.get("model", ""))}
    expected = str(payload.get("sha256", ""))
    actual = hashlib.sha256(model_file.read_bytes()).hexdigest()
    if expected and expected != actual:
        return {"status": "BLOCKED_MODEL_RUNTIME", "reason": "checksum_mismatch", "model_dir": str(root), "model": str(payload.get("model", ""))}
    return {"status": "READY", "model_dir": str(root), "model": str(payload.get("model", "")), "sha256": actual}


def bootstrap_model() -> dict[str, str]:
    url = os.getenv("OPENVOICE_MODEL_URL", "").strip()
    expected = os.getenv("OPENVOICE_MODEL_SHA256", "").strip().lower()
    model = os.getenv("OPENVOICE_MODEL_ID", "").strip()
    root = Path(os.getenv("OPENVOICE_MODEL_DIR", "/models/openvoice"))
    if not url or not expected or not model:
        return {"status": "BLOCKED_MODEL_MISSING", "reason": "OPENVOICE_MODEL_URL, OPENVOICE_MODEL_SHA256 and OPENVOICE_MODEL_ID are required"}
    root.mkdir(parents=True, exist_ok=True)
    artifact = root / "model.bin"
    try:
        urllib.request.urlretrieve(url, artifact)
    except (OSError, urllib.error.URLError) as exc:
        return {"status": "BLOCKED_NETWORK", "reason": type(exc).__name__}
    actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if actual != expected:
        artifact.unlink(missing_ok=True)
        return {"status": "BLOCKED_MODEL_RUNTIME", "reason": "checksum_mismatch"}
    (root / "model-manifest.json").write_text(json.dumps({"model": model, "source": url, "artifact": artifact.name, "sha256": actual}, indent=2) + "\n", encoding="utf-8")
    return model_status()


if __name__ == "__main__":
    print(json.dumps(bootstrap_model(), sort_keys=True))
