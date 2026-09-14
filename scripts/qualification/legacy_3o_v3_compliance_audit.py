"""Final 3O v3.0 compliance audit for the creative runtime.

This is the ``LEGACY_3O_V3_COMPLIANCE_AUDIT`` milestone referenced by the
freshness-checked legacy debt ledger.  The audit does not change any status:
it re-derives every gate from committed evidence and emits a single
machine-readable report.

Gates:

1. ``lint``           - the full 3O v3.0 CI matrix passes (``3O_V3_LINT=PASS``).
2. ``legacy_debt``    - every recorded legacy violation is still observed
                        (fresh), and no new element entered the debt ledger.
3. ``capabilities``   - the capability ledger has 0 missing / partial /
                        unqualified capabilities.
4. ``waves``          - every WAVE A-G closure manifest reports QUALIFIED.
5. ``new_elements``   - no new 3O module was introduced since the v3.0
                        baseline, and every newly added element name has a
                        single source across the first-party 3O layers.

Usage::

    python scripts/qualification/legacy_3o_v3_compliance_audit.py [--write]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
BASELINE_COMMIT = "534c448"
EVIDENCE_ROOT = ROOT / "artifacts/qualification/creative-runtime"
OUT = EVIDENCE_ROOT / "legacy-3o-v3-compliance-audit.json"
DEBT = ROOT / "artifacts/qualification/legacy-3o-v3-debt.json"
CLASSIFICATION = "HEVI_3O_CREATIVE_RUNTIME_PRODUCTION_COMPLETE"

if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))

from reconcile_ledger import parse_ledger, resolve_status  # noqa: E402


def _run(script: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(script)], cwd=ROOT, capture_output=True, text=True)


def _lint_gate() -> dict[str, object]:
    proc = _run(ROOT / "scripts/ci/run_3o_v3_lint.py")
    verdict = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "NO_OUTPUT"
    return {"passed": proc.returncode == 0 and verdict == "3O_V3_LINT=PASS", "verdict": verdict}


def _debt_gate() -> dict[str, object]:
    payload = json.loads(DEBT.read_text(encoding="utf-8"))
    checks = payload.get("checks", {})
    freshness: dict[str, bool] = {}
    for name in checks:
        script = ROOT / "scripts/ci" / f"{name}.py"
        proc = _run(script)
        freshness[name] = proc.returncode == 0 and "allowlisted=" in proc.stdout
    entries = sum(len(section.get("allow", ())) for section in checks.values())
    return {
        "passed": all(freshness.values()) and entries > 0,
        "entries": entries,
        "freshness": freshness,
        "policy": payload.get("policy", ""),
    }


def _capability_gate() -> dict[str, object]:
    lines = (
        (ROOT / "docs/research/inkos_capability_ledger.yaml")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    capabilities = parse_ledger(lines)
    statuses = [resolve_status(cap) for cap in capabilities]
    counts = {key: statuses.count(key) for key in ("QUALIFIED", "PARTIAL", "MISSING")}
    unqualified = len(statuses) - sum(counts.values())
    return {
        "passed": (counts["PARTIAL"] == 0 and counts["MISSING"] == 0 and unqualified == 0),
        "total": len(capabilities),
        "qualified": counts["QUALIFIED"],
        "partial": counts["PARTIAL"],
        "missing": counts["MISSING"],
        "unqualified": unqualified,
    }


def _wave_gate() -> dict[str, object]:
    waves: dict[str, str] = {}
    for wave in "ABCDEFG":
        path = EVIDENCE_ROOT / f"wave-{wave.lower()}-closure.json"
        if not path.exists():
            waves[wave] = "MISSING"
            continue
        waves[wave] = str(json.loads(path.read_text(encoding="utf-8")).get("wave_status"))
    return {"passed": all(value == "QUALIFIED" for value in waves.values()), "waves": waves}


def _element_gate() -> dict[str, object]:
    from inventory_3o_assets import build_inventory

    current = build_inventory()["layers"]
    blob = subprocess.check_output(
        [
            "git",
            "show",
            f"{BASELINE_COMMIT}:artifacts/qualification/creative-runtime/3o-asset-inventory.json",
        ],
        cwd=ROOT,
        text=True,
    )
    baseline = json.loads(blob)["layers"]

    added_modules: list[str] = []
    added_elements: list[str] = []
    removed_elements: list[str] = []
    for layer, entry in current.items():
        base_modules = baseline.get(layer, {}).get("modules", {})
        for module, names in entry["modules"].items():
            if module not in base_modules:
                added_modules.append(f"{layer}/{module}")
                added_elements.extend(names)
                continue
            base_names = set(base_modules[module])
            added_elements.extend(
                f"{layer}/{module}::{name}" for name in names if name not in base_names
            )
            removed_elements.extend(
                f"{layer}/{module}::{name}" for name in base_names if name not in names
            )

    locations: dict[str, list[str]] = {}
    for layer, entry in current.items():
        for module, names in entry["modules"].items():
            for name in names:
                if name.startswith("_"):
                    continue
                locations.setdefault(name, []).append(f"{layer}/{module}")
    multi_source = {
        name: sorted(set(paths)) for name, paths in locations.items() if len(set(paths)) > 1
    }
    added_public_names = {
        item.split("::")[-1] for item in added_elements if not item.split("::")[-1].startswith("_")
    }
    conflicting_new = {
        name: multi_source[name] for name in added_public_names if name in multi_source
    }
    return {
        "passed": not added_modules and not conflicting_new,
        "added_modules": sorted(added_modules),
        "added_elements": sorted(added_elements),
        "removed_elements": sorted(removed_elements),
        "conflicting_new_elements": conflicting_new,
    }


def audit() -> dict[str, object]:
    gates = {
        "lint": _lint_gate(),
        "legacy_debt": _debt_gate(),
        "capabilities": _capability_gate(),
        "waves": _wave_gate(),
        "new_elements": _element_gate(),
    }
    passed = all(bool(gate["passed"]) for gate in gates.values())
    return {
        "schema": "hevi.legacy-3o-v3-compliance-audit/v1",
        "spec": "3O Paradigm SPEC v3.0",
        "milestone": "LEGACY_3O_V3_COMPLIANCE_AUDIT",
        "baseline_commit": BASELINE_COMMIT,
        "gates": gates,
        "classification": CLASSIFICATION if passed else "HEVI_3O_CREATIVE_RUNTIME_INCOMPLETE",
        "status": "PASS" if passed else "FAIL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    report = audit()
    if args.write:
        OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"legacy 3O v3 compliance audit written: {OUT.relative_to(ROOT)}")
    for name, gate in report["gates"].items():
        print(f"[{'PASS' if gate['passed'] else 'FAIL'}] {name}")
    print(f"classification={report['classification']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
