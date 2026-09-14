"""Shared helpers for the 3O v3.0 CI checks (SPEC v3.0 §6.1).

The 3O v3.0 paradigm fixes a flat namespace, a single source per element, and a
strict layer direction.  Legacy code that predates v3.0 is *recorded*, never
silently fixed or ignored, in ``artifacts/qualification/legacy-3o-v3-debt.json``.

Every check follows the same contract:

  - collect ``violations`` as stable string identifiers,
  - call :func:`report`, which subtracts the recorded legacy allowlist,
  - exit ``0`` only when there is no *blocking* violation and no *stale* debt.

A new element must never appear in the debt ledger; stale entries are treated as
a hard failure so the ledger can only shrink.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEVI = ROOT / "hevi"
CREATIVE = HEVI / "creative"
LAYERS = ("oprim", "oskill", "omodul", "oservi")
OBASE = HEVI / "obase"
DEBT_PATH = ROOT / "artifacts/qualification/legacy-3o-v3-debt.json"

#: Names carrying a project / vendor prefix are not flat 3O names.
FORBIDDEN_PREFIXES = ("hevi", "inkos")


def layer_paths() -> list[Path]:
    """All first-party files that belong to the 3O layers (excluding __init__)."""
    paths: list[Path] = []
    for layer in LAYERS:
        paths.extend(sorted(p for p in (CREATIVE / layer).glob("*.py") if p.name != "__init__.py"))
    return paths


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def has_project_prefix(name: str) -> bool:
    lowered = name.lower()
    return any(
        lowered == prefix or lowered.startswith((prefix + "_", prefix + "-"))
        for prefix in FORBIDDEN_PREFIXES
    )


def allowlist(check_name: str) -> set[str]:
    if not DEBT_PATH.exists():
        return set()
    try:
        payload = json.loads(DEBT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return set(payload.get("checks", {}).get(check_name, {}).get("allow", ()))


def report(check_name: str, violations: list[str], *, header: str) -> int:
    allowed = allowlist(check_name)
    observed = set(violations)
    blocking = sorted(observed - allowed)
    stale = sorted(allowed - observed)
    if blocking or stale:
        print(header)
        for item in blocking:
            print(f"  BLOCK {item}")
        for item in stale:
            print(f"  STALE_DEBT {check_name}: {item}")
        print(f"{check_name}: FAIL (blocking={len(blocking)} stale={len(stale)})")
        return 1
    print(f"{check_name}: PASS (legacy allowlisted={len(allowed)})")
    return 0
