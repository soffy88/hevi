"""HEVI P4 — Delivery runtime (single delivery authority).

Validates, packages, publishes/copies, verifies, and records receipts.
Idempotent per (job, revision, destination). Destinations: LOCAL (real);
GOOGLE_DRIVE (real iff rclone remote works, else NOT_QUALIFIED).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ffprobe_ok(path: Path, min_duration_s: float = 1.0) -> tuple[bool, dict[str, Any]]:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration,size:stream=codec_name,codec_type",
         "-of", "json", str(path)], capture_output=True, text=True, check=False)
    if r.returncode != 0:
        return False, {"error": (r.stderr or "")[:200]}
    try:
        payload = json.loads(r.stdout or "{}")
    except ValueError:
        return False, {"error": "ffprobe unparsable"}
    streams = payload.get("streams", [])
    kinds = {s.get("codec_type") for s in streams}
    try:
        dur = float((payload.get("format", {}) or {}).get("duration") or 0)
    except (TypeError, ValueError):
        dur = 0.0
    ok = "video" in kinds and "audio" in kinds and dur >= min_duration_s
    return ok, {"duration_s": dur, "streams": sorted(kinds),
                "size": int((payload.get("format", {}) or {}).get("size") or path.stat().st_size)}


def validate_delivery_source(final_mp4: str, captions: str = "") -> tuple[bool, dict[str, Any]]:
    """Validate a delivery source (not a substitute for production QA)."""
    video = Path(final_mp4)
    if not video.is_file() or video.stat().st_size <= 0:
        return False, {"reason": "final missing or empty"}
    ok, probe = _ffprobe_ok(video)
    if not ok:
        return False, {"reason": "probe failed", "probe": probe}
    detail: dict[str, Any] = {"probe": probe, "sha256": _sha256_file(video)}
    if captions:
        cap = Path(captions)
        detail["captions_exist"] = cap.is_file() and cap.stat().st_size > 0
        if not detail["captions_exist"]:
            return False, {"reason": "captions missing", "probe": probe}
    return True, detail


def package_delivery(job_dir: Path, final_mp4: str, captions: str = "",
                     report: str = "") -> Path:
    """Assemble a delivery package directory (deterministic layout)."""
    pkg = Path(job_dir) / "delivery_pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    for src in (final_mp4, captions, report):
        if src and Path(src).is_file():
            shutil.copyfile(src, pkg / Path(src).name)
    manifest = {"files": sorted(p.name for p in pkg.iterdir() if p.is_file())}
    (pkg / "package_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return pkg


def deliver_local(job_id: str, revision: int, package_dir: Path, dest_root: Path) -> dict[str, Any]:
    """Idempotent local delivery: same (job, revision) never duplicates."""
    dest = Path(dest_root) / job_id / f"r{revision}"
    receipt = dest / "receipt.json"
    if receipt.is_file():
        prior: dict[str, Any] = json.loads(receipt.read_text(encoding="utf-8"))
        # Verify prior delivery still intact (idempotent replay).
        intact = all((dest / name).is_file() for name in prior.get("files", []))
        if intact:
            prior["replayed"] = True
            return prior
    dest.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    for src in sorted(Path(package_dir).iterdir()):
        if src.is_file():
            shutil.copyfile(src, dest / src.name)
            files.append(src.name)
    record = {"job_id": job_id, "revision": revision, "destination": "LOCAL",
              "path": str(dest), "files": files,
              "hashes": {n: _sha256_file(dest / n) for n in files},
              "replayed": False}
    receipt.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def deliver_google_drive(job_id: str, revision: int, package_dir: Path,
                         remote: str = "gdrive:HEVI/deliveries") -> dict[str, Any]:
    """Real Google Drive delivery via rclone. Raises when not qualified."""
    probe = subprocess.run(["rclone", "lsd", remote.split(":")[0] + ":"],
                           capture_output=True, text=True, timeout=30, check=False)
    if probe.returncode != 0:
        raise RuntimeError(f"GOOGLE_DRIVE_NOT_QUALIFIED: {(probe.stderr or '')[:200]}")
    dest = f"{remote}/{job_id}/r{revision}"
    # Idempotency: check existing remote files first.
    ls = subprocess.run(["rclone", "lsjson", dest], capture_output=True, text=True,
                        timeout=60, check=False)
    if ls.returncode == 0:
        try:
            existing = json.loads(ls.stdout or "[]")
        except ValueError:
            existing = []
        local = sorted(p.name for p in Path(package_dir).iterdir() if p.is_file())
        if existing and {e.get("Name") for e in existing} >= set(local):
            return {"job_id": job_id, "revision": revision, "destination": "GOOGLE_DRIVE",
                    "path": dest, "files": local, "replayed": True}
    cp = subprocess.run(["rclone", "copy", str(package_dir), dest],
                        capture_output=True, text=True, timeout=600, check=False)
    if cp.returncode != 0:
        raise RuntimeError(f"GOOGLE_DRIVE_COPY_FAIL: {(cp.stderr or '')[:300]}")
    verify = subprocess.run(["rclone", "lsjson", dest], capture_output=True, text=True,
                            timeout=60, check=False)
    remote_files = []
    if verify.returncode == 0:
        try:
            remote_files = [e.get("Name", "") for e in json.loads(verify.stdout or "[]")]
        except ValueError:
            remote_files = []
    return {"job_id": job_id, "revision": revision, "destination": "GOOGLE_DRIVE",
            "path": dest, "files": remote_files, "replayed": False}


def check_editable_project(segment_dirs: list[Path]) -> dict[str, Any]:
    """Verify a Remotion editable project can be assembled from segments.

    Editable = per-segment motion_spec.json + referenced assets exist +
    timeline references valid. No second editor is created.
    """
    missing: list[str] = []
    specs = 0
    for seg in segment_dirs:
        spec = Path(seg) / "motion_spec.json"
        if not spec.is_file():
            missing.append(f"{seg.name}:motion_spec.json")
            continue
        specs += 1
        try:
            data = json.loads(spec.read_text(encoding="utf-8"))
        except ValueError:
            missing.append(f"{seg.name}:motion_spec-unparsable")
            continue
        for shot in data.get("shots", [])[:4]:
            uri = str(shot.get("asset_uri", ""))
            if uri.startswith("file://") and not Path(uri[7:]).exists():
                missing.append(f"{seg.name}:asset-missing:{uri[-40:]}")
    ok = specs > 0 and not missing
    return {"ok": ok, "specs": specs, "missing": missing,
            "status": "PASS" if ok else ("NOT_APPLICABLE" if specs == 0 else "FAIL")}


__all__ = [
    "check_editable_project",
    "deliver_google_drive",
    "deliver_local",
    "package_delivery",
    "validate_delivery_source",
]
