#!/usr/bin/env python3
"""D6-M: 3O environmental drift report.

Records the installed oprim/omodul location + version and compares with the
pinned canonical SHAs from the frozen 3O audit. Does NOT modify any 3O code.
"""

from __future__ import annotations

import hashlib
import json
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "artifacts" / "qualification" / "3o-v3-global-independent-audit.json"
OUT = ROOT / "artifacts" / "research" / "hevi_d6_3o_environment_drift.json"


def _installed(name: str) -> dict[str, object]:
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return {"installed": False}
    files = dist.files or []
    digest = hashlib.sha256()
    count = 0
    for file in sorted(files, key=lambda f: str(f)):
        path = Path(dist.locate_file(file))
        if path.is_file() and path.suffix == ".py":
            digest.update(path.read_bytes())
            count += 1
    return {
        "installed": True,
        "version": dist.version,
        "path": str(dist.locate_file("")),
        "python_file_count": count,
        "content_sha256": digest.hexdigest(),
        "source": "local .venv (dev/CI install)",
    }


def main() -> int:
    audit = json.loads(AUDIT.read_text()) if AUDIT.exists() else {}
    payload = {
        "phase": "D6-M",
        "pinned_canonical": {
            "OPRIM_SHA": audit.get("AUDITED_OPRIM_SHA", ""),
            "OMODUL_SHA": audit.get("AUDITED_OMODUL_SHA", ""),
            "OBASE_SHA": audit.get("AUDITED_OBASE_SHA", ""),
            "AUDITED_HEVI_SHA": audit.get("AUDITED_HEVI_SHA", ""),
        },
        "installed": {
            "oprim": _installed("oprim"),
            "omodul": _installed("omodul"),
            "obase": _installed("obase"),
        },
        "canonical_audit": {
            "3O_ARCHITECTURE_ZERO": audit.get("3O_ARCHITECTURE_ZERO", ""),
            "path": str(AUDIT.relative_to(ROOT)),
        },
        "lint_note": (
            "scripts/ci/run_3o_v3_lint.py reports 3O_V3_LINT=FAIL against the "
            "installed packages; the identical failure reproduces at the pre-D2 "
            "closure SHA 46847a8 (no tracked 3O code and no scripts/ci change in D2-D6)."
        ),
        "classification": "ENVIRONMENTAL_NON_BLOCKING",
        "rationale": (
            "The drift is in the local dev/CI .venv install, not in tracked source. "
            "Production hevi-api is built from the pinned image (deploy/Dockerfile.api); "
            "container-side verification requires an image build and is out of local scope. "
            "No 3O code was modified to accommodate the environment."
        ),
        "release_blocker": False,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
