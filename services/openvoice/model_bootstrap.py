"""Pinned, atomic OpenVoice model bootstrap and integrity probe."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SERVICE_ROOT = Path(__file__).resolve().parent
DEFAULT_SPEC = SERVICE_ROOT / "model_spec.json"


def _root() -> Path:
    return Path(os.getenv("OPENVOICE_MODEL_DIR", "/models/openvoice"))


def _load_spec() -> dict[str, Any]:
    path = Path(os.getenv("OPENVOICE_MODEL_SPEC", str(DEFAULT_SPEC)))
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_integrity() -> dict[str, Any]:
    spec = _load_spec()
    root = _root()
    if not spec:
        return {"status": "BLOCKED_MODEL_MISSING", "reason": "model_spec_missing", "model_dir": str(root)}
    if not spec.get("license"):
        return {"status": "BLOCKED_LICENSE", "reason": "model license missing", "model": spec.get("model_name", "")}
    manifest_path = root / "model-manifest.json"
    if not manifest_path.is_file():
        return {"status": "BLOCKED_MODEL_MISSING", "reason": "model_manifest_missing", "model": spec.get("model_name", ""), "model_version": spec.get("model_version", ""), "expected_files": [item["path"] for item in spec.get("files", [])], "cache_path": str(root)}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "BLOCKED_MODEL_CORRUPT", "reason": "invalid_model_manifest", "cache_path": str(root)}
    if manifest.get("model_version") != spec.get("model_version"):
        return {"status": "BLOCKED_MODEL_CORRUPT", "reason": "model_version_mismatch", "cache_path": str(root)}
    for item in spec.get("files", []):
        target = root / item["path"]
        if not target.is_file() or target.stat().st_size == 0:
            return {"status": "BLOCKED_MODEL_MISSING", "reason": f"missing_file:{item['path']}", "cache_path": str(root)}
        expected = str(item.get("sha256", ""))
        if expected and _hash(target) != expected:
            return {"status": "BLOCKED_MODEL_CORRUPT", "reason": f"checksum_mismatch:{item['path']}", "cache_path": str(root)}
    return {"status": "READY", "model": spec["model_name"], "model_version": spec["model_version"], "source": spec["source"], "license": spec["license"], "cache_path": str(root), "files": [item["path"] for item in spec["files"]]}


def model_status() -> dict[str, Any]:
    """Health status includes runtime dependency readiness, not just HTTP reachability."""
    integrity = model_integrity()
    if integrity.get("status") != "READY":
        return integrity
    try:
        import openvoice  # noqa: F401
        import torch  # noqa: F401
    except ImportError as exc:
        return {**integrity, "status": "BLOCKED_MODEL_RUNTIME", "reason": f"runtime_dependency_missing:{exc.name}"}
    return integrity


def _download_atomic(url: str, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        digest = hashlib.sha256()
        with os.fdopen(descriptor, "wb") as output, urllib.request.urlopen(url, timeout=120) as response:
            while chunk := response.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
        if digest.hexdigest() != expected_sha256:
            raise ValueError("checksum_mismatch")
        os.replace(temporary_name, destination)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def bootstrap_model() -> dict[str, Any]:
    spec = _load_spec()
    root = _root()
    if not spec:
        return {"status": "BLOCKED_MODEL_MISSING", "reason": "model_spec_missing"}
    if not spec.get("license"):
        return {"status": "BLOCKED_LICENSE", "reason": "model license missing"}
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return {"status": "BLOCKED_DISK", "reason": "cache_not_writable"}
    for item in spec.get("files", []):
        destination = root / item["path"]
        if destination.is_file() and destination.stat().st_size > 0 and item.get("sha256") and _hash(destination) == item["sha256"]:
            continue
        try:
            _download_atomic(item["url"], destination, str(item["sha256"]))
        except urllib.error.HTTPError as exc:
            return {"status": "BLOCKED_NETWORK", "file": item["path"], "url": item["url"], "http_status": exc.code, "error_class": type(exc).__name__}
        except PermissionError:
            return {"status": "BLOCKED_DISK", "file": item["path"], "reason": "cache_not_writable"}
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {"status": "BLOCKED_NETWORK", "file": item["path"], "url": item["url"], "error_class": type(exc).__name__}
        except ValueError as exc:
            return {"status": "BLOCKED_MODEL_CORRUPT", "file": item["path"], "reason": str(exc)}
    manifest = {"model_name": spec["model_name"], "model_version": spec["model_version"], "source": spec["source"], "license": spec["license"], "files": spec["files"]}
    manifest_path = root / "model-manifest.json"
    temporary_manifest = manifest_path.with_suffix(".tmp")
    temporary_manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary_manifest, manifest_path)
    return model_integrity()


if __name__ == "__main__":
    print(json.dumps(bootstrap_model(), ensure_ascii=False, sort_keys=True))
