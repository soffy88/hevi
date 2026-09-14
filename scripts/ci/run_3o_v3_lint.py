"""3O v3.0 unified lint runner (SPEC §6.1).

Runs the full 3O CI matrix and prints a single machine-readable verdict used by
the per-Wave admission gate::

    3O_V3_LINT=PASS

The matrix is the union of the pre-existing HEVI 3O checks and the v3.0 checks:

  1. check_no_sibling_call          (no bare sibling oprim<->omodul calls)
  2. check_omodul_signature         (workflow triple signature + status return)
  3. check_enabled_pillars          (_enabled_pillars declared)
  4. check_flat_namespace           (flat, unprefixed namespace)
  5. check_no_project_prefix        (no project-prefixed module identity)
  6. check_oprim_keyword_only       (keyword-only primitives)
  7. check_obase_no_reverse_dep     (obase never depends upward)
  8. check_oservi_injection         (mechanism-only, injected handlers)
  9. check_async_contract           (fail-closed async workflow contract)

Legacy pre-v3.0 violations are recognised through the freshness-checked debt
ledger at ``artifacts/qualification/legacy-3o-v3-debt.json``; a new element can
never be admitted through it.

Exit code: 0 = all checks pass, 1 = at least one check failed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / "scripts/ci"

CHECKS = (
    "check_no_sibling_call.py",
    "check_omodul_signature.py",
    "check_enabled_pillars.py",
    "check_flat_namespace.py",
    "check_no_project_prefix.py",
    "check_oprim_keyword_only.py",
    "check_obase_no_reverse_dep.py",
    "check_oservi_injection.py",
    "check_async_contract.py",
)


def main() -> int:
    failures: list[str] = []
    for name in CHECKS:
        proc = subprocess.run(
            [sys.executable, str(CI / name)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        verdict = "PASS" if proc.returncode == 0 else "FAIL"
        print(f"[{verdict}] {name}")
        if proc.returncode != 0:
            failures.append(name)
            output = (proc.stdout + proc.stderr).strip()
            if output:
                print(output)
    if failures:
        print("3O_V3_LINT=FAIL")
        print("failed: " + ", ".join(failures))
        return 1
    print("3O_V3_LINT=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
