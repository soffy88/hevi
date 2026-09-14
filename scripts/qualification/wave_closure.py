"""Write a per-wave closure manifest from committed qualification evidence.

The manifest is a review artifact, not a status source: every entry is read from
the capability evidence file, and the ledger counts are recomputed from
``docs/research/inkos_capability_ledger.yaml``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
LEDGER = ROOT / "docs/research/inkos_capability_ledger.yaml"
EVIDENCE_ROOT = ROOT / "artifacts/qualification/creative-runtime"

WAVE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "A": (
        "continuity-and-multidimensional-audit",
        "governed-revision",
        "extensible-genre-system",
        "synthetic-writing-quality",
    ),
    "B": (
        "existing-work-import-continuation",
        "longform-narrative-production",
        "short-fiction-production",
    ),
    "C": (
        "unified-agent-production-harness",
        "production-storyboard",
    ),
}


def _ledger_counts() -> dict[str, int]:
    payload = yaml.safe_load(LEDGER.read_text(encoding="utf-8"))
    counts = {"QUALIFIED": 0, "PARTIAL": 0, "MISSING": 0, "UNQUALIFIED": 0}
    for capability in payload["capabilities"]:
        status = capability["status"]
        counts[status if status in counts else "UNQUALIFIED"] += 1
    counts["TOTAL"] = len(payload["capabilities"])
    return counts


def build_manifest(wave: str) -> dict[str, object]:
    capabilities = WAVE_CAPABILITIES[wave]
    entries: list[dict[str, object]] = []
    for capability_id in capabilities:
        path = EVIDENCE_ROOT / f"{capability_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        checks = payload.get("checks", {})
        entries.append(
            {
                "capability_id": capability_id,
                "status": payload.get("status"),
                "evidence_path": str(path.relative_to(ROOT)),
                "checks_passed": all(checks.values()) and bool(checks),
                "check_count": len(checks),
                "details": payload.get("details", {}),
            }
        )
    all_qualified = all(entry["status"] == "QUALIFIED" for entry in entries)
    return {
        "wave": wave,
        "capabilities": entries,
        "wave_status": "QUALIFIED" if all_qualified else "PARTIAL",
        "ledger": _ledger_counts(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wave", required=True, choices=sorted(WAVE_CAPABILITIES))
    args = parser.parse_args()
    manifest = build_manifest(args.wave)
    output = EVIDENCE_ROOT / f"wave-{args.wave.lower()}-closure.json"
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    ledger = manifest["ledger"]
    print(f"wave {args.wave}: {manifest['wave_status']} -> {output}")
    assert isinstance(ledger, dict)
    print(
        "ledger: "
        f"TOTAL={ledger['TOTAL']} QUALIFIED={ledger['QUALIFIED']} "
        f"PARTIAL={ledger['PARTIAL']} MISSING={ledger['MISSING']} "
        f"UNQUALIFIED={ledger['UNQUALIFIED']}"
    )
    return 0 if manifest["wave_status"] == "QUALIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
