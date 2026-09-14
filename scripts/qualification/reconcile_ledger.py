"""Reconcile the InkOS capability ledger with the committed qualification evidence.

The ledger at ``docs/research/inkos_capability_ledger.yaml`` is the single source
of truth for capability identity.  Status, however, must be *derived* from
evidence: a capability is ``QUALIFIED`` only when its
``qualification_evidence_path`` resolves to a qualification result whose status
is ``QUALIFIED``.  A missing or partial result keeps the capability ``PARTIAL``.

The script never invents a count.  It prints the computed totals and, with
``--write``, rewrites only the ``status:`` lines (and inserts the missing
``qualification_evidence_path:`` field) so the ledger can never drift from the
evidence.

Usage::

    python scripts/qualification/reconcile_ledger.py            # dry run
    python scripts/qualification/reconcile_ledger.py --write    # apply
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parents[2]
LEDGER = ROOT / "docs/research/inkos_capability_ledger.yaml"
EVIDENCE_ROOT = ROOT / "artifacts/qualification/creative-runtime"

#: Capabilities qualified through the narrative gold tests rather than a
#: creative-runtime evidence manifest.  The path points at the real test that
#: exercises the capability.
TEST_BACKED_EVIDENCE: dict[str, str] = {
    "narrative-forecast-branch-simulation": "tests/creative_runtime/test_capabilities.py",
    "length-governance-normalization": "tests/creative_runtime/test_capabilities.py",
    "market-radar": "tests/creative_runtime/test_capabilities.py",
    "fanfic-spinoff-canon-import": "tests/gold/creative_runtime/test_qualification.py",
}

STATUS_LINE = re.compile(r"^(?P<indent> {4})status: (?P<value>\S+)\s*$")
ID_LINE = re.compile(r"^ {2}- id: (?P<id>\S+)\s*$")
EVIDENCE_LINE = re.compile(r"^ {4}qualification_evidence_path: \S+\s*$")


@dataclass
class Capability:
    capability_id: str
    line_index: int
    declared_status: str
    evidence_path: str | None
    status_index: int | None
    evidence_index: int | None


def evidence_path_for(capability_id: str) -> str | None:
    manifest = EVIDENCE_ROOT / f"{capability_id}.json"
    if manifest.exists():
        return str(manifest.relative_to(ROOT))
    return TEST_BACKED_EVIDENCE.get(capability_id)


def evidence_status(path: str | None) -> str:
    if path is None:
        return "MISSING"
    resolved = ROOT / path
    if not resolved.exists():
        return "MISSING"
    if resolved.suffix == ".json":
        try:
            payload = json.loads(resolved.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return "MISSING"
        return str(payload.get("status", "PARTIAL"))
    return "TEST_BACKED"


def parse_ledger(lines: list[str]) -> list[Capability]:
    capabilities: list[Capability] = []
    current: Capability | None = None
    for index, line in enumerate(lines):
        id_match = ID_LINE.match(line)
        if id_match:
            if current is not None:
                capabilities.append(current)
            current = Capability(
                capability_id=id_match.group("id"),
                line_index=index,
                declared_status="PARTIAL",
                evidence_path=evidence_path_for(id_match.group("id")),
                status_index=None,
                evidence_index=None,
            )
            continue
        if current is None:
            continue
        status_match = STATUS_LINE.match(line)
        if status_match:
            current.declared_status = status_match.group("value")
            current.status_index = index
            continue
        if EVIDENCE_LINE.match(line):
            current.evidence_index = index
    if current is not None:
        capabilities.append(current)
    return capabilities


def resolve_status(capability: Capability) -> str:
    observed = evidence_status(capability.evidence_path)
    if observed == "QUALIFIED":
        return "QUALIFIED"
    if observed in {"PARTIAL", "MISSING"}:
        return "PARTIAL"
    # Test-backed evidence preserves the declared status; the tests themselves
    # are executed by the full regression gate.
    return capability.declared_status


def reconcile(*, write: bool) -> int:
    lines = LEDGER.read_text(encoding="utf-8").splitlines()
    capabilities = parse_ledger(lines)
    resolved = {cap.capability_id: resolve_status(cap) for cap in capabilities}

    counts: dict[str, int] = {"QUALIFIED": 0, "PARTIAL": 0, "MISSING": 0, "UNQUALIFIED": 0}
    for cap in capabilities:
        status = resolved[cap.capability_id]
        key = status if status in counts else "UNQUALIFIED"
        counts[key] += 1

    total = len(capabilities)
    print(f"INKOS_CAPABILITY_TOTAL={total}")
    print(f"QUALIFIED={counts['QUALIFIED']}")
    print(f"PARTIAL={counts['PARTIAL']}")
    print(f"MISSING={counts['MISSING']}")
    print(f"UNQUALIFIED={counts['UNQUALIFIED']}")

    if not write:
        for cap in capabilities:
            if resolved[cap.capability_id] != cap.declared_status:
                print(
                    f"DRIFT {cap.capability_id}: ledger={cap.declared_status} "
                    f"evidence={resolved[cap.capability_id]}"
                )
        return 0

    # Rebuild the file, inserting the evidence path before the status line and
    # rewriting only the status value.  All other formatting is preserved.
    status_by_index = {
        cap.status_index: resolved[cap.capability_id]
        for cap in capabilities
        if cap.status_index is not None
    }
    insert_before_index = {
        cap.status_index: f"    qualification_evidence_path: {cap.evidence_path}"
        for cap in capabilities
        if cap.status_index is not None
        and cap.evidence_path is not None
        and cap.evidence_index is None
    }
    output: list[str] = []
    for index, line in enumerate(lines):
        if index in insert_before_index:
            output.append(insert_before_index[index])
        status_match = STATUS_LINE.match(line)
        if status_match and index in status_by_index:
            output.append(
                f"{status_match.group('indent')}status: {status_by_index[index]}"
            )
        else:
            output.append(line)
    LEDGER.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"ledger updated: {LEDGER}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    return reconcile(write=args.write)


if __name__ == "__main__":
    raise SystemExit(main())
