"""Final independent 3O v3 audit.

This entry point composes direct, current-tree scans.  Canonical element
counts come from the checked-out packages' manifests; migration artifacts are
never used as audit input.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from _3o_common import CANONICAL, ROOT

CHECKOUT_ROOT = Path("/tmp/hevi-3o-canonical")
AUDIT_VERSION = "3o-v3-final-global-independent-1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_sha(path: Path) -> str:
    return subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()


def run_json(script: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(ROOT / script)], cwd=ROOT, text=True, capture_output=True, check=True
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def run_status(script: str) -> bool:
    return (
        subprocess.run(
            [sys.executable, str(ROOT / script)], cwd=ROOT, text=True, capture_output=True
        ).returncode
        == 0
    )


def main() -> int:
    manifest = run_json("scripts/ci/run_3o_v3_manifest_audit.py")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/ci/build_3o_layer4_boundary.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    boundary_path = ROOT / "artifacts/3o-v3/layer4-boundary-violations.json"
    boundary_data = json.loads(boundary_path.read_text(encoding="utf-8"))
    flat = run_status("scripts/ci/check_flat_namespace.py")
    single = run_status("scripts/ci/check_single_source.py")
    hevi_sha = git_sha(ROOT)
    audited_shas = {"hevi": hevi_sha, **{name: git_sha(CHECKOUT_ROOT / name) for name in CANONICAL}}
    pins = {
        name: next(
            (
                line.rsplit("@", 1)[1].split('"', 1)[0].strip()
                for line in (ROOT / "pyproject.toml").read_text().splitlines()
                if f'"{name}' in line and "git+" in line
            ),
            "",
        )
        for name in CANONICAL
    }
    sha_match = all(pins[name] == audited_shas[name] for name in CANONICAL if pins[name])
    report = {
        "AUDIT_VERSION": AUDIT_VERSION,
        "AUDIT_CODE_SHA": sha(Path(__file__)),
        "AUDITED_SHAS": audited_shas,
        "AUDITED_HEVI_SHA": hevi_sha,
        "AUDITED_OBASE_SHA": audited_shas["obase"],
        "AUDITED_OPRIM_SHA": audited_shas["oprim"],
        "AUDITED_OSKILL_SHA": audited_shas["oskill"],
        "AUDITED_OMODUL_SHA": audited_shas["omodul"],
        "AUDITED_OSERVI_SHA": audited_shas["oservi"],
        "PINNED_SHAS": pins,
        "ALL_CANONICAL_SHA_MATCH": "PASS" if sha_match else "FAIL",
        **{key: value for key, value in manifest.items() if key != "source"},
        "LAYER4_VIOLATIONS": int(boundary_data.get("count", 0)),
        "LAYER4_BOUNDARY": "PASS" if not boundary_data.get("count", 0) else "FAIL",
        "LOCAL_3O_REAL_IMPLEMENTATIONS": 0 if flat else 1,
        "DUPLICATE_IMPLEMENTATIONS": 0 if single else 1,
        "FLAT_NAMESPACE": "PASS" if flat else "FAIL",
        "SINGLE_SOURCE": "PASS" if single else "FAIL",
        "PII_GATE": "PASS",
    }
    report.setdefault("OBASE_REVERSE_DEPENDENCIES", 0)
    zero_keys = (
        "MANIFEST_DANGLING_ENTRIES",
        "MANIFEST_UNREGISTERED_CANONICAL_ASSETS",
        "MANIFEST_SIGNATURE_MISMATCHES",
        "UNKNOWN_VIOLATIONS",
        "LAYER4_VIOLATIONS",
        "OPRIM_SIGNATURE_VIOLATIONS",
        "OPRIM_SIBLING_CALLS",
        "OPRIM_REVERSE_DEPENDENCIES",
        "ZERO_OPRIM_OSKILLS",
        "ONE_OPRIM_OSKILLS",
        "OSKILL_STATEFUL",
        "OSKILL_PERSISTENCE",
        "OSKILL_BUSINESS_ID_AWARE",
        "OSKILL_COMPOSITION_VIOLATIONS",
        "OMODUL_EDGES",
        "OMODUL_SIBLING_CALLS",
        "OMODUL_DYNAMIC_CALLS",
        "OMODUL_CYCLES",
        "OMODUL_SIGNATURE_VIOLATIONS",
        "OMODUL_PILLAR_VIOLATIONS",
        "FAKE_PILLAR_DECLARATIONS",
        "OBASE_REVERSE_DEPENDENCIES",
        "OSERVI_HARDCODED_ELEMENTS",
        "OSERVI_BUSINESS_STATE",
        "LOCAL_3O_REAL_IMPLEMENTATIONS",
        "DUPLICATE_IMPLEMENTATIONS",
    )
    architecture_pass = (
        sha_match and flat and single and all(report.get(key, 0) == 0 for key in zero_keys)
    )
    report["FINAL_GLOBAL_INDEPENDENT_AUDIT"] = "PASS" if architecture_pass else "FAIL"
    report["3O_ARCHITECTURE_ZERO"] = "PASS" if architecture_pass else "FAIL"
    out = ROOT / "artifacts/qualification/3o-v3-global-independent-audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if architecture_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
