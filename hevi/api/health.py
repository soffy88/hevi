"""D7-I: production readiness distinct from liveness.

Liveness = the process/event loop is alive.
Readiness = the process can serve production requests: database, the
differentiation authority stores, and the single-host authority claim all
resolve. Missing optional capabilities (GPU / lip-sync / local runtime) are
reported as ``OPTIONAL_CAPABILITY_BLOCKED`` and never make readiness fail.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


def _authority_stores(identity_db: Path | None = None, incident_db: Path | None = None) -> dict[str, Any]:
    """Open the durable authority stores and report their host claim."""
    from hevi.creative.layer4.identity_store import IdentityStore
    from hevi.creative.layer4.incident_store import IncidentStore
    from hevi.creative.layer4.store_topology import current_claim

    report: dict[str, Any] = {}
    for name, store_cls, db in (
        ("identity", IdentityStore, identity_db),
        ("incident", IncidentStore, incident_db),
    ):
        try:
            store = store_cls(db) if db else store_cls()
            with __import__("sqlite3").connect(str(store.db_path)) as conn:
                claim = current_claim(conn, "identities" if name == "identity" else "incidents")
            report[name] = {"status": "ok", "claim": claim}
        except Exception as exc:  # readiness must not raise
            report[name] = {"status": "unavailable", "error": type(exc).__name__}
    return report


def _gpu_ready() -> bool:
    """True only if a CUDA device is actually usable, not merely that the
    nvidia-smi binary exists (it can be present while the device is gone)."""
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        probe = subprocess.run(
            ["nvidia-smi", "-L"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return False
    text = f"{probe.stdout}\n{probe.stderr}".lower()
    return (
        probe.returncode == 0
        and "no devices were found" not in text
        and "unable to determine the device handle" not in text
    )


def optional_capabilities() -> dict[str, str]:
    """Non-fatal capability states. GPU/lip-sync are optional features."""
    gpu_ready = _gpu_ready()
    return {
        "gpu": "READY" if gpu_ready else "OPTIONAL_CAPABILITY_BLOCKED",
        "lipsync_presenter": "UNQUALIFIED" if gpu_ready else "OPTIONAL_CAPABILITY_BLOCKED",
        "local_gpu_runtime": "UNQUALIFIED" if gpu_ready else "OPTIONAL_CAPABILITY_BLOCKED",
        "ffmpeg": "READY" if shutil.which("ffmpeg") else "REQUIRED_MISSING",
        "ffprobe": "READY" if shutil.which("ffprobe") else "REQUIRED_MISSING",
    }


def readiness_report(*, database_ok: bool) -> dict[str, Any]:
    stores = _authority_stores()
    capabilities = optional_capabilities()
    stores_ok = all(entry.get("status") == "ok" for entry in stores.values())
    ready = bool(database_ok and stores_ok)
    return {
        "status": "ready" if ready else "not_ready",
        "database": "ok" if database_ok else "unavailable",
        "authority_stores": stores,
        "authority_host_claim": "single_host_durable",
        "optional_capabilities": capabilities,
        "degraded": [name for name, state in capabilities.items() if state == "OPTIONAL_CAPABILITY_BLOCKED"],
    }


__all__ = ["optional_capabilities", "readiness_report"]
